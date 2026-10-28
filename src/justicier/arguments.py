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

"""Argument parsing, SharePoint field extraction, and business-rule validation."""

import argparse
import datetime
import sys
from pathlib import Path
from typing import Callable, Iterable, Any

from .logger import get_logger

from zoneinfo import ZoneInfo  # Python 3.9+

from .naf import NAF, is_naf_present, build_naf_to_dni, parse_naf
from .custom_except import (
    ArgumentDateError,
    UndefinedInputTypeError,
    UndefinedModeError,
    ArgumentNafInvalidError,
    ArgumentNafNotPresentError,
    ArgumentAuthorError,
)
from .defines import (
    DocType,
    SharepointListFields,
    from_string,
    InputLocation,
    Mode,
    SecretNames,
    SHAREPOINT_LIST_NAME,
    DATETIME_SHAREPOINT_FORMAT,
    DATE_DEFAULT_FORMAT,
    DEFAULT_TIMEZONE,
    LOCAL_GENERAL_INPUT_FOLDER,
)
from .secret import read_secret
from .sharepoint import get_parameters_from_list, SharepointItem
from .nif import NIF, parse_nif
from .name import Name, parse_name_sharepoint, parse_name_a3, parse_email_a3

log = get_logger(__name__)


def get_compact_init() -> dict[DocType, bool]:
    """Return a dict mapping every DocType to False (no merging requested).

    Returns:
        Dict with all DocType keys set to False.
    """
    return {
        DocType.SALARY: False,
        DocType.PROOFS: False,
        DocType.CONTRACT: False,
        DocType.RNT: False,
        DocType.RLC: False,
        DocType.SALARIES_AND_PROOFS: False,
    }


# Parser functions that validate the format and type of the data
def parse_id(value: str) -> str:
    """Return *value* unchanged; used as an argparse type for request IDs."""
    return value


def parse_date(
    value: str,
    formatting: str = DATE_DEFAULT_FORMAT,
    tz_name: str = DEFAULT_TIMEZONE,
    assume_tz: str = "UTC",
    return_naive: bool = True,
) -> datetime.datetime:
    """Parse a date/datetime string and convert to Europe/Madrid with DST awareness.

    - value: e.g. "2024-08-31T22:00:00Z" or "2024-08-31"
    - tz_name: target timezone (default Europe/Madrid)
    - assume_tz: if input is naive (date-only), treat it as this tz ("UTC" or any IANA tz)
    - return_naive: if True, drop tzinfo after conversion (keeps local wall time)
    """
    v = value.strip()
    try:
        # Handle trailing 'Z' (UTC) which datetime.fromisoformat pre-3.11 doesn't accept
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"

        if "T" in v or "+" in v or v.count(":") >= 1:
            # Likely a datetime
            dt = datetime.datetime.fromisoformat(v)
        else:
            # Likely a date-only string
            dt = datetime.datetime.strptime(v, formatting)

        if return_naive:
            return dt.replace(tzinfo=None)

        # If naive (no tzinfo), assign the assumed timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(assume_tz))

        # Convert to target local timezone (DST handled automatically)
        local_dt = dt.astimezone(ZoneInfo(tz_name))

        return local_dt

    except Exception as e:
        raise ArgumentDateError(
            f'The value "{value}" could not be parsed/converted: {e}'
        ) from e


def parse_author(author: str) -> str:
    """Return *author* unchanged; used as an argparse type for the author field."""
    return author


def parse_compact_options(value: str) -> dict[DocType, bool]:
    """Parse a comma-separated list of document type names into a merge-options dict.

    Args:
        value: Comma-separated string of DocType names, e.g. ``"salary,RLC"``.

    Returns:
        Dict with requested DocTypes set to True and all others False.
    """
    to_compact = get_compact_init()
    try:
        if "," in value:
            for s in value.split(","):
                doc_type = from_string(s)
                to_compact[doc_type] = True
        else:
            doc_type = from_string(value)
            to_compact[doc_type] = True
        return to_compact
    except ValueError as e:
        log.error(f"Error: {e}")
        exit(1)


def parse_boolean(value: bool | int | str | None) -> bool:
    """Parse a boolean-like value to a Python bool.

    Args:
        value: Accepts ``bool``, ``int``, ``"True"``, ``"False"``, or ``None``.

    Returns:
        The parsed boolean value.

    Raises:
        ValueError: If *value* is a string other than ``"True"`` or ``"False"``.
    """
    if value is None:
        return False

    if isinstance(value, bool):
        return value
    if value == "True":
        return True
    elif value == "False":
        return False
    raise ValueError(
        f"The value {value} can not be parsed into a boolean. It should be 'True' or 'False'"
    )


def parse_input_type(value: str) -> str:
    """Validate and return the input location type string.

    Args:
        value: Input type string; must be ``"sharepoint"`` or ``"local"``.

    Returns:
        The validated type string.

    Raises:
        UndefinedInputTypeError: If *value* is not a recognised input type.
    """
    if value == InputLocation.SHAREPOINT.value:
        return value
    elif value == InputLocation.LOCAL.value:
        return value
    else:
        raise UndefinedInputTypeError(
            'The type supplied for input type "' + value + '" is not defined.'
        )


def expand_job_id(job_id: int) -> SharepointItem:
    """Fetch all SharePoint list fields for the given job identifier.

    Args:
        job_id: Numeric identifier of the justification request.

    Returns:
        SharepointItem containing all field values for the request.
    """
    sharepoint_domain = read_secret(SecretNames.SHAREPOINT_DOMAIN.value)
    site_name = read_secret(SecretNames.SITE_NAME.value)
    list_name = SHAREPOINT_LIST_NAME

    return get_parameters_from_list(sharepoint_domain, site_name, list_name, job_id)


def parse_arguments_helper(arg_text: str) -> None:
    """Log a warning that a locally supplied argument will be overwritten by SharePoint data.

    Args:
        arg_text: Name of the argument that will be ignored.
    """
    log.debug(
        f"The {arg_text} has been provided via argument but it is used in conjunction with argument to "
        f"select request ID. The provided {arg_text} via argument will be ignored and the {arg_text} from "
        f"the corresponding row of the provided Microsoft List will be used."
    )


# Explicit contract: these args are sourced from SharePoint when --id/--request is given.
# Any locally supplied values for them will be warned about and then overwritten.
_ID_OVERRIDES: dict[
    str,
    Callable[
        [argparse.Namespace], NAF | Name | NIF | datetime.datetime | bool | str | None
    ],
] = {
    "naf": lambda a: a.naf,
    "name": lambda a: a.name,
    "email": lambda a: a.email,
    "nif": lambda a: a.nif,
    "begin": lambda a: a.begin,
    "end": lambda a: a.end,
    "author": lambda a: a.author,
    "merge_result": lambda a: a.merge_result != get_compact_init(),
    "merge_salary": lambda a: a.merge_salary,
    "merge_rnt_rlc": lambda a: a.merge_rnt_rlc,
}


def _warn_ignored_local_args(args: argparse.Namespace) -> None:
    """Warn for any local arg that will be ignored because --id/--request was given."""
    for name, was_set in _ID_OVERRIDES.items():
        if was_set(args):
            parse_arguments_helper(name)


def parse_input_location(value: str) -> Path:
    """Validate and convert a path string to a Path pointing to an existing directory.

    Args:
        value: File-system path string.

    Returns:
        Validated Path object.

    Raises:
        ValueError: If the path does not exist or is not a directory.
    """
    path = Path(value)
    if not path.exists():
        raise ValueError(f"Path {value} does not exist")
    if not path.is_dir():
        raise ValueError(f"Path {value} is not a directory")
    return path


def parse_mode(value: str) -> str:
    """Validate and return the execution mode string.

    Args:
        value: Mode string; must be one of ``"dev"``, ``"test"`` or ``"prod"``.

    Returns:
        The validated mode string.

    Raises:
        UndefinedModeError: If *value* is not a recognised mode.
    """
    if value == Mode.DEV.value:
        return value
    elif value == Mode.TEST.value:
        return value
    elif value == Mode.PROD.value:
        return value
    else:
        raise UndefinedModeError(
            'The value supplied for mode "' + value + '" is not defined.'
        )


def parse_arguments() -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = argparse.ArgumentParser(description="Justicier")

    parser.add_argument(
        "-r",
        "--request",
        "--id",
        type=parse_id,
        required=False,
        help="ID of the justification request in Microsoft List of Peticions Justificacions. If you use"
        " this argument you can't use any other argument to submit data to the algorithm except "
        " for -l / --location ",
    )

    parser.add_argument(
        "-l",
        "--location",
        type=parse_input_type,
        required=False,
        default=InputLocation.LOCAL.value,
        help='Location of the input data. Possible values are: "sharepoint" to download from '
        'sharepoint location and "local" to use the local file system storage and read the input'
        " folder in the repository root folder.",
    )
    parser.add_argument(
        "-L",
        "--input-location",
        type=parse_input_location,
        required=False,
        default=LOCAL_GENERAL_INPUT_FOLDER,
        help="Path location of input data. If used, --location local is assumed.",
    )

    parser.add_argument(
        "-n",
        "--naf",
        "--NAF",
        type=parse_naf,
        required=False,
        help="NAF (SS security number) of the employee to justify",
    )
    parser.add_argument(
        "-N",
        "--name",
        type=parse_name_a3,
        required=False,
        help="Name of the employee to justify",
    )
    parser.add_argument(
        "-E",
        "--email",
        type=parse_email_a3,
        required=False,
        help="Email of the employee to justify",
    )
    parser.add_argument(
        "-d",
        "--nif",
        "--NIF",
        type=parse_nif,
        required=False,
        help="Name of the employee to justify",
    )

    parser.add_argument(
        "-b", "--begin", type=parse_date, required=False, help="Begin date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "-e", "--end", type=parse_date, required=False, help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "-a",
        "--author",
        type=parse_author,
        required=False,
        help="author's email doing the justification request",
    )

    parser.add_argument(
        "-s",
        "--merge-salary",
        type=parse_boolean,
        required=False,
        default=False,
        help="Merge each salary with the corresponding bank proof",
    )
    parser.add_argument(
        "-m",
        "--merge-result",
        type=parse_boolean,
        required=False,
        default=get_compact_init(),
        help="Comma separated list of values that indicate which documents need to be merged in one "
        "single PDF in the output. Possible values are: "
        + ",".join([dt.value.__str__() for dt in DocType]),
    )
    parser.add_argument(
        "-R",
        "--merge-rnt-rlc",
        type=parse_boolean,
        required=False,
        default=False,
        help="Merge all RLCs and RNTs of each month.",
    )

    parser.add_argument(
        "--mode",
        type=parse_mode,
        required=False,
        default=Mode.DEV.value,
        help="Execution mode, controlling side effects on external systems. "
        '"dev" (default) skips both the SharePoint list update and the notification '
        'email. "test" updates the SharePoint list but skips the email. "prod" does '
        "both.",
    )

    args = parser.parse_args()

    return args


def _validate_required_sharepoint_fields(config: SharepointItem) -> None:
    """Step 2 – Required-field validation.

    Receives the raw SharepointItem returned by extraction (step 1) and checks
    that every field that is mandatory for the process to proceed is present
    (non-None).

    Responsibility: presence checks only — no type conversion, no business-rule
    checks.  Raises domain exceptions (ArgumentDateError, ArgumentAuthorError)
    when a required field is absent, so the caller can surface a meaningful error
    message without mixing concerns into the parsing layer.
    """
    if config[SharepointListFields.BEGIN] is None:
        raise ArgumentDateError("Field 'begin' is missing from SharePoint item")
    if config[SharepointListFields.END] is None:
        raise ArgumentDateError("Field 'end' is missing from SharePoint item")
    if config[SharepointListFields.AUTHOR_NAME] is None:
        raise ArgumentAuthorError("Field 'author' is missing from SharePoint item")


def _parse_sharepoint_fields(config: SharepointItem) -> dict[str, Any]:
    """Step 3 – Format parsing.

    Receives a raw SharepointItem whose required fields have already been
    validated (step 2) and converts each raw string value into its typed domain
    representation.

    Responsibility: type conversion only — no None-presence checks (already
    handled in step 2) and no business-rule validation (handled in step 4).
    Optional fields are included in the returned dict only when their raw value
    is truthy, so the caller can detect which fields were actually populated and
    avoid overwriting argparse defaults with None.

    Raises format exceptions (ArgumentDateError, ArgumentNafInvalidError, …) when a
    field value cannot be converted into the expected type.
    """
    parsed: dict[str, Any] = {}

    if config[SharepointListFields.NAF]:
        parsed["naf"] = parse_naf(str(config[SharepointListFields.NAF]))
    if config[SharepointListFields.TARGET_NAME]:
        parsed["name"] = parse_name_sharepoint(
            str(config[SharepointListFields.TARGET_NAME])
        )
    if config[SharepointListFields.TARGET_EMAIL]:
        parsed["target_email"] = str(config[SharepointListFields.TARGET_EMAIL])
    if config[SharepointListFields.NIF]:
        parsed["dni"] = parse_nif(str(config[SharepointListFields.NIF]))

    # Required fields — guaranteed non-None after step 2
    parsed["begin"] = parse_date(
        str(config[SharepointListFields.BEGIN]),
        DATETIME_SHAREPOINT_FORMAT,
        return_naive=False,
    ).replace(tzinfo=None)
    parsed["end"] = parse_date(
        str(config[SharepointListFields.END]),
        DATETIME_SHAREPOINT_FORMAT,
        return_naive=False,
    ).replace(tzinfo=None)
    parsed["title"] = config[SharepointListFields.REQUEST_TITLE]
    parsed["author"] = parse_author(str(config[SharepointListFields.AUTHOR_NAME]))
    parsed["author_email"] = config[SharepointListFields.AUTHOR_EMAIL]

    parsed["merge_salary"] = parse_boolean(
        config[SharepointListFields.MERGE_SALARY_BANKPROOF]
    )

    if parse_boolean(config[SharepointListFields.MERGE_RESULTS]):
        compact_default = get_compact_init()
        compact_default = {key: True for key in compact_default}
        parsed["merge_result"] = compact_default
    parsed["merge_rnt_rlc"] = parse_boolean(config[SharepointListFields.MERGE_RLC_RNT])

    return parsed


def _populate_from_sharepoint(args: argparse.Namespace, common: str) -> None:
    """Orchestrate the SharePoint population pipeline and write values into *args*.

    Steps performed in order:
      1. Extraction            – fetch the raw SharepointItem via expand_job_id().
      2. Required-field check  – delegate to _validate_required_sharepoint_fields().
      3. Format parsing        – delegate to _parse_sharepoint_fields().

    Responsibility: coordination and error handling only — the individual steps
    carry no knowledge of each other.  Catches domain and format exceptions raised
    by steps 2–3, prints a user-friendly message, and exits with the appropriate
    error code.  Only fields that were present in SharePoint are written to args;
    optional absent fields keep whatever default was set by parse_arguments().

    Steps performed in order:
      1. Extraction            – fetch the raw SharepointItem via expand_job_id().
      2. Required-field check  – delegate to _validate_required_sharepoint_fields().
      3. Format parsing        – delegate to _parse_sharepoint_fields().

    Responsibility: coordination and error handling only — the individual steps
    carry no knowledge of each other.  Catches domain and format exceptions raised
    by steps 2–3, prints a user-friendly message, and exits with the appropriate
    error code.  Only fields that were present in SharePoint are written to args;
    optional absent fields keep whatever default was set by parse_arguments().

    Args:
        args: argparse Namespace to populate in-place.
        common: Fallback error context string logged alongside specific errors.
    """
    config = expand_job_id(args.request)
    log.trace(f"configuration from sharepoint: {config}")
    try:
        _validate_required_sharepoint_fields(config)
        parsed = _parse_sharepoint_fields(config)
    except ArgumentNafInvalidError as e:
        log.error(f"The NAF provided is invalid. Internal error is {e}")
        log.error(common)
        exit(2)
    except ArgumentDateError as e:
        log.error(f"The dates provided are invalid. Internal error is {e}")
        log.error(common)
        exit(3)
    except argparse.ArgumentTypeError as e:
        log.error(f"Arguments could not have been parsed. Internal error is {e}")
        log.error(common)
        exit(5)

    for field, value in parsed.items():
        setattr(args, field, value)


def process_parse_arguments() -> argparse.Namespace:
    """Parse, enrich from SharePoint, and fully validate all CLI arguments.

    Returns:
        Fully validated argparse Namespace ready for use by the pipeline.
    """
    common = (
        f"Error parsing arguments. Program aborting. The arguments are: {sys.argv}"
        "The program is in a uninitialized state and cannot proceed. This error will be "
        "notified to the admin via log file. We can't create log file in user author folder "
        "because user author could not be parsed."
    )
    try:
        args = parse_arguments()

    except ArgumentNafInvalidError as e:
        log.error(
            f"The NAF provided is invalid. Internal error is {e}. Common error {common}"
        )
        exit(2)
    except ArgumentDateError as e:
        log.error(
            f"The dates provided are invalid. Internal error is {e}. Common error {common}"
        )
        exit(3)
    except argparse.ArgumentTypeError as e:
        log.error(
            f"Arguments could not have been parsed. Internal error is {e}. Common error {common}"
        )
        exit(5)

    if args.request:
        _warn_ignored_local_args(args)
        _populate_from_sharepoint(args, common)

    if args.input_location:
        args.location = InputLocation.LOCAL.value

    # Set time to first second of day, so we do select all documents produced the same day as the beginning
    if args.begin:
        args.begin = args.begin.replace(hour=0, minute=0, second=0, microsecond=0)
    if args.end:
        args.end = args.end.replace(hour=23, minute=59, second=59, microsecond=999999)
    if args.begin and args.end:
        if args.begin >= args.end:
            raise ValueError(f"Begin date {args.begin} can not be after {args.end}")
    return args


# Validations functions that check if the data from the request is valid regarding business rules


def validate_naf(naf: NAF, valid_nafs: Iterable[NAF]) -> None:
    """Step 4 – Business-rule validation for NAF.

    Checks whether the already-parsed NAF value is allowed by the business rules
    (i.e. it exists in the known-employee list).

    Responsibility: domain constraint checks only — the NAF has already been
    converted to its typed form in step 3.  Raises ArgumentNafNotPresentError when
    the NAF is not found in the authorised set.
    """
    if not is_naf_present(naf, valid_nafs):
        raise ArgumentNafNotPresentError


def is_author_present(author: str, valid_authors: Iterable[str]) -> bool:
    """Return True if *author* appears in the iterable of authorised authors."""
    return author in valid_authors


def validate_author(author: str, valid_authors: Iterable[str]) -> None:
    """Step 4 – Business-rule validation for author.

    Checks whether the already-parsed author value is allowed by the business
    rules (i.e. it belongs to the list of authorised requesters).

    Responsibility: domain constraint checks only — the author string has already
    been normalised in step 3.  Raises ArgumentAuthorError when the author is not
    found in the authorised set.
    """
    if not is_author_present(author, valid_authors):
        raise ArgumentAuthorError(
            f'Author "{author}" is not valid. '
        )  # more specific exception


def validate_arguments(
    args: argparse.Namespace, valid_nafs: Iterable[NAF], valid_authors: Iterable[str]
) -> None:
    """Step 4 – Business-rule validation for all arguments.

    Delegates to the individual field validators (validate_author, validate_naf)
    after all format parsing (step 3) has been completed.  Raises the first
    domain exception encountered.
    """
    validate_author(args.author, valid_authors)
    validate_naf(args.naf, valid_nafs)


def process_validate_arguments(
    args: argparse.Namespace, naf_data_path: Path, user_list_data_path: Path
) -> None:
    """Validate NAF and author against the authorised employee and user lists.

    Args:
        args: Parsed CLI arguments containing NAF and author to validate.
        naf_data_path: Path to the NAF/DNI Excel file.
        user_list_data_path: Path to the plain-text authorised-users file.
    """
    common = (
        f"Error validating arguments. Program aborting. The arguments are: {sys.argv}"
        "The program is in a uninitialized state and cannot proceed. This error will be "
        "notified to the admin via log file. We can't create log file in user author folder "
        "because the process that validates user author could not finish."
    )

    nafs = build_naf_to_dni(naf_data_path).keys()

    authors = []
    with open(user_list_data_path, newline="", encoding="utf-8") as f:
        for line in f.readlines():
            authors.append(line)

    try:
        validate_arguments(args, nafs, authors)

    except ArgumentNafNotPresentError as e:
        log.error(
            f"The NAF provided is valid but is not present in {naf_data_path}. "
            f"Internal error is {e}. Common error is: {common}"
        )
        exit(1)
    except ArgumentAuthorError as e:
        log.error(
            f"The author is not present in the accepted user list. Internal error is {e}. Common error is: {common}"
        )
        exit(4)
