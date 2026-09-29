"""
printjob2openbis command line.

Usage::

    python main.py check [--offline] [--excel PATH]
    python main.py upload [--dry-run] [--update] [--excel PATH]

``check`` validates the 2PP print protocol and writes nothing. Online (the
default) it also logs in and verifies that every referenced permId exists.
``upload`` runs the online check first, then creates the objects: 3DPoli job objects,
print steps, printed samples, washing / CPD / sintering runs, sintered samples, imaging steps.
``--dry-run`` reads openBIS but writes nothing.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, List, Optional

import requests

from checks.checker import check_protocol, sorted_issues
from checks.issues import CheckResult
from config.settings import Settings
from excel.excel_reader import ProtocolData, read_protocol
from utils.logger import get_logger

logger = get_logger(__name__)

_PACKAGE_DIR = Path(__file__).parent

#: Collection groups the upload writes to.
UPLOAD_GROUPS = ("poli", "printjobs", "samples", "washing", "cpd", "sintering", "imaging")


def _package_path(value: str) -> Path:
    """Path from settings; a relative path is relative to this package."""
    path = Path(value)
    return path if path.is_absolute() else _PACKAGE_DIR / path


def _excel_path(cfg: Settings, override: Optional[str]) -> Path:
    """Excel file from ``--excel`` (relative to the current directory) or from settings."""
    return Path(override) if override else _package_path(cfg.excel_file_path)


def connect(cfg: Settings) -> Any:
    """Log in to openBIS (keyring PAT, password prompt as fallback)."""
    from openbis_utils.connection import connect_openbis

    openbis, _, _ = connect_openbis(url=cfg.openbis_url, userid=cfg.openbis_username)
    return openbis


def run_check(cfg: Settings, data: ProtocolData, openbis: Optional[Any]) -> CheckResult:
    """
    Run all checks on *data*.

    Args:
        cfg: Settings (printer permId, bam_oe).
        data: Workbook content.
        openbis: Logged-in session, or None for an offline check (permIds and
            bam_oe are then not checked in openBIS).

    Returns:
        The check result.
    """
    lookup = terms = None
    if openbis is not None:
        from openbis.lookup import existing_permids, vocabulary_terms

        lookup = lambda permids: existing_permids(openbis, permids)  # noqa: E731
        terms = lambda vocabulary: vocabulary_terms(openbis, vocabulary)  # noqa: E731
    return check_protocol(data, printer_permid=cfg.printer_permid, permid_lookup=lookup,
                          bam_oe=cfg.bam_oe, vocabulary_lookup=terms)


def run_upload(cfg: Settings, data: ProtocolData, check: CheckResult, openbis: Any,
               dry_run: bool, update: bool) -> int:
    """
    Upload *data* (check must not be fatal) and print the summary.

    Returns:
        Exit code: 0 if no upload error, else 1.
    """
    from openbis.object_manager import ObjectManager
    from openbis.uploader import UploadConfig, Uploader, write_report

    try:
        collection_paths = {group: cfg.collection_path(group) for group in UPLOAD_GROUPS}
    except ValueError as exc:  # collection not configured in settings.json
        print(f"ERROR: {exc}")
        return 1
    config = UploadConfig(printer_permid=cfg.printer_permid, bam_oe=cfg.bam_oe,
                          collection_paths=collection_paths)
    manager = ObjectManager(openbis, cfg.openbis_space, cfg.project_name, dry_run=dry_run)
    stats = Uploader(manager, config, data, check, update=update).run()
    report = write_report(stats, _package_path(cfg.report_dir), dry_run)

    print()
    print("DRY-RUN (nothing written to openBIS)" if dry_run else "Upload finished")
    print(f"  openBIS: {stats.summary(dry_run)}")
    print(f"  Check:   {len(check.errors)} error(s), {len(check.warnings)} warning(s) "
          f"(affected rows were skipped; see the list above).")
    print(f"  Report:  {report}")
    return 1 if stats.errors else 0


def print_report(result: CheckResult, offline: bool) -> None:
    """Print every issue and a summary line to stdout."""
    for issue in sorted_issues(result.issues):
        print(issue)
    if result.issues:
        print()
    if result.fatal:
        print("File-level ERROR: nothing can be uploaded until it is fixed.")
    print(f"{len(result.errors)} error(s), {len(result.warnings)} warning(s).")
    if offline:
        print("Offline check: permIds and bam_oe were not verified in openBIS.")


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Check the 2PP print protocol and upload it to openBIS."
    )
    parser.add_argument("--excel", metavar="PATH",
                        help="Excel file (default: excel.file_path in config/settings.json)")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Validate the Excel file; writes nothing.")
    check.add_argument("--offline", action="store_true",
                       help="Do not log in: Excel and Lists checks only.")

    upload = commands.add_parser("upload", help="Check, then create the objects in openBIS.")
    upload.add_argument("--dry-run", action="store_true",
                        help="Log what would be created / linked / updated; write nothing.")
    upload.add_argument("--update", action="store_true",
                        help="Also overwrite properties of existing objects from the Excel.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point; returns the process exit code (0 = no errors)."""
    args = _parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows console: never fail on a character
    cfg = Settings()
    excel = _excel_path(cfg, args.excel)
    offline = getattr(args, "offline", False)

    try:
        data = read_protocol(excel)
        openbis = None if offline else connect(cfg)
        result = run_check(cfg, data, openbis)
        print_report(result, offline=offline)
        if args.command == "check":
            return 1 if result.errors else 0

        if result.fatal:
            print("Upload stopped.")
            return 1
        return run_upload(cfg, data, result, openbis, dry_run=args.dry_run, update=args.update)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    except requests.ConnectionError as exc:
        print(f"ERROR: {exc} Run 'check --offline' to check the Excel file only.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
