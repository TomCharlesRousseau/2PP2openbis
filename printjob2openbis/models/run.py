"""
Post-processing steps (washing, CPD, sintering) and runs.

A :class:`StepEntry` is one print's view of one step (the values of that
step's columns in one PrintJobs row). A :class:`Run` groups the entries that
share a run ID; it becomes one shared EXPERIMENTAL_STEP in openBIS.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from excel.column_mapping import (
    SECTION_CPD,
    SECTION_SINTERING,
    SECTION_WASHING,
    SHEET_PRINTJOBS,
    columns_in_section,
)
from models.cell import CellValue

if TYPE_CHECKING:
    from models.printjob import PrintJob


class StepKind(Enum):
    """Post-processing step, in the fixed order washing → CPD → sintering."""

    WASHING = ("washing", "WASH-", SECTION_WASHING)
    CPD = ("cpd", "CPD-", SECTION_CPD)
    SINTERING = ("sintering", "SINT-", SECTION_SINTERING)

    def __init__(self, key: str, run_prefix: str, section: str) -> None:
        self.key = key  # field prefix in PrintJob and collection key in settings
        self.run_prefix = run_prefix  # required prefix of the run ID
        self.section = section  # PrintJobs section holding the step's columns

    @property
    def previous(self) -> Optional["StepKind"]:
        """The step that must precede this one, or None for washing."""
        order = list(StepKind)
        index = order.index(self)
        return order[index - 1] if index > 0 else None

    @property
    def own_fields(self) -> List[str]:
        """PrintJob fields of this step other than date, run ID and operator, in sheet order."""
        fixed = {f"{self.key}_date", f"{self.key}_run_id", f"{self.key}_operator"}
        return [
            col.field
            for col in columns_in_section(SHEET_PRINTJOBS, self.section)
            if col.field not in fixed
        ]


@dataclass
class StepEntry:
    """
    One print's values for one post-processing step.

    Attributes:
        kind: Which step.
        print_code: Print code of the row.
        row: Excel row number (1-based).
        date: Step date; the step exists for this print only if it is filled.
        run_id: Run ID as typed in the Excel (stripped, case unchanged).
        operator: Operator of this step.
        attributes: The step's other columns (field → value), in sheet order.
    """

    kind: StepKind
    print_code: CellValue
    row: int
    date: CellValue
    run_id: CellValue
    operator: CellValue
    attributes: Dict[str, CellValue] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        """True if the step date is filled."""
        return self.date is not None

    def consistency_values(self) -> Dict[str, CellValue]:
        """Values that must be identical for all entries of one run (field → value)."""
        return {
            f"{self.kind.key}_date": self.date,
            f"{self.kind.key}_operator": self.operator,
            **self.attributes,
        }


@dataclass
class Run:
    """
    All entries sharing one run ID for one step kind.

    Attributes:
        kind: Which step.
        run_id: Run ID as typed in the Excel.
        entries: One entry per PrintJobs row carrying this run ID, in row order.
    """

    kind: StepKind
    run_id: str
    entries: List[StepEntry] = field(default_factory=list)

    @property
    def code(self) -> str:
        """openBIS code of the shared step, e.g. ``2PP_WASH-0012``."""
        return f"2PP_{self.run_id}".upper()

    @property
    def rows(self) -> List[int]:
        """Excel rows of the entries."""
        return [entry.row for entry in self.entries]

    @property
    def reference(self) -> StepEntry:
        """First entry; holds the run's date, operator and attributes once the run is consistent."""
        return self.entries[0]

    def mismatched_fields(self) -> List[str]:
        """
        Fields whose values differ between entries of the run.

        Returns:
            Field names in sheet order; empty if the run is consistent.
        """
        reference = self.reference.consistency_values()
        mismatched: List[str] = []
        for field_name, value in reference.items():
            if any(e.consistency_values()[field_name] != value for e in self.entries[1:]):
                mismatched.append(field_name)
        return mismatched

    def is_consistent(self) -> bool:
        """True if all entries have identical values in the step's own columns."""
        return not self.mismatched_fields()


def group_runs(prints: Iterable["PrintJob"], kind: StepKind) -> Dict[str, Run]:
    """
    Group the *kind* entries of *prints* by run ID.

    Entries without a run ID are ignored. The caller decides which prints take
    part (e.g. filter out ``openBIS upload = No``, Failed or erroneous prints
    before calling). Run IDs are compared exactly as typed (after stripping).

    Args:
        prints: Print jobs to group.
        kind: Step kind to group.

    Returns:
        Run ID → :class:`Run`, in order of first appearance.
    """
    runs: Dict[str, Run] = {}
    for job in prints:
        entry = job.step(kind)
        if entry.run_id is None:
            continue
        run_id = str(entry.run_id)
        runs.setdefault(run_id, Run(kind=kind, run_id=run_id)).entries.append(entry)
    return runs


def run_ids_by_kind(prints: Iterable["PrintJob"]) -> Dict[str, List[Tuple[StepKind, int]]]:
    """
    Map every run ID to the (step kind, row) pairs where it is used.

    Lets the checker find a run ID used for two different steps.

    Args:
        prints: Print jobs to scan.

    Returns:
        Run ID → list of (kind, Excel row).
    """
    usage: Dict[str, List[Tuple[StepKind, int]]] = {}
    for job in prints:
        for kind in StepKind:
            run_id = job.step(kind).run_id
            if run_id is not None:
                usage.setdefault(str(run_id), []).append((kind, job.row))
    return usage
