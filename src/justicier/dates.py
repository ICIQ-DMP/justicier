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

"""Date formatting and document-filename parsing helpers."""

from datetime import datetime
from pathlib import Path

from . import logger
from .custom_except import InvalidFilenameError
from .defines import (
    DATETIME_FORMAT_YEAR_MONTH,
    DATETIME_FORMAT_MONTH_YEAR,
    SalaryFileSuffix,
)

log = logger.get_logger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def unparse_month(d: datetime) -> str:
    """Return the zero-padded two-digit month string."""
    return d.strftime("%m")


def unparse_year_month(d: datetime) -> str:
    """Return a six-character YYYYMM string."""
    return d.strftime("%Y%m")


def unparse_year_month_short(d: datetime) -> str:
    """Return a four-character YYMM string."""
    return d.strftime("%y%m")


def unparse_date(d: datetime, separator: str = "-") -> str:
    """Return a MM<sep>YYYY string."""
    return d.strftime("%m") + separator + d.strftime("%Y")


def unparse_full_date(d: datetime, separator: str = "-") -> str:
    """Return a DD<sep>MM<sep>YYYY string."""
    return (
        d.strftime("%d") + separator + d.strftime("%m") + separator + d.strftime("%Y")
    )


# ---------------------------------------------------------------------------
# Month range
# ---------------------------------------------------------------------------


def datetime_range(begin: datetime, end: datetime) -> list[datetime]:
    """Return a list of first-of-month datetimes covering the [begin, end] period."""
    current = datetime(begin.year, begin.month, 1)
    result = []
    while current <= end:
        result.append(current)
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)
    return result


# ---------------------------------------------------------------------------
# Filename parsing — all raise InvalidFilenameError on malformed input
# ---------------------------------------------------------------------------


def parse_salary_date(path: Path) -> datetime:
    """Parse the YYYYMM date from a salary filename.

    Expected format: ``YYMM_Type_*.pdf``

    Args:
        path: Path to the salary PDF file.

    Returns:
        datetime representing the salary's year and month.

    Raises:
        InvalidFilenameError: if the YYMM prefix cannot be parsed.
    """
    try:
        prefix = Path(path).stem.split("_")[0]
        return datetime.strptime("20" + prefix, DATETIME_FORMAT_YEAR_MONTH)
    except (ValueError, IndexError) as e:
        raise InvalidFilenameError(
            f"Cannot parse date from salary filename '{Path(path).name}': expected YYMM prefix"
        ) from e


def parse_salary_type(path: Path) -> SalaryFileSuffix:
    """Extract the SalaryType from a salary filename.

    Expected format: ``YYMM_Type_*.pdf``

    Args:
        path: Path to the salary PDF file.

    Returns:
        The SalaryType encoded in the filename.

    Raises:
        InvalidFilenameError: if the type field is missing or not a known SalaryType.
    """
    name = Path(path).name
    stem = Path(path).stem
    try:
        type_str = stem.split("_")[1]
    except IndexError as e:
        raise InvalidFilenameError(
            f"Cannot parse type from salary filename '{name}': expected YYMM_Type format"
        ) from e
    try:
        return SalaryFileSuffix(type_str)
    except ValueError as e:
        raise InvalidFilenameError(
            f"Unknown salary type '{type_str}' in '{name}'"
        ) from e


def parse_proof_folder_date(folder_name: str) -> datetime:
    """Parse MMYYYY from the start of a bank-proof folder name.

    Expected format: ``MMYYYY_Bank``

    Args:
        folder_name: Name of the proof subfolder (not its full path).

    Returns:
        datetime representing the folder's month and year.

    Raises:
        InvalidFilenameError: if the first six characters cannot be parsed as MMYYYY.
    """
    try:
        return datetime.strptime(folder_name[:6], DATETIME_FORMAT_MONTH_YEAR)
    except ValueError as e:
        raise InvalidFilenameError(
            f"Cannot parse date from proof folder '{folder_name}': expected MMYYYY prefix"
        ) from e


def parse_rnt_date(filename: str) -> datetime:
    """Parse the YYYYMM date from an RNT filename.

    Expected format: ``YYMM_*.pdf``

    Args:
        filename: RNT filename (not its full path).

    Returns:
        datetime representing the RNT's year and month.

    Raises:
        InvalidFilenameError: if the YYMM prefix cannot be parsed.
    """
    try:
        return datetime.strptime("20" + filename[:4], DATETIME_FORMAT_YEAR_MONTH)
    except ValueError as e:
        raise InvalidFilenameError(
            f"Cannot parse date from RNT filename '{filename}': expected YYMM prefix"
        ) from e


def parse_contract_dates(filename: str) -> tuple[datetime, datetime]:
    """Parse begin and end dates from a contract filename.

    Expected format: ``NAF_YYMM[_YYMM|_A].pdf``
    The end date is ``datetime.max`` for open-ended contracts (suffix ``_A`` or absent).

    Args:
        filename: Contract filename (not its full path).

    Returns:
        Tuple of ``(begin_date, end_date)``.

    Raises:
        InvalidFilenameError: if the filename does not match the expected format.
    """
    try:
        parts = Path(filename).stem.split("_")
        if not 2 <= len(parts) <= 3:
            raise ValueError(
                f"expected 2 or 3 underscore-separated fields, got {len(parts)}"
            )
        begin = datetime.strptime("20" + parts[1], DATETIME_FORMAT_YEAR_MONTH)
        if len(parts) == 3 and parts[2] != "A":
            end = datetime.strptime("20" + parts[2], DATETIME_FORMAT_YEAR_MONTH)
        else:
            end = datetime.max
        return begin, end
    except (ValueError, IndexError) as e:
        raise InvalidFilenameError(
            f"Cannot parse dates from contract filename '{filename}': {e}"
        ) from e
