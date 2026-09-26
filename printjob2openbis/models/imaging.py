"""
ImagingEvent model: one row of the Imaging sheet = one imaging step.

Field names match :data:`excel.column_mapping.IMAGING_COLUMNS`. All fields
hold raw cell values (see :mod:`models.cell`); nothing is validated here.
"""

from dataclasses import dataclass
from datetime import date
from typing import Tuple

from models.cell import CellValue, is_no

SAMPLE_STATE_GREEN = "Green"
SAMPLE_STATE_SINTERED = "Sintered"
SAMPLE_STATES = (SAMPLE_STATE_GREEN, SAMPLE_STATE_SINTERED)


@dataclass
class ImagingEvent:
    """One Imaging row. ``row`` is the Excel row number (1-based)."""

    row: int
    print_code: CellValue = None
    print_name: CellValue = None
    substrate_permid: CellValue = None
    technique: CellValue = None
    sample_state: CellValue = None
    imaging_date: CellValue = None
    imaging_operator: CellValue = None
    instrument_permid: CellValue = None
    image_folder: CellValue = None
    notes: CellValue = None
    openbis_upload: CellValue = None

    @property
    def upload_disabled(self) -> bool:
        """True if ``openBIS upload`` is ``No`` (row ignored)."""
        return is_no(self.openbis_upload)

    @property
    def identity(self) -> Tuple[CellValue, CellValue, CellValue, CellValue]:
        """(Print code, Technique, Sample state, Imaging date): must be unique, it defines the code."""
        return (self.print_code, self.technique, self.sample_state, self.imaging_date)

    @property
    def code(self) -> str:
        """
        Code of the imaging step, e.g. ``2PP_IMG_2PP-000001_LIMI_GREEN_20260320``.

        Raises:
            ValueError: If the imaging date is not a date (run the checker first).
        """
        if not isinstance(self.imaging_date, date):
            raise ValueError(
                f"Imaging row {self.row}: Imaging date is not a date ({self.imaging_date!r})"
            )
        stamp = self.imaging_date.strftime("%Y%m%d")
        return f"2PP_IMG_{self.print_code}_{self.technique}_{self.sample_state}_{stamp}".upper()
