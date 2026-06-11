"""
Excel parser for the print-job spreadsheet.

Reads the Excel file (headers on row 2) and converts each data row
into a PrintJob dataclass instance.
"""

import pandas as pd
from pathlib import Path
from typing import Any, List, Optional

from models.printjob import PrintJob
from excel.column_mapping import COLUMN_TO_FIELD, REQUIRED_COLUMNS
from utils.logger import get_logger

logger = get_logger(__name__)

# Sentinel values that represent "no data" in a cell.
_EMPTY_VALUES = {"nan", "none", "n/a", ""}


def _clean(value: Any) -> Optional[str]:
    """
    Convert a cell value to a clean string or None.

    Args:
        value: Raw cell value from pandas.

    Returns:
        Stripped string, or None if the value is empty/NaN.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _EMPTY_VALUES:
        return None
    return text


class ExcelParser:
    """Parse the print-job protocol Excel file."""

    def __init__(self, file_path: Path) -> None:
        """
        Initialise the parser and load the spreadsheet.

        Args:
            file_path: Path to the Excel file.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If required columns are missing.
        """
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(f"Excel file not found: {self.file_path}")

        logger.info(f"Loading Excel file: {self.file_path}")

        # Row 2 in Excel = index 1 (0-based), so header=1.
        self.df = pd.read_excel(self.file_path, header=1, engine="openpyxl")

        logger.info(f"Found columns: {list(self.df.columns)}")
        self._validate_columns()
        logger.info(f"Loaded {len(self.df)} data rows")

    def _validate_columns(self) -> None:
        """
        Validate that all required columns are present.

        Raises:
            ValueError: If any required column is missing.
        """
        missing = set(REQUIRED_COLUMNS) - set(self.df.columns)
        if missing:
            raise ValueError(
                f"Missing required columns: {missing}\n"
                f"Found columns: {list(self.df.columns)}"
            )

    def parse(self) -> List[PrintJob]:
        """
        Parse all rows and return a list of PrintJob objects.

        Rows where both name and code are empty are silently skipped.

        Returns:
            List of PrintJob instances.
        """
        jobs: List[PrintJob] = []

        for idx, row in self.df.iterrows():
            job = self._row_to_printjob(row)
            if job is None:
                continue
            jobs.append(job)

        logger.info(f"Parsed {len(jobs)} print jobs from Excel")
        return jobs

    def _row_to_printjob(self, row: pd.Series) -> Optional[PrintJob]:
        """
        Convert a single DataFrame row to a PrintJob.

        Args:
            row: A pandas Series representing one spreadsheet row.

        Returns:
            PrintJob instance, or None if the row has no name or code.
        """
        kwargs: dict = {}

        for header, field_name in COLUMN_TO_FIELD.items():
            if header in row.index:
                kwargs[field_name] = _clean(row[header])
            else:
                kwargs[field_name] = None

        name = kwargs.get("name")
        code = kwargs.get("code")

        if not name and not code:
            # Completely empty row – skip silently.
            return None

        if not name:
            logger.warning(f"Row with code '{code}' has no name – skipping")
            return None

        if not code:
            logger.warning(f"Row with name '{name}' has no code – skipping")
            return None

        return PrintJob(**kwargs)
