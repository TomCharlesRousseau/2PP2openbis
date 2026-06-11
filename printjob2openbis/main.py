"""
Main orchestrator for printjob2openbis.

Reads the print-job Excel spreadsheet and creates one EXPERIMENTAL_STEP
object per print job in openBIS, validating parents and skipping
duplicates.

Usage::

    python main.py [--excel PATH] [--dry-run]
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from config.settings import Settings
from excel.excel_parser import ExcelParser
from excel.description_builder import build_description
from models.printjob import PrintJob
from openbis.connection import OpenBISConnection
from openbis.object_manager import ObjectManager
from utils.logger import get_logger
from utils.validators import is_valid_perm_id

logger = get_logger(__name__)


class PrintJobParser:
    """Orchestrates Excel parsing and openBIS object creation."""

    def __init__(self, excel_file: Optional[Path] = None) -> None:
        """
        Initialise the parser.

        Args:
            excel_file: Path to the Excel file. Falls back to the value
                from ``config/settings.json`` when not supplied.
        """
        self._cfg = Settings()
        self.excel_file = Path(excel_file) if excel_file else Path(self._cfg.excel_file_path)
        self.excel_parser = ExcelParser(self.excel_file)
        self.conn = OpenBISConnection()
        self.object_manager: Optional[ObjectManager] = None

        # Run statistics
        self.total = 0
        self.created = 0
        self.skipped = 0
        self.failed = 0

    def run(self, dry_run: bool = False) -> bool:
        """
        Execute the full import workflow.

        For each row in the spreadsheet the method:
        1. Checks whether the code already exists → skip with INFO.
        2. Validates Resin ID and Substrate ID via ``object_exists()``
           → skip with ERROR if a parent is missing.
        3. Builds a description and creates the ``EXPERIMENTAL_STEP``.

        Args:
            dry_run: When ``True``, parse and validate but do not write to
                openBIS.

        Returns:
            ``True`` if the run completed without a fatal error.
        """
        logger.info("=" * 70)
        logger.info("printjob2openbis starting")
        logger.info("=" * 70)

        try:
            if not dry_run:
                logger.info("Connecting to openBIS...")
                openbis = self.conn.connect()
                if openbis is None:
                    logger.error("Failed to connect to openBIS")
                    return False
                self.object_manager = ObjectManager(openbis)
                logger.info("Connected to openBIS")
            else:
                logger.info("[DRY RUN] Skipping openBIS connection")

            jobs = self.excel_parser.parse()

            if not jobs:
                logger.info("No print jobs found in spreadsheet")
                return True

            logger.info(f"Processing {len(jobs)} print job(s)...")

            for job in jobs:
                self.total += 1
                status = self._process_job(job, dry_run)
                if status == "created":
                    self.created += 1
                elif status == "skipped":
                    self.skipped += 1
                else:
                    self.failed += 1

            self._log_summary()
            return True

        except Exception as exc:
            logger.error(f"Fatal error: {exc}", exc_info=True)
            return False

        finally:
            if not dry_run:
                self.conn.disconnect()

    def _process_job(self, job: PrintJob, dry_run: bool) -> str:
        """
        Process a single print job.

        Args:
            job: PrintJob instance to process.
            dry_run: Skip actual object creation when ``True``.

        Returns:
            ``"created"``, ``"skipped"``, or ``"failed"``.
        """
        code = job.code
        logger.info(f"Processing: {code} ({job.name})")

        # ── Duplicate detection ────────────────────────────────────────────
        if not dry_run and self.object_manager is not None:
            if self.object_manager.object_exists(code):
                logger.info(f"EXPERIMENTAL_STEP {code} already exists. Skipping.")
                return "skipped"

        # ── Parent validation ──────────────────────────────────────────────
        if not dry_run and self.object_manager is not None:
            for parent_label, parent_id in [
                ("Resin ID", job.resin_id),
                ("Substrate ID", job.substrate_id),
            ]:
                if not is_valid_perm_id(parent_id):
                    logger.error(
                        f"Row '{code}': {parent_label} is empty or missing – skipping"
                    )
                    return "skipped"

                if not self.object_manager.object_exists(parent_id):
                    logger.error(
                        f"Row '{code}': {parent_label} '{parent_id}' does not exist "
                        f"in openBIS – skipping"
                    )
                    return "failed"

        # ── Dry-run output ─────────────────────────────────────────────────
        if dry_run:
            logger.info(f"  [DRY RUN] Would create EXPERIMENTAL_STEP '{code}'")
            logger.info(f"    Name:        {job.name}")
            logger.info(f"    Resin ID:    {job.resin_id}")
            logger.info(f"    Substrate ID: {job.substrate_id}")
            return "created"

        # ── Object creation ────────────────────────────────────────────────
        description = build_description(job)
        perm_id = self.object_manager.create_experimental_step(
            name=job.name,
            code=code,
            parents=job.parent_ids(),
            description=description,
            print_date=job.print_date,
        )

        if perm_id is None:
            logger.error(f"Failed to create EXPERIMENTAL_STEP '{code}'")
            return "failed"

        logger.info(f"Created EXPERIMENTAL_STEP '{code}' (permId: {perm_id})")
        return "created"

    def _log_summary(self) -> None:
        """Print a summary of the run."""
        logger.info("=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total rows:  {self.total}")
        logger.info(f"Created:     {self.created}")
        logger.info(f"Skipped:     {self.skipped}")
        logger.info(f"Failed:      {self.failed}")
        logger.info("=" * 70)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Parse print-job Excel spreadsheet and upload to openBIS."
    )
    parser.add_argument(
        "--excel",
        metavar="PATH",
        help="Path to the Excel file (overrides config/settings.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to openBIS",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = _parse_args()
    excel_path = Path(args.excel) if args.excel else None

    try:
        runner = PrintJobParser(excel_file=excel_path)
        success = runner.run(dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
