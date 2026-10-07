# justicier - Automated employee justifications
# Copyright (C) 2026  Aleix Mariné Tena (AleixMT), Carles de la Cuadra
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""PDF page extraction, matching, merging, and salary-type classification."""

import locale
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pypdf
from pypdf import PdfReader, PdfWriter

from .custom_except import UndefinedSalaryTypeError, UndefinedProofTypeError
from .data import parse_salary_type_from_file_suffix, map_folder_suffix_to_proof_type
from .dates import unparse_month
from .defines import (
    ProofFileSuffix,
    SalaryType,
    ProofType,
    BBVAFolderSuffixes,
    LaCaixaFolderSuffixes,
)
from .filesystem import list_dir
from .logger import get_logger

log = get_logger(__name__)


def get_dni(pdf_path: Path) -> str:
    """Extract the first DNI/NIE string found in any page of the PDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        The matched identifier string.

    Raises:
        ValueError: If no DNI/NIE pattern is found in the document.
    """
    reader = PdfReader(pdf_path)

    pattern = re.compile("[A-Z]\\d{7}[A-Z]|\\d{8}[A-Z]")

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()

        if not text:
            continue

        match = pattern.search(text)
        if not match:
            continue

        dni = match.group(0)
        return dni
    raise ValueError(f"DNI could not be detected in PDF {pdf_path}")


def write_page(page: pypdf.PageObject, path: Path) -> None:
    """Write a single PDF page to a new file at *path*.

    Args:
        page: The PDF page object to write.
        path: Destination file path (created or overwritten).
    """
    writer = PdfWriter()
    writer.add_page(page)

    with open(path, "wb+") as output_pdf:
        writer.write(output_pdf)


def get_matching_pages(
    pdf_path: Path, query_string: str, pattern_str: str = r"\d{2}/\d{8}-\d{2}"
) -> List[Tuple[pypdf.PageObject, int]]:
    """Return all pages whose extracted text contains *query_string* matched by *pattern_str*.

    Args:
        pdf_path: Path to the PDF file.
        query_string: Exact string to look for among pattern matches.
        pattern_str: Regex pattern used to find candidates on each page.

    Returns:
        List of ``(page, page_number)`` tuples for all matching pages.
    """
    reader = PdfReader(pdf_path)

    pattern = re.compile(pattern_str)
    pages = []

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text:
            continue

        match = pattern.findall(text)
        if not match:
            continue

        match_selected = None
        for match_i in match:
            if match_i == query_string:
                match_selected = match_i
                break

        if match_selected is not None:
            pages.append((page, page_num))
    return pages


def get_matching_page(
    pdf_path: Path, query_string: str, pattern_str: str = r"\d{2}/\d{8}-\d{2}"
) -> pypdf.PageObject:
    """Return the last page whose extracted text contains *query_string*.

    Args:
        pdf_path: Path to the PDF file.
        query_string: Exact string to look for among pattern matches.
        pattern_str: Regex pattern used to find candidates on each page.

    Returns:
        The matching page object.

    Raises:
        ValueError: If *query_string* is not found in any page of the document.
    """
    reader = PdfReader(pdf_path)

    pattern = re.compile(pattern_str)

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text:
            continue

        match = pattern.findall(text)
        if not match:
            continue

        match_selected = None
        for match_i in match:
            if str(match_i) == query_string:
                match_selected = match_i

        if match_selected is not None:
            return page

    raise ValueError(f"The string {query_string} can't be found in the file {pdf_path}")


def parse_dates_from_delayed_salary(
    page: pypdf.PageObject,
) -> tuple[datetime, datetime]:
    """Extract the start and end dates from a delayed-salary (atrasos) page.

    Args:
        page: The PDF page object to parse.

    Returns:
        Tuple of ``(start_date, end_date)`` parsed from the Spanish date range text.

    Raises:
        ValueError: If the page text is empty or the date range pattern is not found.
    """
    _months = (
        r"Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto"
        r"|Septiembre|Octubre|Noviembre|Diciembre"
    )
    query_str = (
        rf"\d{{1,2}}\s+({_months})\s+20\d{{2}}"
        rf"\s+a\s+\d{{1,2}}\s+({_months})\s+20\d{{2}}"
    )
    pattern = re.compile(query_str, re.MULTILINE)

    text = page.extract_text()
    if not text:
        raise ValueError("Could not extract text from delayed salary page")

    match = pattern.search(text)
    if not match:
        raise ValueError("Could not find date range in delayed salary page")

    match_str = match.group(0)
    match_str = match_str.replace("\n", "")

    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")

    start_str, end_str = match_str.split(" a ")

    start_date = datetime.strptime(start_str.strip(), "%d %B %Y")
    end_date = datetime.strptime(end_str.strip(), "%d %B %Y")
    return start_date, end_date


def is_monthly_salary(salary_page: pypdf.PageObject) -> bool:
    """Return True if the page contains the monthly salary marker text.

    Args:
        salary_page: PDF page to inspect.

    Returns:
        True if a ``"Mensual -"`` pattern is found in the extracted text.
    """
    text = salary_page.extract_text()

    if not text:
        return False

    pattern_str = r".*Mensual -.*"
    pattern = re.compile(pattern_str)

    match = pattern.findall(text)

    if not match:
        return False

    if len(match) > 0:
        return True

    return False


def is_settlement_salary(salary_page: pypdf.PageObject) -> bool:
    """Return True if the page contains the settlement (finiquito) marker text.

    Args:
        salary_page: PDF page to inspect.

    Returns:
        True if ``"Vacaciones Finiquito"`` is found in the extracted text.
    """
    text = salary_page.extract_text()
    if not text:
        return False

    pattern_str = r"Vacaciones Finiquito"
    pattern = re.compile(pattern_str)

    match = pattern.findall(text)
    if match:
        return True
    return False


def parse_salary_type(
    salary_page: pypdf.PageObject, salary_file_suffix: ProofFileSuffix
) -> SalaryType:
    """Classify a regular salary page as monthly or settlement.

    Args:
        salary_page: PDF page to classify.
        salary_file_suffix: A salary file suffix computed from the filename where the file is.

    Returns:
        The detected RegularSalaryType.

    Raises:
        UndefinedRegularSalaryTypeError: If the page does not match either known subtype.
    """
    if salary_file_suffix == ProofFileSuffix.REGULAR:
        if is_monthly_salary(salary_page):
            return SalaryType.MONTHLY
        elif is_settlement_salary(salary_page):
            return SalaryType.SETTLEMENT
        else:
            raise UndefinedSalaryTypeError("The type was not recognized")
    return parse_salary_type_from_file_suffix(salary_file_suffix)


def is_monthly_proof(proof_page: pypdf.PageObject) -> bool:
    """Return True if the page contains the monthly proof marker text."""
    return False


def is_settlement_proof(proof_page: pypdf.PageObject) -> bool:
    """Return True if the page contains the settlement proof marker text."""
    return False


def parse_proof_type(
    proof_page: pypdf.PageObject,
    proof_file_suffix: BBVAFolderSuffixes | LaCaixaFolderSuffixes,
) -> ProofType:
    """Classify a proof page with its type.

    Args:
        proof_page: PDF page to classify.
        proof_file_suffix: A proof file suffix computed from the filename where the file is.

    Returns:
        The detected ProofType.

    Raises:
        UndefinedProofTypeError: If the page does not match either known subtype.
    """
    if (
        proof_file_suffix == BBVAFolderSuffixes.REGULAR
        or proof_file_suffix == LaCaixaFolderSuffixes.REGULAR
    ):
        if is_monthly_proof(proof_page):
            return ProofType.MONTHLY
        elif is_settlement_proof(proof_page):
            return ProofType.SETTLEMENT
        else:
            raise UndefinedProofTypeError("The type was not recognized")
    return map_folder_suffix_to_proof_type(proof_file_suffix)


def merge_pdfs(
    pdf_paths: List[Path], output_path: Path, all_pages: bool = False
) -> None:
    """Merge multiple PDF files into a single output PDF.

    Args:
        pdf_paths: List of paths to PDF files to merge.
        output_path: Destination path for the merged PDF.
        all_pages: If True, include all pages from each source file;
            otherwise only the first page of each file is included.
    """
    pdf_writer = pypdf.PdfWriter()
    for filename in pdf_paths:
        pdf_file = open(filename, "rb")
        pdf_reader = pypdf.PdfReader(pdf_file)
        if all_pages:
            for i in range(len(pdf_reader.pages)):
                pdf_writer.add_page(pdf_reader.pages[i])
        else:
            pdf_writer.add_page(pdf_reader.pages[0])
    with open(output_path, "wb") as f:
        pdf_writer.write(f)


def is_date_present_in_rlc_delay(
    delay_begin: datetime, delay_end: datetime, document_path: Path
) -> bool:
    """Return True if the RLC delay document covers the given date range.

    Args:
        delay_begin: Start date of the delay period.
        delay_end: End date of the delay period.
        document_path: Path to the RLC PDF to inspect.

    Returns:
        True if the formatted date range string is found in any page.
    """
    reader = PdfReader(document_path)
    query_string = f"{unparse_month(delay_begin)}/{delay_begin.year} - {unparse_month(delay_end)}/{delay_end.year}"
    pattern = re.compile(query_string)

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text:
            continue

        match = pattern.findall(text)
        if not match:
            continue

        log.debug(f"Detected this matches: {match}")
        for match_i in match:
            if match_i == query_string:
                return True

    return False


def compact_folder(path_folder: Path) -> None:
    """Merge all PDFs in a folder into a single file, then remove the folder.

    Expects *path_folder* to contain only PDF files. The merged output is written
    to ``path_folder.pdf`` alongside the original folder.
    """
    names = list_dir(path_folder)
    if len(names) == 0:
        log.warning(
            f"Refusing to compact folder {path_folder} because it is empty. Aborting compression."
        )
        return

    names.sort()
    paths = [path_folder / name for name in names]
    merge_pdfs(paths, path_folder.parent / (path_folder.name + ".pdf"), True)
    shutil.rmtree(path_folder)


def merge_equal_files_from_two_folders(
    folder1: Path, folder2: Path, folder_out: Path
) -> None:
    """Merge PDF files with matching names from two folders into a third folder.

    Args:
        folder1: First source folder.
        folder2: Second source folder.
        folder_out: Destination folder for merged files.
    """
    log.info(
        f"Merging files with same name in folders {folder1} and {folder2} and outputting them in "
        f"{folder_out}."
    )
    files1 = list_dir(folder1)
    if len(files1) == 0:
        log.warning(
            f"Refusing to compact folders because {folder1} is empty. Aborting compression."
        )
        return
    files2 = list_dir(folder2)
    if len(files2) == 0:
        log.warning(
            f"Refusing to compact folders because {folder2} is empty. Aborting compression."
        )
        return

    for i in range(len(files1)):
        for j in range(len(files2)):
            if files1[i] == files2[j]:
                path1 = folder1 / files1[i]
                path2 = folder2 / files2[j]
                out_path = folder_out / files1[i]
                log.info(f"Matched {path1} with {path2} and merging into {out_path}.")
                merge_pdfs([path1, path2], out_path)
