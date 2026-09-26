"""
Checker for the 2PP print protocol.

Validates the data read by :func:`excel.excel_reader.read_protocol` and
returns every problem as an :class:`~checks.issues.Issue`. Never corrects
anything. Rows with ``openBIS upload = No`` are ignored.

Online checks (do the referenced objects exist in openBIS?) run only when a
``permid_lookup`` callable is given; the CLI passes one that queries openBIS.
"""

import re
from collections import defaultdict
from datetime import date
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from checks.issues import CheckResult, Issue, Level, Stage
from excel.column_mapping import (
    SHEET_IMAGING,
    SHEET_PRINTJOBS,
    column_by_field,
)
from excel.excel_reader import ProtocolData
from models.cell import CellValue
from models.imaging import SAMPLE_STATE_SINTERED, SAMPLE_STATES, ImagingEvent
from models.printjob import PRINT_STATUSES, PrintJob
from models.run import StepKind, group_runs, run_ids_by_kind

#: Returns the subset of the given permIds that exist in openBIS.
PermIdLookup = Callable[[Set[str]], Set[str]]

#: Returns the term codes of a controlled vocabulary.
VocabularyLookup = Callable[[str], Set[str]]

#: Vocabulary of the mandatory SAMPLE property ``bam_oe``.
BAM_OE_VOCABULARY = "BAM_OE"

#: Text the Lists lookup formulas return for a name that is not in the Lists sheet.
NOT_IN_LIST = "NOT IN LIST"

#: openBIS permId, e.g. ``20210101000000000-12345``.
PERMID_PATTERN = re.compile(r"^\d{17}-\d+$")

#: Characters allowed in an openBIS code (codes are uppercased before the check).
CODE_PATTERN = re.compile(r"^[A-Z0-9_.\-]+$")

REQUIRED_PRINT_FIELDS = [
    "print_date",
    "print_operator",
    "design",
    "resin_name",
    "resin_permid",
    "substrate_permid",
    "objective",
]

#: Fields required once the step date is filled (the date itself is the trigger).
REQUIRED_STEP_FIELDS: Dict[StepKind, List[str]] = {
    StepKind.WASHING: ["washing_run_id", "washing_operator", "washing_solvent"],
    StepKind.CPD: ["cpd_run_id", "cpd_operator"],
    StepKind.SINTERING: [
        "sintering_run_id",
        "sintering_operator",
        "furnace_name",
        "furnace_permid",
    ],
}

REQUIRED_IMAGING_FIELDS = ["technique", "sample_state", "imaging_date", "imaging_operator"]

#: Formula columns that are never empty once their inputs are filled. An empty
#: value with filled inputs proves the file was not recalculated by Excel.
#: (Lookup formulas like Resin permId are not usable: they return an empty
#: value when the Lists entry has no permId.)
CACHE_PROBES: List[Tuple[str, List[str]]] = [
    ("print_name", ["print_date", "design"]),
    ("z_height_um", ["z_start_um", "z_end_um"]),
    ("x_width_um", ["x_start_um", "x_end_um"]),
    ("y_depth_um", ["y_start_um", "y_end_um"]),
]

_UPLOAD_VALUES = {"yes", "no"}


def _header(sheet: str, field: str) -> str:
    """Excel header of *field* in *sheet*."""
    return column_by_field(sheet, field).header


def _code(value: CellValue) -> Optional[str]:
    """Print code as text for issue grouping."""
    return None if value is None else str(value)


class Checker:
    """Runs all checks on one :class:`ProtocolData`."""

    def __init__(
        self,
        data: ProtocolData,
        printer_permid: Optional[str] = None,
        permid_lookup: Optional[PermIdLookup] = None,
        bam_oe: Optional[str] = None,
        vocabulary_lookup: Optional[VocabularyLookup] = None,
    ) -> None:
        """
        Args:
            data: Workbook content from the Excel reader.
            printer_permid: Printer permId from settings (checked if given).
            permid_lookup: Online existence check; None = offline mode.
            bam_oe: ``properties.bam_oe`` from settings (checked online if given).
            vocabulary_lookup: Online vocabulary terms; None = offline mode.
        """
        self.data = data
        self.printer_permid = printer_permid
        self.permid_lookup = permid_lookup
        self.bam_oe = bam_oe
        self.vocabulary_lookup = vocabulary_lookup
        self.result = CheckResult()

    # ── Entry point ─────────────────────────────────────────────────────────

    def run(self) -> CheckResult:
        """Run every check and return the result."""
        self._check_structure()
        if self.result.fatal:
            return self.result
        self._check_formula_cache()
        self._check_printer()
        self._check_bam_oe()
        if self.result.fatal:
            return self.result

        prints = [p for p in self.data.prints if not p.upload_disabled]
        imaging = [e for e in self.data.imaging if not e.upload_disabled]

        self._check_print_codes_unique()
        for job in prints:
            self._check_print(job)
        for job in prints:
            if not job.is_failed:
                self._check_steps_of_print(job)
        self._check_run_ids_across_steps(prints)
        for kind in StepKind:
            self._check_run_consistency(prints, kind)
        self._check_same_substrate_dates(prints)

        for event in imaging:
            self._check_imaging_row(event)
        self._check_imaging_unique(imaging)

        if self.permid_lookup is not None:
            self._check_permids_exist(prints, imaging)
        return self.result

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _add(
        self,
        level: Level,
        stage: Stage,
        message: str,
        sheet: Optional[str] = None,
        row: Optional[int] = None,
        field: Optional[str] = None,
        print_code: CellValue = None,
        blocking: Optional[bool] = None,
    ) -> None:
        """Record one issue; *field* is translated to its Excel header."""
        column = _header(sheet, field) if sheet and field else None
        self.result.issues.append(
            Issue(level, stage, message, sheet, row, column, _code(print_code), blocking)
        )

    def _print_error(self, job: PrintJob, stage: Stage, field: Optional[str], message: str) -> None:
        """ERROR on a PrintJobs row."""
        self._add(Level.ERROR, stage, message, SHEET_PRINTJOBS, job.row, field, job.print_code)

    def _is_blocked(self, job: PrintJob, stage: Stage) -> bool:
        """True if an earlier check blocks *job* at *stage* or before."""
        blocked = self.result.blocked_from(SHEET_PRINTJOBS, job.row)
        return blocked is not None and blocked <= stage

    def _check_permid_value(
        self, job_or_event, sheet: str, stage: Stage, field: str, what: str, name_field: str
    ) -> None:
        """ERROR if a permId cell holds ``NOT IN LIST`` or is not a permId."""
        value = getattr(job_or_event, field)
        if value is None:
            return
        if value == NOT_IN_LIST:
            name = getattr(job_or_event, name_field)
            message = f"{what} '{name}' is not in the Lists sheet."
        elif not PERMID_PATTERN.match(str(value)):
            message = f"'{value}' is not a valid openBIS permId."
        else:
            return
        self._add(Level.ERROR, stage, message, sheet, job_or_event.row, field,
                  job_or_event.print_code)

    # ── File / structure ────────────────────────────────────────────────────

    def _check_structure(self) -> None:
        """Required sheets and headers present, headers not duplicated."""
        for sheet in self.data.missing_sheets:
            self._add(Level.ERROR, Stage.FILE, f"Required sheet '{sheet}' is missing.")
        for sheet, headers in self.data.missing_headers.items():
            for header in headers:
                self.result.issues.append(Issue(
                    Level.ERROR, Stage.FILE, "Required column is missing in row 2.",
                    sheet, None, header))
        for sheet, headers in self.data.duplicate_headers.items():
            for header in headers:
                self.result.issues.append(Issue(
                    Level.ERROR, Stage.FILE, "Column header appears more than once in row 2.",
                    sheet, None, header))
        for sheet, rows in self.data.rows_without_key.items():
            for row in rows:
                self._add(Level.WARNING, Stage.FILE,
                          "Row has values but no Print code; it is ignored.",
                          sheet, row, "print_code")

    def _check_formula_cache(self) -> None:
        """Formula columns must have cached values (file saved by Excel)."""
        for job in self.data.prints:
            for target, inputs in CACHE_PROBES:
                if getattr(job, target) is None and all(getattr(job, f) is not None for f in inputs):
                    self._add(
                        Level.ERROR, Stage.FILE,
                        "Formula column is empty although its inputs are filled: the file was "
                        "not recalculated. Open it in Excel, save it, and run again.",
                        SHEET_PRINTJOBS, job.row, target,
                    )
                    return  # one message is enough

    def _check_printer(self) -> None:
        """Printer permId from settings is a permId."""
        if self.printer_permid is not None and not PERMID_PATTERN.match(self.printer_permid):
            self._add(Level.ERROR, Stage.FILE,
                      f"'printer.permid' ('{self.printer_permid}') is not a valid openBIS permId.")

    def _check_bam_oe(self) -> None:
        """Online: ``bam_oe`` from settings is a term of the BAM_OE vocabulary."""
        if self.bam_oe is None or self.vocabulary_lookup is None:
            return
        if self.bam_oe not in self.vocabulary_lookup(BAM_OE_VOCABULARY):
            self._add(Level.ERROR, Stage.FILE,
                      f"'properties.bam_oe' ('{self.bam_oe}') is not a term of the openBIS "
                      f"vocabulary {BAM_OE_VOCABULARY}; no sample could be saved.")

    # ── PrintJobs: print ────────────────────────────────────────────────────

    def _check_print_codes_unique(self) -> None:
        """Print code unique over all rows (also rows with openBIS upload = No)."""
        rows_by_code: Dict[str, List[int]] = defaultdict(list)
        for job in self.data.prints:
            rows_by_code[str(job.print_code)].append(job.row)
        for job in self.data.prints:
            rows = rows_by_code[str(job.print_code)]
            if len(rows) > 1 and not job.upload_disabled:
                others = ", ".join(str(r) for r in rows if r != job.row)
                self._print_error(job, Stage.PRINT, "print_code",
                                  f"Print code '{job.print_code}' is also used in row(s) {others}.")

    def _check_print(self, job: PrintJob) -> None:
        """Required columns, print status, permId cells and dates of one print."""
        self._check_upload_value(job, SHEET_PRINTJOBS, Stage.PRINT)
        if not CODE_PATTERN.match(job.print_step_code):
            self._print_error(job, Stage.PRINT, "print_code",
                              f"'{job.print_code}' cannot be used in an openBIS code "
                              f"(allowed: letters, digits, _ - .).")
        for field in REQUIRED_PRINT_FIELDS:
            if getattr(job, field) is None:
                self._print_error(job, Stage.PRINT, field, "Required value is empty.")

        if job.print_status is None:
            self._add(Level.WARNING, Stage.PRINT,
                      "Print status is empty. Fill it in (OK / Partial / Failed) and run again.",
                      SHEET_PRINTJOBS, job.row, "print_status", job.print_code, blocking=True)
        elif job.print_status not in PRINT_STATUSES:
            self._print_error(job, Stage.PRINT, "print_status",
                              f"'{job.print_status}' is not one of {', '.join(PRINT_STATUSES)}.")

        if job.print_date is not None and not isinstance(job.print_date, date):
            self._print_error(job, Stage.PRINT, "print_date",
                              f"'{job.print_date}' is not a date.")

        self._check_permid_value(job, SHEET_PRINTJOBS, Stage.PRINT, "resin_permid",
                                 "Resin", "resin_name")
        self._check_permid_value(job, SHEET_PRINTJOBS, Stage.PRINT, "substrate_permid",
                                 "Substrate", "substrate_name")

        if job.is_failed and any(job.step(kind).exists for kind in StepKind):
            self._add(Level.WARNING, Stage.WASHING,
                      "Print status is Failed: the post-processing values of this row are ignored.",
                      SHEET_PRINTJOBS, job.row, "print_status", job.print_code)

    def _check_upload_value(self, row_obj, sheet: str, stage: Stage) -> None:
        """``openBIS upload`` must be empty, Yes or No."""
        value = row_obj.openbis_upload
        if value is not None and str(value).strip().lower() not in _UPLOAD_VALUES:
            self._add(Level.ERROR, stage, f"'{value}' is not Yes or No (empty = Yes).",
                      sheet, row_obj.row, "openbis_upload", row_obj.print_code)

    # ── PrintJobs: post-processing ──────────────────────────────────────────

    def _check_steps_of_print(self, job: PrintJob) -> None:
        """Per print: required step values, run ID prefix, sequence and date order."""
        previous_date: CellValue = job.print_date
        previous_label = "Print date"
        for kind in StepKind:
            stage = Stage.of(kind)
            entry = job.step(kind)
            date_field = f"{kind.key}_date"
            if not entry.exists:
                if entry.run_id is not None:
                    self._print_error(job, stage, f"{kind.key}_run_id",
                                      "Run ID is filled but the date is empty.")
                continue

            for field in REQUIRED_STEP_FIELDS[kind]:
                if getattr(job, field) is None:
                    self._print_error(job, stage, field,
                                      "Required once the step date is filled; value is empty.")

            if entry.run_id is not None and not (
                str(entry.run_id).startswith(kind.run_prefix)
                and len(str(entry.run_id)) > len(kind.run_prefix)
            ):
                self._print_error(job, stage, f"{kind.key}_run_id",
                                  f"Run ID '{entry.run_id}' must start with '{kind.run_prefix}'.")
            elif entry.run_id is not None and not CODE_PATTERN.match(str(entry.run_id).upper()):
                self._print_error(job, stage, f"{kind.key}_run_id",
                                  f"Run ID '{entry.run_id}' cannot be used in an openBIS code "
                                  f"(allowed: letters, digits, _ - .).")

            if kind is StepKind.SINTERING:
                self._check_permid_value(job, SHEET_PRINTJOBS, stage, "furnace_permid",
                                         "Furnace", "furnace_name")

            previous = kind.previous
            if previous is not None and not job.step(previous).exists:
                self._print_error(
                    job, stage, date_field,
                    f"{kind.section} date is filled but {previous.section} date is empty "
                    f"(order is Washing -> Drying (CPD) -> Sintering).")

            if not isinstance(entry.date, date):
                self._print_error(job, stage, date_field, f"'{entry.date}' is not a date.")
            elif isinstance(previous_date, date) and entry.date < previous_date:
                self._print_error(
                    job, stage, date_field,
                    f"{_header(SHEET_PRINTJOBS, date_field)} {entry.date} is before "
                    f"{previous_label} {previous_date}.")
            previous_date = entry.date
            previous_label = _header(SHEET_PRINTJOBS, date_field)

    def _check_run_ids_across_steps(self, prints: List[PrintJob]) -> None:
        """A run ID must not be used for two different steps."""
        by_row = {job.row: job for job in prints if not job.is_failed}
        for run_id, uses in run_ids_by_kind(by_row.values()).items():
            kinds = {kind for kind, _ in uses}
            if len(kinds) < 2:
                continue
            names = " and ".join(k.section for k in StepKind if k in kinds)
            for kind, row in uses:
                self._print_error(by_row[row], Stage.of(kind), f"{kind.key}_run_id",
                                  f"Run ID '{run_id}' is used for {names}.")

    def _check_run_consistency(self, prints: List[PrintJob], kind: StepKind) -> None:
        """All prints of one run must have identical values in the step's own columns."""
        stage = Stage.of(kind)
        members = [
            job for job in prints
            if not job.is_failed and job.step(kind).exists and not self._is_blocked(job, stage)
        ]
        for run in group_runs(members, kind).values():
            mismatched = run.mismatched_fields()
            if not mismatched:
                continue
            headers = ", ".join(_header(SHEET_PRINTJOBS, f) for f in mismatched)
            rows = ", ".join(str(r) for r in run.rows)
            for entry in run.entries:
                self._add(Level.ERROR, stage,
                          f"Run '{run.run_id}' (rows {rows}) has different values in: {headers}. "
                          f"The whole run is not uploaded.",
                          SHEET_PRINTJOBS, entry.row, f"{kind.key}_run_id", entry.print_code)

    def _check_same_substrate_dates(self, prints: List[PrintJob]) -> None:
        """WARNING: prints on the same substrate with different step dates."""
        by_substrate: Dict[str, List[PrintJob]] = defaultdict(list)
        for job in prints:
            if not job.is_failed and job.substrate_permid is not None:
                by_substrate[str(job.substrate_permid)].append(job)
        for substrate, jobs in by_substrate.items():
            for kind in StepKind:
                dated = [(job, job.step(kind).date) for job in jobs if job.step(kind).exists]
                if len({d for _, d in dated}) < 2:
                    continue
                details = ", ".join(f"row {job.row}: {d}" for job, d in dated)
                self._add(Level.WARNING, Stage.of(kind),
                          f"Prints on substrate {substrate} have different {kind.section} dates "
                          f"({details}). Allowed, but often a copy error.",
                          SHEET_PRINTJOBS, dated[0][0].row, f"{kind.key}_date",
                          dated[0][0].print_code)

    # ── Imaging ─────────────────────────────────────────────────────────────

    def _imaging_error(self, event: ImagingEvent, field: Optional[str], message: str) -> None:
        """ERROR on an Imaging row."""
        self._add(Level.ERROR, Stage.IMAGING, message, SHEET_IMAGING, event.row, field,
                  event.print_code)

    def _check_imaging_row(self, event: ImagingEvent) -> None:
        """Print reference, required values, sample state and instrument of one row."""
        self._check_upload_value(event, SHEET_IMAGING, Stage.IMAGING)
        if event.print_code is None:
            self._imaging_error(event, "print_code", "Required value is empty.")
        else:
            job = self._print_by_code(event.print_code)
            if job is None:
                self._imaging_error(event, "print_code",
                                    f"Print code '{event.print_code}' is not in PrintJobs.")
            elif job.upload_disabled:
                self._add(Level.WARNING, Stage.IMAGING,
                          f"Print '{event.print_code}' has openBIS upload = No.",
                          SHEET_IMAGING, event.row, "print_code", event.print_code, blocking=True)
            elif job.is_failed:
                self._imaging_error(event, "print_code",
                                    f"Print '{event.print_code}' has status Failed (no sample).")
            elif event.sample_state == SAMPLE_STATE_SINTERED and not job.step(StepKind.SINTERING).exists:
                self._imaging_error(event, "sample_state",
                                    f"Sample state is Sintered but print '{event.print_code}' "
                                    f"has no sintering date.")

        for field in REQUIRED_IMAGING_FIELDS:
            if getattr(event, field) is None:
                self._imaging_error(event, field, "Required value is empty.")
        if event.sample_state is not None and event.sample_state not in SAMPLE_STATES:
            self._imaging_error(event, "sample_state",
                                f"'{event.sample_state}' is not one of {', '.join(SAMPLE_STATES)}.")
        if event.imaging_date is not None and not isinstance(event.imaging_date, date):
            self._imaging_error(event, "imaging_date", f"'{event.imaging_date}' is not a date.")
        self._check_permid_value(event, SHEET_IMAGING, Stage.IMAGING, "instrument_permid",
                                 "Technique", "technique")
        if (None not in event.identity and isinstance(event.imaging_date, date)
                and not CODE_PATTERN.match(event.code)):
            self._imaging_error(event, "technique",
                                f"Code '{event.code}' is not a valid openBIS code (allowed: "
                                f"letters, digits, _ - .); check Print code and Technique.")

    def _print_by_code(self, print_code: CellValue) -> Optional[PrintJob]:
        """First PrintJobs row with *print_code* (duplicates are reported separately)."""
        for job in self.data.prints:
            if str(job.print_code) == str(print_code):
                return job
        return None

    def _check_imaging_unique(self, imaging: List[ImagingEvent]) -> None:
        """(Print code, Technique, Sample state, Imaging date) unique."""
        rows_by_identity: Dict[tuple, List[int]] = defaultdict(list)
        for event in imaging:
            if None not in event.identity:
                rows_by_identity[event.identity].append(event.row)
        for event in imaging:
            rows = rows_by_identity.get(event.identity, [])
            if len(rows) > 1:
                others = ", ".join(str(r) for r in rows if r != event.row)
                self._imaging_error(
                    event, None,
                    f"Same print code, technique, sample state and imaging date as row(s) "
                    f"{others}: this would give the same openBIS code.")

    # ── Online ──────────────────────────────────────────────────────────────

    def _check_permids_exist(self, prints: List[PrintJob], imaging: List[ImagingEvent]) -> None:
        """Every referenced permId exists in openBIS."""
        # (sheet or None, row, field, print code, stage, kind label, permId)
        references: List[Tuple[Optional[str], Optional[int], Optional[str], CellValue, Stage, str, str]] = []
        if self.printer_permid:
            references.append((None, None, None, None, Stage.FILE, "printer", self.printer_permid))
        for job in prints:
            refs = [("resin_permid", Stage.PRINT, "resin"), ("substrate_permid", Stage.PRINT, "substrate")]
            if not job.is_failed and job.step(StepKind.SINTERING).exists:
                refs.append(("furnace_permid", Stage.SINTERING, "furnace"))
            for field, stage, label in refs:
                references.append((SHEET_PRINTJOBS, job.row, field, job.print_code, stage, label,
                                   getattr(job, field)))
        for event in imaging:
            references.append((SHEET_IMAGING, event.row, "instrument_permid", event.print_code,
                               Stage.IMAGING, "instrument", event.instrument_permid))

        valid = [r for r in references if r[6] is not None and PERMID_PATTERN.match(str(r[6]))]
        existing = self.permid_lookup({str(r[6]) for r in valid})
        for sheet, row, field, print_code, stage, label, permid in valid:
            if str(permid) not in existing:
                self._add(Level.ERROR, stage, f"Parent {label} {permid} does not exist in openBIS.",
                          sheet, row, field, print_code)


def check_protocol(
    data: ProtocolData,
    printer_permid: Optional[str] = None,
    permid_lookup: Optional[PermIdLookup] = None,
    bam_oe: Optional[str] = None,
    vocabulary_lookup: Optional[VocabularyLookup] = None,
) -> CheckResult:
    """
    Run all checks on *data*.

    Args:
        data: Workbook content from the Excel reader.
        printer_permid: Printer permId from settings (format and, online, existence).
        permid_lookup: Returns which permIds exist in openBIS; None = offline.
        bam_oe: ``properties.bam_oe`` from settings.
        vocabulary_lookup: Returns the terms of a vocabulary; None = offline.

    Returns:
        The :class:`CheckResult`; issues are in check order.
    """
    return Checker(data, printer_permid, permid_lookup, bam_oe, vocabulary_lookup).run()


def sorted_issues(issues: Iterable[Issue]) -> List[Issue]:
    """Issues ordered for the report: file/settings first, then by sheet and row."""
    sheet_order = {None: 0, SHEET_PRINTJOBS: 1, SHEET_IMAGING: 2}
    return sorted(
        issues,
        key=lambda i: (i.stage is not Stage.FILE, sheet_order.get(i.sheet, 3), i.row or 0),
    )
