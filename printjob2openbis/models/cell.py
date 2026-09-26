"""
Cell value type shared by the models.

The Excel reader stores values with their native type: text is stripped,
empty cells become ``None``, dates become :class:`datetime.date` (or
:class:`datetime.datetime` when a time of day is present). Nothing else is
converted — validating types is the checker's job.
"""

from datetime import date, datetime
from typing import Optional, Union

CellValue = Optional[Union[str, int, float, bool, date, datetime]]


def is_no(value: CellValue) -> bool:
    """Return True if *value* is the text ``No`` (case-insensitive), e.g. in ``openBIS upload``."""
    return isinstance(value, str) and value.strip().lower() == "no"
