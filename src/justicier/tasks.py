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

"""Document processing tasks: salary/RLC extraction, proofs, contracts, and RNTs."""

import shutil
from datetime import datetime
from pathlib import Path

import pypdf
from dateutil.relativedelta import relativedelta

from .dates import (
    unparse_month,
    unparse_date,
    parse_salary_date,
    parse_salary_type,
    parse_rnt_date,
    parse_contract_dates,
    unparse_year_month,
    unparse_year_month_short,
    datetime_range,
)
from .nif import NIF
from .naf import NAF
from .custom_except import (
    UndefinedRegularSalaryTypeError,
    InvalidFilenameError,
)
from .data import (
    get_rlc_monthly_result_structure,
    get_rnt_monthly_result_structure,
    parse_proof_folder_name,
)
from .defines import (
    SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME,
    SalaryType,
    RegularSalaryType,
    RLCTypeFileName,
    SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME,
    RLCSubType,
    RLCType,
    BankType,
)

from .filesystem import flatten_dirs, list_dir

from .pdf import (
    get_matching_page,
    write_page,
    parse_dates_from_delayed_salary,
    is_date_present_in_rlc_delay,
    merge_pdfs,
    parse_regular_salary_type,
    get_matching_pages,
)
from .logger import get_logger

log = get_logger(__name__)


def process_rlc_aux(
    salary_date: datetime,
    rlc_folder_path: Path,
    months_found: dict[datetime, list[bool]],
    rlc_subtype: RLCSubType,
    rlc_type: RLCType,
) -> Path:
    """Locate one RLC sub-document (N or P) and mark it as found in *months_found*.

    Args:
        salary_date: Date of the corresponding salary.
        rlc_folder_path: Root folder containing RLC files.
        months_found: Per-month result structure to update in-place.
        rlc_subtype: Sub-document type, either ``"N"`` or ``"P"``.
        rlc_type: RLC type code, e.g. ``"L00"``, ``"L03"``, ``"L13"``.

    Returns:
        Path to the found RLC file.

    Raises:
        ValueError: If the expected RLC file does not exist.
    """
    month = unparse_month(salary_date)
    year = str(salary_date.year)
    # TODO: I do not get the 01 suffix, maybe missing loop
    n_name = month + "_" + rlc_type.value + rlc_subtype.value + "01.pdf"
    rlc_n_path = rlc_folder_path / year / n_name
    if rlc_n_path.exists():
        log.debug(f"The RLC {rlc_n_path} is present.")
        if rlc_subtype == RLCSubType.NOMINAL:
            months_found[salary_date][1] = True
        elif rlc_subtype == RLCSubType.PAYMENT:
            months_found[salary_date][2] = True
        return rlc_n_path
    else:
        log.error(
            f"Monthly salary was found, but the expected L{rlc_type.value} RLC of type "
            f"{rlc_subtype.value} was not found in the expected location {rlc_n_path}. "
            f"Skipping merge of this salary file."
        )
        raise ValueError("File was not detected")  # TODO custom except


def process_generic_rlc(
    rlc_type: RLCType,
    salary_date: datetime,
    salary_file_path: Path,
    rlc_folder_path: Path,
    naf_dir: Path,
    salaries_found: dict[datetime, list[bool]],
) -> None:
    """Locate and merge both RLC sub-documents (N and P) for a regular or settlement salary.

    Args:
        rlc_type: RLC type code (``"00"`` for regular, ``"13"`` for settlement).
        salary_date: Date of the corresponding salary.
        salary_file_path: Path to the salary PDF (for logging only).
        rlc_folder_path: Root folder containing RLC files.
        naf_dir: Output directory for the employee.
        salaries_found: Per-month result structure updated in-place.
    """
    salaries_found[salary_date][0] = True
    try:
        rlc_n_path = process_rlc_aux(
            salary_date, rlc_folder_path, salaries_found, RLCSubType.NOMINAL, rlc_type
        )
        log.debug(f"Expected RLC N path is: {rlc_n_path}")
        rlc_p_path = process_rlc_aux(
            salary_date, rlc_folder_path, salaries_found, RLCSubType.PAYMENT, rlc_type
        )
        log.debug(f"Expected RLC P path is: {rlc_p_path}")
    except ValueError:
        log.error(
            f"Some of the RLC documents (N or P) has not been found. "
            f"The salary file {salary_file_path} will be skipped."
        )
        return

    pdf_merged_name = (
        str(salary_date.year)
        + unparse_month(salary_date)
        + "_"
        + rlc_type.value
        + "Merge.pdf"
    )
    merge_pdfs(
        [rlc_n_path, rlc_p_path],
        naf_dir / SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME / pdf_merged_name,
    )


def process_rlc_l03(
    salary_file_path: Path,
    salary_page_number: int,
    salary_page: pypdf.PageObject,
    salary_date: datetime,
    naf_dir: Path,
    rlc_folder_path: Path,
    months_found: dict[datetime, list[bool]],
) -> None:
    """Locate and merge the L03 RLC documents matching a delay (atrasos) salary page.

    Args:
        salary_file_path: Path to the salary PDF.
        salary_page_number: Zero-based page index of the delay salary.
        salary_page: The delay salary page object (used to extract its date range).
        salary_date: Date of the salary file.
        naf_dir: Output directory for the employee.
        rlc_folder_path: Root folder containing RLC files.
        months_found: Per-month result structure updated in-place.
    """
    log.info(
        f"Salary file {salary_file_path} page {salary_page_number + 1} has been "
        f"selected as delay salary for date {unparse_date(salary_date)}"
    )
    try:
        delay_initial_date, delay_end_date = parse_dates_from_delayed_salary(
            salary_page
        )
    except ValueError as exc:
        log.error(
            f"The delay date could not be parsed from the delay salary page. "
            f"This document will be skipped from search. The internal error is {exc}"
        )
        return
    log.debug(
        "Initial date is "
        + unparse_date(delay_initial_date, "-")
        + " and end date is "
        + unparse_date(delay_end_date, "-")
    )

    rlc_dir = naf_dir / rlc_folder_path / str(salary_date.year)
    rlc_stem = unparse_month(salary_date) + "_" + RLCType.DELAY.value

    suffix = 1
    while suffix < 100:
        str_suffix = str(suffix).zfill(2)
        rlc_path_n = rlc_dir / (
            rlc_stem + RLCSubType.NOMINAL.value + str_suffix + ".pdf"
        )
        if not rlc_path_n.exists():
            log.debug(f"Breaking out of the bucle because {rlc_path_n} does not exist.")
            break
        if is_date_present_in_rlc_delay(delay_initial_date, delay_end_date, rlc_path_n):
            months_found[salary_date][1] = True
            rlc_path_p = rlc_dir / (
                rlc_stem + RLCSubType.PAYMENT.value + str_suffix + ".pdf"
            )
            pdf_merged_name = (
                f"{salary_date.year}{unparse_month(salary_date)}_"
                f"{RLCType.DELAY.value}Merge{str_suffix}.pdf"
            )
            pdf_output_path = (
                naf_dir / SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME / pdf_merged_name
            )
            if not rlc_path_p.exists():
                log.debug(
                    f"Breaking out of the bucle because {rlc_path_p} does not exist."
                )
            months_found[salary_date][2] = True
            merge_pdfs([rlc_path_n, rlc_path_p], pdf_output_path)
            break
        suffix += 1


def process_salaries_with_rlc(
    salaries_folder_path: Path,
    rlc_folder_path: Path,
    naf_dir: Path,
    naf: NAF,
    begin: datetime,
    end: datetime,
) -> tuple[dict[RLCTypeFileName, dict[datetime, list[bool]]], bool]:
    """Extract salary pages for *naf* and locate their matching RLC documents.

    Args:
        salaries_folder_path: Root folder containing salary PDFs.
        rlc_folder_path: Root folder containing RLC PDFs.
        naf_dir: Output directory for the employee.
        naf: NAF identifier of the employee.
        begin: Start of the justification period.
        end: End of the justification period.

    Returns:
        Nested dict mapping each RLCType to a per-month found/not-found structure.
    """
    regular_monthly_salaries_rlcs_found = get_rlc_monthly_result_structure(begin, end)
    regular_settlement_salaries_rlcs_found = get_rlc_monthly_result_structure(
        begin, end
    )
    delay_salaries_rlcs_found = get_rlc_monthly_result_structure(begin, end)

    salary_files = flatten_dirs(salaries_folder_path)
    salary_files_selected = []
    for salary_file in salary_files:
        try:
            dir_date = parse_salary_date(salary_file)
        except InvalidFilenameError as e:
            log.error(f"Salary file {salary_file} has an invalid name, skipping: {e}")
            continue
        if begin <= dir_date <= end:
            salary_files_selected.append(salary_file)
            log.info(
                f"Salary file {salary_file} is selected, because its date is {unparse_date(dir_date, '-')}."
            )
        else:
            log.trace(
                f"Salary file {salary_file} is not selected, because its date is {unparse_date(dir_date, '-')}."
            )

    scanned_liquidation_salary_found = False
    salary_files_selected.sort()
    for salary_file in salary_files_selected:
        log.debug(f"Processing file {salary_file}")
        salary_file_path = salaries_folder_path / salary_file
        try:
            salary_date = parse_salary_date(salary_file_path)
            salary_type = parse_salary_type(salary_file_path)
        except InvalidFilenameError as e:
            log.error(f"Salary file {salary_file} has an invalid name, skipping: {e}")
            continue
        salary_output_filename_base = (
            f"{unparse_year_month(salary_date)}_{salary_type.value}"
        )
        # Liquidation files
        if salary_type == SalaryType.LIQ:
            salary_file_liq_naf = salary_file_path.stem.split("_")[2]
            if salary_file_liq_naf != str(naf):
                log.trace(
                    f"NAF {str(naf)} was not detected in the name of liquidation PDF {salary_file}. Skipping document."
                )
                continue
            shutil.copy(
                src=salary_file_path,
                dst=naf_dir
                / SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME
                / (salary_output_filename_base + ".pdf"),
            )
            scanned_liquidation_salary_found = True

        salary_pages = get_matching_pages(salary_file_path, naf.slash_dash_str())
        if len(salary_pages) == 0:
            log.debug(
                f"NAF {str(naf)} was not detected in PDF {salary_file}. Skipping document."
            )
            continue
        for salary_page, salary_page_number in salary_pages:
            salary_output_path = (
                naf_dir
                / SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME
                / (salary_output_filename_base + ".pdf")
            )

            index = 1
            while salary_output_path.exists():
                salary_output_path = (
                    naf_dir
                    / SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME
                    / f"{unparse_year_month(salary_date)}_{salary_type.value}_{index}.pdf"
                )
                index += 1

            write_page(salary_page, salary_output_path)

            log.info(
                f"Detected NAF {str(naf)} in PDF salary {salary_file_path}, page "
                f"{salary_page_number + 1}. Saving page in {salary_output_path} and "
                f"further processing it."
            )

            if salary_type == SalaryType.DELAY:
                delay_salaries_rlcs_found[salary_date][0] = True
                process_rlc_l03(
                    salary_file_path,
                    salary_page_number,
                    salary_page,
                    salary_date,
                    naf_dir,
                    rlc_folder_path,
                    delay_salaries_rlcs_found,
                )
            elif salary_type == SalaryType.REGULAR:
                log.info(
                    f"Salary file {salary_file_path} page {salary_page_number + 1} has been selected "
                    f"as regular salary for date {unparse_date(salary_date)}"
                )
                try:
                    regular_salary_type = parse_regular_salary_type(salary_page)
                except UndefinedRegularSalaryTypeError as e:
                    log.error(
                        f"Salary file {salary_file_path} page {salary_page_number + 1} is a type "
                        f"not supported or can not be recognized. Skipping to next page. Internal error "
                        f"is: {str(e)}"
                    )
                    continue
                if regular_salary_type == RegularSalaryType.MONTHLY:
                    log.info(
                        f"Salary file {salary_file_path} page {salary_page_number + 1} has been "
                        f"selected as regular monthly salary for date {unparse_date(salary_date)}"
                    )
                    process_generic_rlc(
                        RLCType.REGULAR,
                        salary_date,
                        salary_file_path,
                        rlc_folder_path,
                        naf_dir,
                        regular_monthly_salaries_rlcs_found,
                    )
                elif regular_salary_type == RegularSalaryType.SETTLEMENT:
                    log.info(
                        f"Salary file {salary_file_path} page {salary_page_number + 1} has been "
                        f"selected as regular settlement salary for date {unparse_date(salary_date)}"
                    )
                    process_generic_rlc(
                        RLCType.SETTLEMENT,
                        salary_date,
                        salary_file_path,
                        rlc_folder_path,
                        naf_dir,
                        regular_settlement_salaries_rlcs_found,
                    )
                else:
                    log.error(
                        "The regular salary type is not recognized. This RLC will be skipped."
                    )
                    continue

            elif salary_type == SalaryType.EXTRA:
                log.info(
                    f"Salary file {salary_file_path} page {salary_page_number + 1} has been selected "
                    f"as extra salary for date {unparse_date(salary_date)}"
                )
                continue
            elif salary_type == SalaryType.LIQ:
                continue
            else:
                log.error(
                    f"Detected type {str(salary_type)} that is not a recognized type. The current salary "
                    f"file will be ignored"
                )

    r = {
        RLCTypeFileName.REGULAR: regular_monthly_salaries_rlcs_found,
        RLCTypeFileName.SETTLEMENT: regular_settlement_salaries_rlcs_found,
        RLCTypeFileName.DELAY: delay_salaries_rlcs_found,
    }

    return r, scanned_liquidation_salary_found


def compute_path(partial_path: Path, suffix: str, extension: str) -> Path:
    """Return a unique output path by appending *suffix* and a numeric disambiguator.

    Args:
        partial_path: Base path without suffix or extension.
        suffix: Label appended before the extension (e.g. ``"Nomines"``).
        extension: File extension including the dot (e.g. ``".pdf"``).

    Returns:
        A path that does not yet exist on disk.
    """
    num_suffix = 1
    output_path = partial_path.parent / (partial_path.name + "_" + suffix + extension)
    while output_path.exists():
        output_path = (
            partial_path.parent
            / f"{partial_path.name}_{suffix}_{num_suffix}{extension}"
        )
        num_suffix += 1
    return output_path


def process_proof(
    proof_folder: Path,
    proofs_output_path: Path,
    nifs: list[NIF],
    proof_date: datetime,
    bank: BankType,
    proof_type: SalaryType,
) -> None:
    """Processes a specific proof directory, that contain proof documents."""
    files = list_dir(proof_folder)
    files.sort()
    for bankproof_file in files:
        for nif in nifs:
            try:
                pattern = "[A-Z]\\d{7}[A-Z]|\\d{8}[A-Z]|[A-Z][A-Z]\\d{7}"
                page = get_matching_page(
                    proof_folder / bankproof_file,
                    nif.no_dash_str(),
                    pattern,
                )
            except ValueError as e:
                log.trace(
                    f"DNI {nif.no_dash_str()} not detected in "
                    f"{proof_folder / bankproof_file}. Error: {e}"
                )
                continue

            output_partial_path = proofs_output_path / unparse_year_month(proof_date)
            output_path = compute_path(output_partial_path, proof_type.value, ".pdf")
            log.info(
                f"DNI {nif.no_dash_str()} was detected in "
                f"{proof_folder / bankproof_file}. "
                f"Writing page to {output_path}."
            )
            write_page(page, output_path)
            break  # If we have matched the current document, we do not need to keep lookign with another nif


def process_proofs(
    proofs_folder_path: Path,
    proofs_output_path: Path,
    naf: NAF,
    begin: datetime,
    end: datetime,
    naf_to_dni: dict[NAF, list[NIF]],
    look_for_liquidation_payments: bool,
) -> None:
    """Extract bank-proof pages matching *naf*'s DNI from the proofs folder.

    Args:
        proofs_folder_path: Root folder containing bank-proof PDFs.
        proofs_output_path: Directory where extracted proof pages are written.
        naf: NAF identifier of the employee.
        begin: Start of the justification period.
        end: End of the justification period.
        naf_to_dni: Mapping from NAF to NIF for DNI lookup.
        look_for_liquidation_payments: Look for liquidation payments from a previous month from begin to the next month
        of end.
    """
    if look_for_liquidation_payments:
        log.trace("Looking for liquidation payments")
    all_bankproof_folders = flatten_dirs(proofs_folder_path)
    # all_bankproof_folders.sort()  # Optional, improves readibility

    for bankproof_folder in all_bankproof_folders:
        process_current = False
        try:
            dir_date, bank, proof_type = parse_proof_folder_name(bankproof_folder.name)
        except InvalidFilenameError as e:
            log.error(
                f"Proof folder {bankproof_folder} has an invalid name, skipping: {e}"
            )
            continue

        if proof_type is SalaryType.SETTLEMENT:
            # Only select a payment that is settlement if the flag is active
            if look_for_liquidation_payments:
                # When selecting, select the range plus two months offset, one from the beginning one from the end
                if (
                    begin - relativedelta(months=1)
                    <= dir_date
                    <= end + relativedelta(months=1)
                ):
                    process_current = True

        else:
            # If it is not a settlement, the flag does not affect to selection.
            if begin <= dir_date <= end:
                process_current = True

        if process_current:
            log.debug(
                f"Proof folder {bankproof_folder} is selected, because its date is {unparse_date(dir_date, '-')}."
            )

            process_proof(
                proofs_folder_path / bankproof_folder,
                proofs_output_path,
                naf_to_dni[naf],
                dir_date,
                bank,
                proof_type,
            )


def process_contracts(
    contracts_folder_path: Path, naf_dir: Path, naf: NAF, begin: datetime, end: datetime
) -> bool:
    """Copy contract files for *naf* that overlap the requested period.

    Args:
        contracts_folder_path: Folder containing contract PDFs.
        naf_dir: Output directory for the employee.
        naf: NAF identifier of the employee.
        begin: Start of the justification period.
        end: End of the justification period.

    Returns:
        True if at least one matching contract was found and copied.
    """
    found = False
    contracts_files = list_dir(contracts_folder_path)
    contracts_files.sort()
    for contracts_file in contracts_files:
        log.debug(f"contract file: {contracts_file}")
        try:
            begin_date, end_date = parse_contract_dates(contracts_file)
        except InvalidFilenameError as e:
            log.error(
                f"Contract file {contracts_file} has an invalid name, skipping: {e}"
            )
            continue
        naf_dirty = NAF(contracts_file.split("_")[0])

        if naf_dirty == naf:
            log.debug(
                f"NAF {naf_dirty} of file {contracts_file} coincides with queried NAF. Checking dates..."
            )
            if begin <= end_date and begin_date <= end:
                log.info(
                    f"{contracts_file} that starts at {unparse_date(begin_date, '-')} and ends at "
                    f"{unparse_date(end_date, '-')} is in range of "
                    f"{unparse_date(begin, '-')}, {unparse_date(end, '-')}. Copying it to {naf_dir}"
                )
                try:
                    shutil.copy(
                        src=contracts_folder_path / contracts_file,
                        dst=naf_dir / SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME,
                    )
                    found = True
                except Exception as e:
                    err_msg = (
                        f"An error happened while copying "
                        f"{contracts_folder_path / contracts_file} to "
                        f"{naf_dir / SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME}. The program will abort. "
                        f"Error is: {str(e)}"
                    )
                    log.critical(err_msg)
                    raise Exception(err_msg)

    if not found:
        log.warning(f"Contract not found with NAF {naf}")
    return found


def process_rnts(
    rnts_folder_path: Path, naf_dir: Path, naf: NAF, begin: datetime, end: datetime
) -> dict[datetime, bool]:
    """Extract RNT pages for *naf* and track which months have a matching RNT.

    Args:
        rnts_folder_path: Root folder containing RNT PDFs.
        naf_dir: Output directory for the employee.
        naf: NAF identifier of the employee.
        begin: Start of the justification period.
        end: End of the justification period.

    Returns:
        Per-month dict indicating whether an RNT was found for each month.
    """
    rnts_found = get_rnt_monthly_result_structure(begin, end)

    rnt_files = flatten_dirs(rnts_folder_path)
    rnt_files.sort()
    for rnt_file in rnt_files:
        try:
            file_date = parse_rnt_date(rnt_file.name)
        except InvalidFilenameError as e:
            log.error(f"RNT file {rnt_file} has an invalid name, skipping: {e}")
            continue
        if begin <= file_date <= end:
            rnt_file_name = rnt_file.name
            rnt_file_name_without_extension = Path(rnt_file_name).stem
            rnt_path = rnts_folder_path / str(file_date.year) / rnt_file_name
            log.info(
                f"RNT file {rnt_path} is selected, because its date is {unparse_date(file_date)}."
            )
            try:
                pages = get_matching_pages(rnt_path, str(naf), r"\d{12}")
            except ValueError as e:
                log.debug(f"NAF {naf} not detected in {rnt_path}. Error: {e}")
                continue
            for page, page_num in pages:
                rnt_path_destination = (
                    naf_dir
                    / SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME
                    / f"{rnt_file_name_without_extension}_{page_num}.pdf"
                )
                log.info(
                    f"NAF {naf} was detected in {rnt_path} in page {page_num + 1}. "
                    f"Writing page to {rnt_path_destination}."
                )
                write_page(page, rnt_path_destination)
                log.debug(f"rnt found with date: {file_date}")
                rnts_found[file_date] = True
        else:
            log.debug(
                f"RNT file {rnt_file} is not selected, because its date is {unparse_date(file_date)}."
            )

    return rnts_found


def merge_rnts_rlcs(
    rnts_folder: Path,
    rlcs_folder: Path,
    rnts_folder_output: Path,
    rlcs_folder_output: Path,
    merged_rnts_rlcs_folder_output: Path,
    begin: datetime,
    end: datetime,
) -> None:
    """Merge per-month RNT and RLC output files into combined PDFs.

    Args:
        rnts_folder: Source folder listing available RNT filenames.
        rlcs_folder: Source folder listing available RLC filenames.
        rnts_folder_output: Folder containing the extracted RNT pages to merge.
        rlcs_folder_output: Folder containing the extracted RLC pages to merge.
        merged_rnts_rlcs_folder_output: Destination folder for the merged PDFs.
        begin: Start of the justification period.
        end: End of the justification period.
    """
    months_list = datetime_range(begin, end)
    log.info(f"Generated months list from {begin} to {end} is: {months_list}")
    rnts_filenames = list_dir(rnts_folder)
    rlcs_filenames = list_dir(rlcs_folder)
    log.trace(f"RNT available files are: {rnts_filenames}")
    log.trace(f"RLC available files are: {rlcs_filenames}")

    for current_date in months_list:
        full_year_date = unparse_year_month(current_date)
        partial_year_date = unparse_year_month_short(current_date)
        log.trace(f"Full year date is: {full_year_date}")
        log.trace(f"Partial year date is: {partial_year_date}")

        paths_to_merge = []
        for rnt_filename in rnts_filenames:
            date_str = rnt_filename.split("_")[0]
            log.trace(f"date str is: {date_str}")
            if date_str == partial_year_date:
                paths_to_merge.append(rnts_folder_output / rnt_filename)
        for rlc_filename in rlcs_filenames:
            date_str = rlc_filename.split("_")[0]
            log.trace(f"date str is: {date_str}")
            if date_str == full_year_date:
                paths_to_merge.append(rlcs_folder_output / rlc_filename)

        output_path = merged_rnts_rlcs_folder_output / (
            unparse_year_month(current_date) + "_Merged.pdf"
        )
        log.debug(f"PDFs to merge: {paths_to_merge}")
        log.debug(f"Output path: {output_path}")

        if len(paths_to_merge) >= 2:
            merge_pdfs(paths_to_merge, output_path, True)
        else:
            log.warning(
                f"During date {unparse_year_month(current_date)} there were less than "
                f"one RNTs or RLCs to merge (at least one is missing). Skipping"
            )
        log.trace(f"Merged PDFs: {paths_to_merge} -> {output_path}")
