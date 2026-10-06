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

"""Project-wide constants, enumerations, and path helpers."""

import datetime
from enum import Enum
from pathlib import Path

SHAREPOINT_ROOT_FOLDER_NAME = Path("Documentació Nomines, Seguretat Social")
SHAREPOINT_ROOT_INPUT_FOLDER_NAME = Path("input")
SHAREPOINT_ROOT_OUTPUT_FOLDER_NAME = Path("_output")

SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME = Path("Nòmines")
SHAREPOINT_PROOFS_OUTPUT_FOLDER_NAME = Path("Justificants")
SHAREPOINT_SALARIES_AND_PROOFS_OUTPUT_FOLDER_NAME = Path("Nòmines i Justificants")
SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME = Path("Contractes")
SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME = Path("RNTs")
SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME = Path("RLCs")
SHAREPOINT_RNTS_AND_RLCS_OUTPUT_FOLDER_NAME = Path("RNTs i RLCs")
SHAREPOINT_ADMIN_LOGS_OUTPUT_FOLDER_NAME = Path("_admin_logs")
SHAREPOINT_SUPERVISOR_LOGS_OUTPUT_FOLDER_NAME = Path("_supervisor_logs")

SHAREPOINT_LIST_NAME = "Peticions_Justificacions"

DATETIME_FORMAT = "%Y-%m-%d_%H-%M-%S"
DATETIME_FORMAT_COMMAS = "%Y-%m-%d_%H,%M,%S"
DATE_FORMAT = "%d/%m/%Y"
DATETIME_SHAREPOINT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_DEFAULT_FORMAT = "%Y-%m-%d"
DEFAULT_TIMEZONE = "Europe/Madrid"
DATETIME_FORMAT_YEAR_MONTH = "%Y%m"
DATETIME_FORMAT_MONTH_YEAR = "%m%Y"

SHAREPOINT_DRIVE_NAME = "Documents"

ROOT_FOLDER_PATH: Path = Path(__file__).resolve().parent.parent.parent

LOCAL_GENERAL_OUTPUT_FOLDER_PATH: Path = (
    ROOT_FOLDER_PATH / SHAREPOINT_ROOT_OUTPUT_FOLDER_NAME
)

LOCAL_ADMIN_LOG_FOLDER_PATH: Path = (
    LOCAL_GENERAL_OUTPUT_FOLDER_PATH / SHAREPOINT_ADMIN_LOGS_OUTPUT_FOLDER_NAME
)
LOCAL_SUPERVISOR_LOG_FOLDER_PATH: Path = (
    LOCAL_GENERAL_OUTPUT_FOLDER_PATH / SHAREPOINT_SUPERVISOR_LOGS_OUTPUT_FOLDER_NAME
)

SHAREPOINT_INPUT_FOLDER_PATH: Path = (
    SHAREPOINT_ROOT_FOLDER_NAME / SHAREPOINT_ROOT_INPUT_FOLDER_NAME
)
SHAREPOINT_OUTPUT_FOLDER_PATH: Path = (
    SHAREPOINT_ROOT_FOLDER_NAME / SHAREPOINT_ROOT_OUTPUT_FOLDER_NAME
)

SHAREPOINT_ADMIN_LOGS_FOLDER_PATH = (
    SHAREPOINT_INPUT_FOLDER_PATH / SHAREPOINT_ADMIN_LOGS_OUTPUT_FOLDER_NAME
)

LOCAL_GENERAL_INPUT_FOLDER = (
    ROOT_FOLDER_PATH
    / "service"
    / "onedrive"
    / "data"
    / SHAREPOINT_ROOT_FOLDER_NAME
    / SHAREPOINT_ROOT_INPUT_FOLDER_NAME
)

NOW_DATA = datetime.datetime.now()
NOW = NOW_DATA.strftime(DATETIME_FORMAT)
NOW_COMMAS = NOW_DATA.strftime(DATETIME_FORMAT_COMMAS)


class SecretNames(str, Enum):
    """Available secret names."""

    SHAREPOINT_DOMAIN = "SHAREPOINT_DOMAIN"
    SITE_NAME = "SITE_NAME"
    SMTP_OWNER_EMAIL = "SMTP_OWNER_EMAIL"
    SMTP_USERNAME = "SMTP_USERNAME"
    SMTP_PASSWORD = "SMTP_PASSWORD"
    SMTP_SERVER = "SMTP_SERVER"
    SMTP_PORT = "SMTP_PORT"


class InputLocation(str, Enum):
    """Input location argument possible values."""

    SHAREPOINT = "sharepoint"
    LOCAL = "local"


class InputElementsNames(str, Enum):
    """Input folder names."""

    SALARIES = "_salaries"
    BANKPROOFS = "_proofs"
    CONTRACTS = "_contracts"
    RNTS = "_RNT"
    RLCS = "_RLC"
    NAF_DNI = "NAF_DNI.xlsx"


class NAFFileColumn(str, Enum):
    """Column header names in the NAF/DNI Excel file."""

    NAME = "Nombre Completo"
    NASS = "NASS"
    NIF_CURRENT = "NIF ACTUAL"
    NIF_PREVIOUS = "NIF ANTERIOR"
    NIF_BEFORE_PREVIOUS = "NIF PREVIO AL ANTERIOR"
    EMAIL = "E-mail profesional"


class SharepointListFieldWorkflowState(Enum):
    """Maps semantic Python names to the SharePoint field values SharepointListFields.WORKFLOW_STATE.

    Only values used in the algorithm are included, even though there are more.
    """

    IN_EXECUTION = "En execució"
    COMPLETED = "Completat"
    ERROR = "Error"


class SharepointListFields(Enum):
    """Maps semantic Python names to the internal SharePoint field names used by the Graph API."""

    ID = "id"
    REQUEST_TITLE = "Title"
    NAF = "NAF"
    TARGET_NAME = "Nomdelapersona"
    TARGET_EMAIL = "PersonaEmail"
    NIF = "DNI"
    BEGIN = "DataInici"
    END = "Datafinal"
    AUTHOR_NAME = "Sol_x00b7_licitant"
    AUTHOR_EMAIL = "SolicitantEmail"
    MERGE_SALARY_BANKPROOF = "Fusi_x00f3_NominaiJustificantBan"
    MERGE_RESULTS = "juntarpdfs"
    MERGE_RLC_RNT = "Fusi_x00f3_RLCRNT"
    WORKFLOW_STATE = "Estatworkflow"
    RESULT = "Resultat"
    ERROR_MESSAGE = "Missatge_x0020_error"


class DocType(Enum):
    """Document categories produced by the justification process."""

    SALARY = "salary"
    CONTRACT = "contract"
    RLC = "RLC"
    RNT = "RNT"
    PROOFS = "proofs"
    SALARIES_AND_PROOFS = "salaries with proofs"


def from_string(value: str) -> "DocType":
    """Return the DocType matching *value*, accepting common aliases.

    Args:
        value: Human-readable document type string (e.g. ``"salary"``, ``"RLC"``).

    Returns:
        The matching DocType member.

    Raises:
        ValueError: If *value* does not match any known type or alias.
    """
    _aliases = {
        DocType.SALARY: {"salary", "salaries", "SALARY", "Salary", "payslip"},
        DocType.CONTRACT: {"contract", "CONTRACT", "Contract", "agreement"},
        DocType.RLC: {"RLC", "rlc", "R.L.C."},
        DocType.RNT: {"RNT", "rnt", "R.N.T."},
        DocType.PROOFS: {"proof", "bankproof", "proofs", "bankproofs"},
    }
    for doctype in _aliases:
        if value.strip() in _aliases[doctype]:
            return doctype
    raise ValueError(f"Unknown document type: {value}")


class RLCTypeFileName(Enum):
    """Sub-types of RLC (payroll tax settlement) documents for folder names."""

    REGULAR = "regular"
    DELAY = "delay"
    SETTLEMENT = "settlement"


class BankType(Enum):
    """Types of Bank doing the bank proofs."""

    BBVA = "BBVA"
    LA_CAIXA = "LA_CAIXA"


class RLCType(Enum):
    """Sub-types of RLC (payroll tax settlement) document."""

    REGULAR = "L00"
    DELAY = "L03"
    SETTLEMENT = "L13"


class RLCSubType(Enum):
    """Sub-types of RLC (payroll tax settlement) documents."""

    NOMINAL = "N"
    PAYMENT = "P"


class SalaryType(Enum):
    """Salary file and bank proof types as encoded in their filenames."""

    REGULAR = "Nomines"
    DELAY = "Atrasos"
    EXTRA = "Extres"
    LIQ = "LIQ"
    SETTLEMENT = "BESTRETA_QUITANÇA"


class LaCaixaFolderSuffixes(Enum):
    """La Caixa bank proofs folder suffixes."""

    REGULAR = ""
    DELAY = "endarreriments"
    EXTRA = "EXTRA"


class BBVAFolderSuffixes(Enum):
    """BBVA bank proofs folder suffixes."""

    REGULAR = ""
    DELAY = "endarreriments"
    EXTRA = "FINIQUITO"
    SETTLEMENT = "BESTRETA_QUITANÇA"


class RegularSalaryType(Enum):
    """Sub-types of regular salary slips."""

    SETTLEMENT = "Settlement"
    MONTHLY = "Monthly"
