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

"""Result-structure factories."""

import copy
import re
from datetime import datetime
from typing import Dict, List, Any, TypeVar, Type, Union

from . import logger
from .custom_except import InvalidFilenameError, UndefinedSalaryTypeError
from .defines import (
    BankType,
    LaCaixaFolderSuffixes,
    BBVAFolderSuffixes,
    DATETIME_FORMAT_MONTH_YEAR,
    ProofType,
    ProofFileSuffix,
    SalaryType,
)
from .naf import NAF
from .name import Name
from .nif import NIF

log = logger.get_logger(__name__)


def get_rlc_monthly_result_structure(
    begin: datetime, end: datetime
) -> Dict[datetime, List[bool]]:
    """Return a per-month tracking structure for RLC documents (salary, N, P flags).

    Args:
        begin: Start of the period.
        end: End of the period.

    Returns:
        Dict mapping each month to a three-element bool list ``[salary, rlc_n, rlc_p]``.
    """
    return get_monthly_result_structure(begin, end, [False, False, False])


def get_rnt_monthly_result_structure(
    begin: datetime, end: datetime
) -> Dict[datetime, bool]:
    """Return a per-month tracking structure for RNT documents.

    Args:
        begin: Start of the period.
        end: End of the period.

    Returns:
        Dict mapping each month to a bool indicating whether the RNT was found.
    """
    return get_monthly_result_structure(begin, end, False)


def parse_salary_type_from_file_suffix(
    salary_file_suffix: ProofFileSuffix,
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
    if salary_file_suffix == ProofFileSuffix.DELAY:
        return SalaryType.DELAY
    elif salary_file_suffix == ProofFileSuffix.LIQUIDATION:
        return SalaryType.LIQUIDATION
    elif salary_file_suffix == ProofFileSuffix.EXTRA:
        return SalaryType.EXTRA
    elif salary_file_suffix == ProofFileSuffix.REGULAR:
        raise UndefinedSalaryTypeError(
            "the SalaryType cannot be deduced only from SalaryFileSuffix.REGULAR"
        )
    else:
        raise UndefinedSalaryTypeError("The type was not recognized")


def get_monthly_result_structure(
    begin: datetime, end: datetime, result_structure: Any
) -> Dict[datetime, Any]:
    """Build an ordered dict covering every month in the ``[begin, end]`` range.

    Args:
        begin: Start of the period.
        end: End of the period.
        result_structure: Default value assigned to each month key.

    Returns:
        Dict mapping ``datetime`` month keys to copies of *result_structure*.
    """
    log.trace(f"get_rlc_monthly_result_structure params: begin: {begin} end: {end}")
    current = datetime(begin.year, begin.month, 1)

    result = {}
    while current <= end:
        log.trace(f"Current datetime is: {current}")
        result[current] = copy.deepcopy(
            result_structure  # Monthly salary found, RLC L00N found, RLC L00P found
        )
        # Move to next month
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)

    log.trace(f"result structure:{result}")
    return result


_K = TypeVar("_K")
_V = TypeVar("_V")


def reverse_dict(d: dict[_K, _V]) -> dict[_V, _K]:
    """Return a new dict with keys and values swapped.

    Args:
        d: Source dictionary to invert.

    Returns:
        Inverted dictionary mapping original values to original keys.
    """
    r = {}
    for key, value in d.items():
        r[value] = key
    return r


def complete_ids_with_naf(
    naf: NAF,
    naf_to_dni: dict[NAF, list[NIF]],
    naf_to_name: dict[NAF, Name],
    naf_to_email: dict[NAF, str],
) -> tuple[list[NIF], Name, str]:
    """Resolve NIF, Name, and email for the given NAF using the lookup tables.

    Args:
        naf: NAF identifier of the employee.
        naf_to_dni: Mapping from NAF to NIF.
        naf_to_name: Mapping from NAF to Name.
        naf_to_email: Mapping from NAF to email address.

    Returns:
        Tuple of ``(nif, name, email)`` for the employee.
    """
    dni = naf_to_dni[naf]
    name = naf_to_name[naf]
    email = naf_to_email[naf]
    return dni, name, email


def parse_bank_type_from_folder_name(bank_folder_name: str) -> BankType:
    """Parse a Bank type from a bank folder name."""
    try:
        name_as_list_without_initial_date = bank_folder_name.split("_")[1:]
    except KeyError as e:
        raise InvalidFilenameError(
            f"The bankproof {bank_folder_name} has an invalid name as it can't be split by _"
            f""
        ) from e
    suffixes = [s.value for s in BBVAFolderSuffixes] + [
        s.value for s in LaCaixaFolderSuffixes
    ]
    for suffix in suffixes:
        if suffix in name_as_list_without_initial_date:
            name_as_list_without_initial_date.remove(suffix)

    bank_type_str = "_".join(name_as_list_without_initial_date)
    try:
        return BankType(bank_type_str)
    except ValueError as e:
        raise InvalidFilenameError(
            f"The bankproof {bank_folder_name} has been processed into {bank_type_str} but that "
            f"can't be mapped to any BankType"
        ) from e


_SuffixEnum = TypeVar("_SuffixEnum", BBVAFolderSuffixes, LaCaixaFolderSuffixes)


def _parse_proof_type(
    folder_name: str, bank_type: BankType, suffix_cls: Type[_SuffixEnum]
) -> _SuffixEnum:
    name_without_date = "_".join(folder_name.split("_")[1:])
    suffix_str = name_without_date.replace(bank_type.value, "")
    try:
        return suffix_cls(suffix_str)
    except ValueError as e:
        raise InvalidFilenameError(
            f"Bankproof folder '{folder_name}' maps to '{suffix_str}' which is not a valid {suffix_cls.__name__}"
        ) from e


def parse_proof_folder_name(
    folder_name: str,
) -> tuple[datetime, BankType, ProofType]:
    """Parse date, bank type, and salary type from a bank-proof folder name.

    The regex is built dynamically from the BankType, BBVAFolderSuffixes, and
    LaCaixaFolderSuffixes enum values, so adding a new member to any of those
    enums is automatically reflected here.

    Expected format: ``MMYYYY_<BankType>[_<suffix>]``
    """
    bank_type_to_suffix_cls: dict[
        BankType, Union[Type[BBVAFolderSuffixes], Type[LaCaixaFolderSuffixes]]
    ] = {
        BankType.BBVA: BBVAFolderSuffixes,
        BankType.LA_CAIXA: LaCaixaFolderSuffixes,
    }

    bank_type_alts = "|".join(
        re.escape(b.value)
        for b in sorted(BankType, key=lambda b: len(b.value), reverse=True)
    )
    all_suffixes = list(
        dict.fromkeys(
            s.value
            for the_class in bank_type_to_suffix_cls.values()
            for s in the_class
            if s.value
        )
    )
    suffix_alts = "|".join(
        re.escape(s) for s in sorted(all_suffixes, key=len, reverse=True)
    )

    pattern = re.compile(rf"^(\d{{6}})_({bank_type_alts})(?:_({suffix_alts}))?$")

    m = pattern.match(folder_name)
    if not m:
        raise InvalidFilenameError(
            f"Bank-proof folder name '{folder_name}' does not match the expected format"
        )

    date_str, bank_type_str, suffix_str = m.group(1), m.group(2), m.group(3)

    date = datetime.strptime(date_str, DATETIME_FORMAT_MONTH_YEAR)
    bank_type = BankType(bank_type_str)
    suffix_cls = bank_type_to_suffix_cls[bank_type]
    suffix = suffix_cls(suffix_str if suffix_str is not None else "")

    return date, bank_type, map_folder_suffix_to_proof_type(suffix)


def parse_proof_type_from_la_caixa_folder_name(
    folder_name: str,
) -> LaCaixaFolderSuffixes:
    """Parse a bank proof type from a La Caixa folder name."""
    return _parse_proof_type(folder_name, BankType.LA_CAIXA, LaCaixaFolderSuffixes)


def parse_proof_type_from_bbva_folder_name(folder_name: str) -> BBVAFolderSuffixes:
    """Parse a bank proof type from a BBVA folder name."""
    return _parse_proof_type(folder_name, BankType.BBVA, BBVAFolderSuffixes)


def map_folder_suffix_to_proof_type(
    suffix: BBVAFolderSuffixes | LaCaixaFolderSuffixes,
) -> ProofType:
    """Maps a bank folder suffix into the types of salaries that are in the folder."""
    if suffix == BBVAFolderSuffixes.DELAY or suffix == LaCaixaFolderSuffixes.DELAY:
        return ProofType.DELAY
    elif suffix == BBVAFolderSuffixes.EXTRA or suffix == LaCaixaFolderSuffixes.EXTRA:
        return ProofType.EXTRA
    elif suffix == BBVAFolderSuffixes.SETTLEMENT:
        return ProofType.ADVANCED_SETTLEMENT
    elif (
        suffix == BBVAFolderSuffixes.REGULAR or suffix == LaCaixaFolderSuffixes.REGULAR
    ):
        raise ValueError(f"Type cannot be determined from folder suffix {suffix}")
    else:
        raise ValueError(
            f"{suffix} is not a valid BBVAFolderSuffixes or LaCaixaFolderSuffixes"
        )


def complete_ids(
    naf: NAF,
    nif: NIF,
    email: str,
    name: Name,
    name_to_naf: dict[Name, NAF],
    naf_to_nif: dict[NAF, list[NIF]],
    nif_to_naf: dict[NIF, NAF],
    naf_to_name: dict[NAF, Name],
    email_to_naf: dict[str, NAF],
    naf_to_email: dict[NAF, str],
) -> tuple[NAF, list[NIF], Name, str]:
    """Resolve all employee identifiers from whichever primary key is provided.

    Precedence: NAF > email > NIF > name. Warns when a redundant identifier is
    supplied alongside the primary key.

    Args:
        naf: NAF identifier (highest priority).
        nif: NIF/DNI identifier.
        email: Email address.
        name: Employee name.
        name_to_naf: Lookup table from Name to NAF.
        naf_to_nif: Lookup table from NAF to NIF.
        nif_to_naf: Lookup table from NIF to NAF.
        naf_to_name: Lookup table from NAF to Name.
        email_to_naf: Lookup table from email to NAF.
        naf_to_email: Lookup table from NAF to email.

    Returns:
        Tuple of ``(naf, nif, name, email)`` with all fields resolved.

    Raises:
        ValueError: If none of the identifier arguments are provided.
    """
    if naf:
        if nif:
            log.warning(
                "DNI is defined but NAF is also defined. Provided NIF will be ignored."
            )
        if name:
            log.warning(
                "Name is defined but NAF is also defined. Provided name will be ignored."
            )
        if email:
            log.warning(
                "Email is defined but NAF is also defined. Provided email will be ignored."
            )

    elif email:
        if nif:
            log.warning(
                "DNI is defined but email is also defined. Provided NIF will be ignored."
            )
        if name:
            log.warning(
                "Name is defined but email is also defined. Provided name will be ignored."
            )
        naf = email_to_naf[email]

    elif nif:
        if name:
            log.warning(
                "Name is defined but NIF is also defined. Provided name will be ignored."
            )
        log.warning(
            "Remember that "
            "identifying employees using NIF is fragile and should be avoided. Using NAF or email for "
            "employee "
            "identification is the recommended configuration."
        )
        naf = nif_to_naf[nif]

    elif name:
        log.warning(
            "Remember that "
            "identifying employees using name is fragile and should be avoided. Using NAF or email for "
            "employee "
            "identification is the recommended configuration."
        )
        naf = name_to_naf[name]

    else:
        raise ValueError(
            "An employee identifier was not supplied (NAF, DNI or name). Aborting."
        )
    nifs, name, email = complete_ids_with_naf(
        naf, naf_to_nif, naf_to_name, naf_to_email
    )
    return naf, nifs, name, email
