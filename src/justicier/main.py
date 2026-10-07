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

"""Main entry point: orchestrates the full justification pipeline."""

import argparse
import logging
import time
from pathlib import Path

from justicier.data import reverse_dict, complete_ids
from .naf import (
    build_naf_to_dni,
    build_naf_to_name,
    build_naf_to_email,
    flatten_dict_list,
)
from .token_manager import get_token_manager
from .arguments import process_parse_arguments
from .chrono import elapsed_time
from .custom_except import (
    PersonDoesNotExistInSharepointError,
    SecretCouldNotBeReadFromAnySourceError,
)
from .defines import (
    SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME,
    SHAREPOINT_PROOFS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME,
    DocType,
    SHAREPOINT_SALARIES_AND_PROOFS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME,
    SHAREPOINT_RNTS_AND_RLCS_OUTPUT_FOLDER_NAME,
    ROOT_FOLDER_PATH,
    SharepointListFields,
    SharepointListFieldWorkflowState,
    LOCAL_ADMIN_LOG_FOLDER_PATH,
    InputElementsNames,
    InputLocation,
    SecretNames,
    SHAREPOINT_ROOT_INPUT_FOLDER_NAME,
    SHAREPOINT_DRIVE_NAME,
    SHAREPOINT_ADMIN_LOGS_FOLDER_PATH,
    SHAREPOINT_OUTPUT_FOLDER_PATH,
    SHAREPOINT_INPUT_FOLDER_PATH,
    NOW_COMMAS,
    SHAREPOINT_ADMIN_LOGS_OUTPUT_FOLDER_NAME,
)
from .filesystem import (
    remove_folder,
    compute_id,
    compute_impersonal_id,
    compute_paths,
    ensure_file_structure,
    get_first_file_path_in_folder,
)
from .logger import get_logger, setup_logging
from .mail import mail_process
from .pdf import merge_pdfs, compact_folder, merge_equal_files_from_two_folders
from .report import get_end_user_report, get_initial_user_report
from .secret import read_secret
from .sharepoint import (
    download_input_folder,
    upload_folder_recursive,
    upload_file,
    get_site_id,
    get_drive_id,
    update_list_item_field,
    get_sharepoint_web_url,
    _connect_sharepoint,
    update_list_with_person_ids,
)
from .tasks import (
    process_salaries_with_rlc,
    process_proofs,
    process_contracts,
    process_rnts,
    merge_rnts_rlcs,
)

log = get_logger(__name__)


def process(args: argparse.Namespace, input_folder: Path) -> tuple[str, str]:
    """Run the full justification pipeline for one employee request.

    Downloads input data, extracts matching documents, uploads results to
    SharePoint, and sends the completion email.

    Args:
        args: Validated CLI arguments containing NAF, dates, and options.
        input_folder: Local directory where input files are stored or downloaded.

    Returns:
        Tuple of ``(result_sharepoint_url, log_sharepoint_url)``.
    """
    if args.request:
        update_list_item_field(
            args.request,
            {
                SharepointListFields.WORKFLOW_STATE.value: SharepointListFieldWorkflowState.IN_EXECUTION.value
            },
        )

    salaries_folder: Path = input_folder / InputElementsNames.SALARIES.value
    proofs_folder: Path = input_folder / InputElementsNames.BANKPROOFS.value
    contracts_folder: Path = input_folder / InputElementsNames.CONTRACTS.value
    rnts_folder: Path = input_folder / InputElementsNames.RNTS.value
    rlcs_folder: Path = input_folder / InputElementsNames.RLCS.value

    naf_data_path: Path = input_folder / InputElementsNames.NAF_DNI.value

    start_time = time.time()

    if args.location == InputLocation.SHAREPOINT.value:
        token_manager, site_id, drive_id = _connect_sharepoint()
        carpeta_sharepoint = SHAREPOINT_INPUT_FOLDER_PATH
        remove_folder(input_folder)
        download_input_folder(token_manager, drive_id, carpeta_sharepoint, input_folder)

    naf_to_dni = build_naf_to_dni(naf_data_path)
    dni_to_naf = reverse_dict(flatten_dict_list(naf_to_dni))
    naf_to_name = build_naf_to_name(naf_data_path)
    name_to_naf = reverse_dict(naf_to_name)
    naf_to_email = build_naf_to_email(naf_data_path)
    email_to_naf = reverse_dict(naf_to_email)

    args.naf, nifs, args.name, args.email = complete_ids(
        args.naf,
        args.nif,
        args.email,
        args.name,
        name_to_naf,
        naf_to_dni,
        dni_to_naf,
        naf_to_name,
        email_to_naf,
        naf_to_email,
    )

    nifs = naf_to_dni[args.naf]

    if args.request:
        try:
            update_list_with_person_ids(args.request, args.naf, nifs[0], args.email)
        except PersonDoesNotExistInSharepointError as e:
            log.warning(
                "The person to be justified does not exist in the Sharepoint database. This means that the person"
                "probably has left ICIQ and IT has already removed its user account. The justification will "
                'continue normally but the "Nom de la persona" field will be left unfilled in the '
                f"corresponding row of the requests list. Internal error is: {str(e)}"
            )

    id_str = compute_id(
        NOW_COMMAS,
        args.naf,
        args.begin,
        args.end,
        args.request,
        args.author,
        naf_to_name,
    )
    impersonal_id_str = compute_impersonal_id(
        NOW_COMMAS, args.naf, args.begin, args.end, args.request, naf_to_name
    )

    (
        current_user_folder,
        current_justification_folder,
        user_report_file,
        admin_log_path,
        supervisor_log_path,
    ) = compute_paths(args.author, id_str, impersonal_id_str)

    ensure_file_structure(current_user_folder, current_justification_folder)

    setup_logging(
        level=logging.DEBUG,
        user_report_file=user_report_file,
        admin_log_file=admin_log_path,
        supervisor_log_file=supervisor_log_path,
    )

    log.info(
        get_initial_user_report(
            args.naf,
            args.begin,
            args.end,
            args.merge_result,
            args.merge_salary,
            args.merge_rnt_rlc,
            args.author,
            args.request,
        )
    )

    end_time = elapsed_time(start_time)
    log.info(f"Time elapsed for obtaining and validating input data: {end_time}.")
    start_time = time.time()

    # Salaries & RLC
    salary_output_path: Path = (
        current_justification_folder / SHAREPOINT_SALARIES_OUTPUT_FOLDER_NAME
    )
    salaries_with_rlcs_result, scanned_liquidation_found = process_salaries_with_rlc(
        salaries_folder,
        rlcs_folder,
        current_justification_folder,
        args.naf,
        args.begin,
        args.end,
    )

    # Bank proofs
    proof_output_path: Path = (
        current_justification_folder / SHAREPOINT_PROOFS_OUTPUT_FOLDER_NAME
    )
    process_proofs(
        proofs_folder,
        proof_output_path,
        args.naf,
        args.begin,
        args.end,
        naf_to_dni,
        scanned_liquidation_found,
    )

    rlc_output_path: Path = (
        current_justification_folder / SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME
    )
    if args.merge_salary:
        salaries_and_bankproofs_output_path: Path = (
            current_justification_folder
            / SHAREPOINT_SALARIES_AND_PROOFS_OUTPUT_FOLDER_NAME
        )
        merge_equal_files_from_two_folders(
            salary_output_path, proof_output_path, salaries_and_bankproofs_output_path
        )
        if args.merge_result[DocType.SALARIES_AND_PROOFS]:
            compact_folder(salaries_and_bankproofs_output_path)
    if args.merge_result[DocType.SALARY]:
        compact_folder(salary_output_path)
    if args.merge_result[DocType.RLC]:
        compact_folder(rlc_output_path)
    if args.merge_result[DocType.PROOFS]:
        compact_folder(proof_output_path)

    # Contracts
    contracts_result = process_contracts(
        contracts_folder,
        current_justification_folder,
        args.naf,
        args.begin,
        args.end,
    )
    contract_output_path: Path = (
        current_justification_folder / SHAREPOINT_CONTRACTS_OUTPUT_FOLDER_NAME
    )
    if args.merge_result[DocType.CONTRACT]:
        compact_folder(contract_output_path)

    # RNTs
    rnts_result = process_rnts(
        rnts_folder, current_justification_folder, args.naf, args.begin, args.end
    )
    rnt_output_path: Path = (
        current_justification_folder / SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME
    )
    if args.merge_result[DocType.RNT]:
        compact_folder(rnt_output_path)

    # Merge RLC & RNT
    if args.merge_rnt_rlc:
        log.info("Starting the merge of RNT and RLC")
        if args.merge_result[DocType.RNT] or args.merge_result[DocType.RLC]:
            rnts_merged_path: Path = current_justification_folder / (
                str(SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME) + ".pdf"
            )
            rlcs_merged_path: Path = current_justification_folder / (
                str(SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME) + ".pdf"
            )
            if rnts_merged_path.exists() and rlcs_merged_path.exists():
                rnt_rlc_merged_output_path: Path = current_justification_folder / (
                    str(SHAREPOINT_RNTS_AND_RLCS_OUTPUT_FOLDER_NAME) + ".pdf"
                )
                merge_pdfs(
                    [rnts_merged_path, rlcs_merged_path],
                    rnt_rlc_merged_output_path,
                    True,
                )
            else:
                log.warning(
                    "The merge of RNT and RLC was not done because we were also instructed to merge each type"
                    " of document in a single file, but either RNTs.pdf or RLCs.pdf with the final results"
                    " of the merge do not exist, so the merge will not be done. Try again without marking"
                    " the option to merge the documents, only mark RLC and RNT merging"
                )
        else:
            (
                current_justification_folder
                / SHAREPOINT_RNTS_AND_RLCS_OUTPUT_FOLDER_NAME
            ).mkdir(parents=True, exist_ok=True)
            merge_rnts_rlcs(
                current_justification_folder / SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME,
                current_justification_folder / SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME,
                current_justification_folder / SHAREPOINT_RNTS_OUTPUT_FOLDER_NAME,
                current_justification_folder / SHAREPOINT_RLCS_OUTPUT_FOLDER_NAME,
                current_justification_folder
                / SHAREPOINT_RNTS_AND_RLCS_OUTPUT_FOLDER_NAME,
                args.begin,
                args.end,
            )

    report_text = get_end_user_report(
        salaries_with_rlcs_result=salaries_with_rlcs_result,
        contracts_result=contracts_result,
        rnts_result=rnts_result,
        naf=args.naf,
        begin=args.begin,
        end=args.end,
    )
    log.info(report_text)
    exit(0)

    if args.request:
        end_time = elapsed_time(start_time)
        log.info(f"Time elapsed for doing this justification: {end_time}.")
        start_time = time.time()
        elapsed_time(start_time)

        token_manager, site_id, drive_id = _connect_sharepoint()
        remote_output_path = (
            f"{SHAREPOINT_OUTPUT_FOLDER_PATH}/{args.author}/{impersonal_id_str}"
        )
        remote_log_path = (
            f"{SHAREPOINT_OUTPUT_FOLDER_PATH}/"
            f"{SHAREPOINT_ADMIN_LOGS_OUTPUT_FOLDER_NAME}/{admin_log_path.name}"
        )

        upload_folder_recursive(
            token_manager=token_manager,
            drive_id=drive_id,
            local_folder_path=current_justification_folder,
            remote_folder_path=remote_output_path,
        )

        link = get_sharepoint_web_url(
            token_manager, site_id, drive_id, remote_output_path
        )
        log.info(f"Clickable SharePoint URL: {link}  ")

        upload_file(token_manager, drive_id, remote_log_path, admin_log_path)
        log_link = get_sharepoint_web_url(
            token_manager, site_id, drive_id, remote_log_path
        )

        end_time = elapsed_time(start_time)
        log.info(f"Time elapsed for uploading data: {end_time}.")
        start_time = time.time()
        elapsed_time(start_time)

        log.debug("Updating list element state to Completed")
        update_list_item_field(
            args.request,
            {
                SharepointListFields.WORKFLOW_STATE.value: SharepointListFieldWorkflowState.COMPLETED.value
            },
        )
        log.debug("Updating list element error message to no error message")
        update_list_item_field(
            args.request, {SharepointListFields.ERROR_MESSAGE.value: "-"}
        )
        log.debug("Updating list element link to result")
        update_list_item_field(
            args.request, {SharepointListFields.RESULT.value: str(link)}
        )

    return link, log_link


def main() -> None:
    """Parse arguments, run the justification pipeline, and handle top-level errors."""
    setup_logging()
    args = process_parse_arguments()

    input_folder: Path = ROOT_FOLDER_PATH / SHAREPOINT_ROOT_INPUT_FOLDER_NAME
    if args.input_location:
        input_folder = args.input_location

    result_link = ""
    log_link = ""
    try:
        result_link, log_link = process(args, input_folder)
    except ValueError as e:
        err = f"A not controlled error happen during execution of Justicier. Error is: {str(e)}"
        log.error(err)
        if args.request:
            update_list_item_field(
                args.request, {SharepointListFields.ERROR_MESSAGE.value: err}
            )

            update_list_item_field(
                args.request,
                {
                    SharepointListFields.WORKFLOW_STATE.value: SharepointListFieldWorkflowState.ERROR.value
                },
            )

            if (
                LOCAL_ADMIN_LOG_FOLDER_PATH.is_dir()
            ):  # Only upload when the folder is detected
                supervisor_log_path = get_first_file_path_in_folder(
                    LOCAL_ADMIN_LOG_FOLDER_PATH
                )
                token_manager = get_token_manager()
                sharepoint_domain = read_secret(SecretNames.SHAREPOINT_DOMAIN.value)
                site_name = read_secret(SecretNames.SITE_NAME.value)
                site_id = get_site_id(token_manager, sharepoint_domain, site_name)
                drive_id = get_drive_id(
                    token_manager, site_id, drive_name=SHAREPOINT_DRIVE_NAME
                )

                upload_file(
                    token_manager,
                    drive_id,
                    str(SHAREPOINT_ADMIN_LOGS_FOLDER_PATH) + supervisor_log_path.name,
                    supervisor_log_path,
                )
        exit(1)

    log.info("Justification process is finished.")
    log.info("Sending notification email")

    try:
        owner_email = read_secret(SecretNames.SMTP_OWNER_EMAIL.value)
    except SecretCouldNotBeReadFromAnySourceError:
        owner_email = "justicier@org.org"

    if args.request:
        mail_process(
            result_link=result_link,
            log_link=log_link,
            title=args.title,
            request=args.request,
            name=args.name,
            author=args.author_email,
            begin=args.begin,
            end=args.end,
            owner_email=owner_email,
        )


if __name__ == "__main__":
    main()
