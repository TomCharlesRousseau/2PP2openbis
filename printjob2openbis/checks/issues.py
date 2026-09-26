"""
Issues reported by the checker, and the result object the uploader reads.

Every issue names the sheet, row and column it is about. ``stage`` says which
part of a print's workflow it blocks: an issue at stage WASHING blocks washing
and every later step of that print (CPD, sintering, sintered sample, imaging).
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional

from models.run import StepKind


class Level(str, Enum):
    """Severity of an issue."""

    ERROR = "ERROR"
    WARNING = "WARNING"


class Stage(IntEnum):
    """Workflow stage an issue belongs to, in upload order."""

    FILE = 0
    PRINT = 1
    WASHING = 2
    CPD = 3
    SINTERING = 4
    IMAGING = 5

    @classmethod
    def of(cls, kind: StepKind) -> "Stage":
        """Stage of a post-processing step kind."""
        return cls[kind.name]


@dataclass
class Issue:
    """
    One problem found in the workbook.

    Attributes:
        level: ERROR or WARNING.
        stage: Workflow stage the issue blocks (if ``blocking``).
        message: Human-readable explanation.
        sheet: Sheet name, or None for problems outside the workbook (settings).
        row: Excel row (1-based), or None for sheet-level problems.
        column: Header of the column concerned, if any.
        print_code: Print the issue belongs to (PrintJobs rows and Imaging rows).
        blocking: True if the object (and later steps) must not be uploaded.
            Defaults to True for ERROR, False for WARNING.
    """

    level: Level
    stage: Stage
    message: str
    sheet: Optional[str] = None
    row: Optional[int] = None
    column: Optional[str] = None
    print_code: Optional[str] = None
    blocking: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.blocking is None:
            self.blocking = self.level is Level.ERROR

    @property
    def location(self) -> str:
        """``Sheet row N, 'Column'`` (parts omitted when unknown)."""
        parts = [self.sheet or "settings"]
        if self.row is not None:
            parts.append(f"row {self.row}")
        text = " ".join(parts)
        if self.column:
            text += f", '{self.column}'"
        return text

    def __str__(self) -> str:
        suffix = " (not uploaded)" if self.blocking and self.level is Level.WARNING else ""
        return f"{self.level.value:<7} {self.location}: {self.message}{suffix}"


@dataclass
class CheckResult:
    """All issues of one check run, with the queries the uploader needs."""

    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        """Issues of level ERROR."""
        return [i for i in self.issues if i.level is Level.ERROR]

    @property
    def warnings(self) -> List[Issue]:
        """Issues of level WARNING."""
        return [i for i in self.issues if i.level is Level.WARNING]

    @property
    def fatal(self) -> bool:
        """True if a file-level problem blocks the whole upload."""
        return any(i.blocking and i.stage is Stage.FILE for i in self.issues)

    def blocked_from(self, sheet: str, row: int) -> Optional[Stage]:
        """
        Earliest blocked stage of one row, or None if nothing is blocked.

        For a PrintJobs row, everything from the returned stage onwards is
        skipped. Does not include file-level problems (see :attr:`fatal`).
        """
        stages = [
            i.stage for i in self.issues if i.blocking and i.sheet == sheet and i.row == row
        ]
        return min(stages) if stages else None
