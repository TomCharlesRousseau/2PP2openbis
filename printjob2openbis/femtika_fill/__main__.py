"""
Command line: fill the print protocol from the Femtika output folders.

Usage (from printjob2openbis/)::

    python -m femtika_fill [EXCEL] [--logs-dir DIR] [--dry-run]

Defaults come from ``config/settings.json`` when present (read as plain JSON:
``excel.file_path`` and ``femtika.logs_dir``). No openBIS login.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from femtika_fill.fill import WorkbookLockedError, fill_workbook

_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_SETTINGS = _PACKAGE_DIR / "config" / "settings.json"


def _settings() -> Dict[str, Any]:
    """The private settings, or {} if there are none."""
    try:
        return json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run(excel: Optional[str], logs_dir: Optional[str], dry_run: bool) -> int:
    """Fill the workbook and print the summary; returns the exit code."""
    settings = _settings()
    excel_path = Path(excel) if excel else _PACKAGE_DIR / settings.get("excel", {}).get(
        "file_path", "2PP_print_protocol_v5.xlsx")
    logs = logs_dir or settings.get("femtika", {}).get("logs_dir")
    try:
        report = fill_workbook(excel_path, Path(logs) if logs else None, dry_run=dry_run)
    except (FileNotFoundError, WorkbookLockedError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 1
    for line in report.lines():
        print(line)
    return 1 if any(r.error for r in report.rows) else 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m femtika_fill",
        description="Fill empty PrintJobs cells from the Femtika output folders (no openBIS).")
    parser.add_argument("excel", nargs="?", help="Workbook (default: excel.file_path in settings)")
    parser.add_argument("--logs-dir", help="Folder with the run folders (default: femtika.logs_dir)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be filled; change nothing.")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    return run(args.excel, args.logs_dir, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
