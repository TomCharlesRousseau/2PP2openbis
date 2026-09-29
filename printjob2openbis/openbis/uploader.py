"""
Upload of the checked protocol to openBIS.

Order: 3DPoli job objects → print steps → printed samples → washing → CPD →
sintering → sintered samples → imaging. Each level needs the permIds of the previous one.

Washing / CPD / sintering steps are shared per run ID. Their parents are
collected per print (printed sample → washing step → CPD step) and
de-duplicated; a run whose creation fails blocks all of its prints.

- 3DPoli job objects get their job file as a ``RAW_DATA`` dataset, without duplicates
  (compared by size and CRC32 with the files already stored).
- Rows with ``openBIS upload = No`` and rows blocked by the checker are skipped.
- A print that fails at one stage is blocked for every later stage.
- Existing code → skipped; missing parent links are added (never removed).
- With ``update``: properties of existing objects that differ from the Excel
  are overwritten (empty Excel cells never clear a stored value).

Every object touched is recorded in :attr:`UploadStats.records`;
:func:`write_report` saves them as a CSV ``code → permId`` report.
"""

import csv
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from checks.issues import CheckResult, Stage
from excel.column_mapping import SHEET_IMAGING, SHEET_PRINTJOBS
from excel.excel_reader import ProtocolData
from models.imaging import SAMPLE_STATE_SINTERED, ImagingEvent
from models.printjob import PrintJob
from models.run import StepKind, group_runs
from openbis import object_builders
from openbis.object_manager import ExistingObject, NewObject, ObjectManager
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class UploadConfig:
    """
    Values from settings needed by the upload.

    Attributes:
        printer_permid: Printer, parent of every print step.
        bam_oe: Mandatory ``bam_oe`` of every sample.
        collection_paths: Collection group (``printjobs``, ``samples`` …) → path.
    """

    printer_permid: str
    bam_oe: str
    collection_paths: Dict[str, str]


@dataclass
class ReportRow:
    """One object in the end report."""

    code: str
    type_code: str
    permid: str
    status: str  # created / would create / existing [+ updated] [+ linked] [+ dataset] / error
    origin: str  # Excel rows the object comes from


REPORT_COLUMNS = ["code", "type", "permId", "status", "origin"]


@dataclass
class UploadStats:
    """Counts for the end report (in dry-run: what would happen)."""

    created: int = 0
    skipped: int = 0
    updated: int = 0
    linked: int = 0
    datasets: int = 0
    errors: int = 0
    permids: Dict[str, str] = field(default_factory=dict)  # code → permId
    records: List[ReportRow] = field(default_factory=list)

    def summary(self, dry_run: bool = False) -> str:
        """One-line summary; in dry-run worded as what would happen."""
        created, updated, linked, uploaded = (
            ("would be created", "would be updated", "would get new parent links",
             "would be uploaded") if dry_run
            else ("created", "updated", "got new parent links", "uploaded"))
        return (f"{self.created} {created}, {self.skipped} already existed (skipped), "
                f"{self.updated} {updated}, {self.linked} {linked}, "
                f"{self.datasets} dataset(s) {uploaded}, {self.errors} error(s).")


class Uploader:
    """Creates the objects of one protocol in openBIS."""

    def __init__(self, manager: ObjectManager, config: UploadConfig, data: ProtocolData,
                 check: CheckResult, update: bool = False) -> None:
        """
        Args:
            manager: openBIS gateway (in dry-run mode it does not write).
            config: Settings values.
            data: Workbook content.
            check: Result of the checker on *data* (must not be fatal).
            update: Overwrite differing properties of existing objects.
        """
        if check.fatal:
            raise ValueError("The check found a file-level error; nothing may be uploaded.")
        self.manager = manager
        self.config = config
        self.data = data
        self.check = check
        self.update = update
        self.stats = UploadStats()
        self._upload_failed: Dict[int, Stage] = {}  # PrintJobs row → earliest failed stage

    # ── Entry point ─────────────────────────────────────────────────────────

    def run(self) -> UploadStats:
        """Upload everything the check allows; return the counts."""
        missing = self.manager.missing_collections(self.config.collection_paths.values())
        if missing:
            for path in missing:
                logger.error(f"Collection {path} does not exist in openBIS. Nothing uploaded.")
            self.stats.errors += len(missing)
            return self.stats

        prints = [job for job in self.data.prints if not job.upload_disabled]
        imaging = [event for event in self.data.imaging
                   if not event.upload_disabled
                   and self.check.blocked_from(SHEET_IMAGING, event.row) is None]
        existing = self.manager.find_existing(
            self._candidate_codes(prints) + [event.code for event in imaging])

        self._upload_poli_jobs(prints, existing)
        self._upload_print_steps(prints, existing)
        self._upload_printed_samples(prints, existing)
        for kind in StepKind:
            self._upload_runs(prints, kind, existing)
        self._upload_sintered_samples(prints, existing)
        self._upload_imaging(imaging, existing)
        return self.stats

    @staticmethod
    def _candidate_codes(prints: List[PrintJob]) -> List[str]:
        """Every code this upload may create (looked up in one batch beforehand)."""
        codes: List[str] = []
        for job in prints:
            if job.poli_job_code is not None:
                codes.append(job.poli_job_code)
            codes.append(job.print_step_code)
            if job.is_failed:
                continue
            codes.append(job.printed_sample_code)
            for kind in StepKind:
                run_code = job.run_code(kind)
                if run_code is not None:
                    codes.append(run_code)
            if job.step(StepKind.SINTERING).exists:
                codes.append(job.sintered_sample_code)
        return codes

    # ── Levels ──────────────────────────────────────────────────────────────

    def _upload_poli_jobs(self, prints: List[PrintJob],
                          existing: Dict[str, ExistingObject]) -> None:
        """One SAMPLE per distinct 3DPoli job file; a failure blocks every print using it."""
        by_code: Dict[str, List[PrintJob]] = {}
        for job in prints:
            if job.poli_job_code is not None and not self._blocked(job, Stage.PRINT):
                by_code.setdefault(job.poli_job_code, []).append(job)
        for jobs in by_code.values():
            new = object_builders.poli_job(jobs[0], self.config.collection_paths["poli"])
            permid = self._ensure(new, existing, jobs, Stage.PRINT)
            if permid is not None:
                self._upload_job_file(new, permid, created=new.code not in existing)

    def _upload_job_file(self, new: NewObject, permid: str, created: bool) -> None:
        """
        Upload the job file of a 3DPoli job object as a dataset, without duplicates.

        A new object always gets it. For an existing object the file is compared by
        size and CRC32 with every file of its datasets: same content → nothing to do;
        no file of that name → upload (e.g. an earlier upload failed); same name but
        other content → WARNING, uploaded only with ``update`` (old dataset kept).
        A failed upload is an error but does not block the prints.
        """
        path = new.dataset_files[0]
        if not created:
            try:
                data = path.read_bytes()
            except OSError as exc:
                logger.error(f"Job file of {new.code}: {exc}")
                self.stats.errors += 1
                self._mark(new.code, f"dataset error: {exc}")
                return
            size, crc = len(data), zlib.crc32(data)
            stored = self.manager.dataset_files(permid)
            if any(f.size == size and f.crc32 == crc for f in stored):
                return
            same_name = [f for f in stored if f.name == path.name]
            if any(f.crc32 is None for f in same_name):
                logger.warning(f"{new.code}: openBIS gives no checksum for {path.name}; "
                               f"cannot tell if the job file changed. Nothing uploaded.")
                return
            if same_name and not self.update:
                logger.warning(f"{new.code}: job file {path.name} changed since upload; "
                               f"run with --update to upload the new version.")
                return
            if same_name:
                logger.warning(f"{new.code}: job file {path.name} changed, uploading a new dataset.")
        try:
            self.manager.upload_dataset(permid, new.code, new.dataset_files)
        except (OSError, ValueError) as exc:
            logger.error(f"Dataset {path.name} of {new.code}: {exc}")
            self.stats.errors += 1
            self._mark(new.code, f"dataset error: {exc}")
            return
        self.stats.datasets += 1
        self._mark(new.code, "dataset")

    def _mark(self, code: str, text: str) -> None:
        """Append *text* to the report status of the last record of *code*."""
        for row in reversed(self.stats.records):
            if row.code == code:
                row.status += f" + {text}"
                return

    def _upload_print_steps(self, prints: List[PrintJob],
                            existing: Dict[str, ExistingObject]) -> None:
        """One EXPERIMENTAL_STEP per print (parent: its 3DPoli job object, if any)."""
        for job in prints:
            if self._blocked(job, Stage.PRINT):
                continue
            poli_permid = (self.stats.permids[job.poli_job_code]
                           if job.poli_job_code is not None else None)
            new = object_builders.print_step(
                job, self.config.collection_paths["printjobs"], self.config.printer_permid,
                poli_permid)
            self._ensure(new, existing, [job], Stage.PRINT)

    def _upload_printed_samples(self, prints: List[PrintJob],
                                existing: Dict[str, ExistingObject]) -> None:
        """One SAMPLE per print that is not Failed."""
        for job in prints:
            if job.is_failed or self._blocked(job, Stage.PRINT):
                continue
            step_permid = self.stats.permids[job.print_step_code]
            new = object_builders.printed_sample(
                job, self.config.collection_paths["samples"], step_permid, self.config.bam_oe)
            self._ensure(new, existing, [job], Stage.PRINT)

    def _previous_permid(self, job: PrintJob, kind: StepKind) -> str:
        """PermId of the object preceding *kind* for *job* (printed sample or previous run step)."""
        previous = kind.previous
        code = job.printed_sample_code if previous is None else job.run_code(previous)
        return self.stats.permids[code]

    def _upload_runs(self, prints: List[PrintJob], kind: StepKind,
                     existing: Dict[str, ExistingObject]) -> None:
        """One shared EXPERIMENTAL_STEP per run ID of *kind*."""
        stage = Stage.of(kind)
        members = [job for job in prints
                   if not job.is_failed and job.step(kind).exists and not self._blocked(job, stage)]
        by_row = {job.row: job for job in members}
        for run in group_runs(members, kind).values():
            jobs = [by_row[row] for row in run.rows]
            parents: List[str] = []
            for job in jobs:
                permid = self._previous_permid(job, kind)
                if permid not in parents:
                    parents.append(permid)
            if kind is StepKind.SINTERING:
                parents.append(str(jobs[0].furnace_permid))
            new = object_builders.run_step(
                run, jobs[0], self.config.collection_paths[kind.key], parents)
            self._ensure(new, existing, jobs, stage)

    def _upload_sintered_samples(self, prints: List[PrintJob],
                                 existing: Dict[str, ExistingObject]) -> None:
        """One SAMPLE per sintered print; parents: its sintering step + its printed sample."""
        for job in prints:
            if (job.is_failed or not job.step(StepKind.SINTERING).exists
                    or self._blocked(job, Stage.SINTERING)):
                continue
            new = object_builders.sintered_sample(
                job, self.config.collection_paths["samples"],
                self.stats.permids[job.run_code(StepKind.SINTERING)],
                self.stats.permids[job.printed_sample_code],
                self.config.bam_oe)
            self._ensure(new, existing, [job], Stage.SINTERING)

    def _upload_imaging(self, imaging: List[ImagingEvent],
                        existing: Dict[str, ExistingObject]) -> None:
        """One EXPERIMENTAL_STEP per Imaging row; parent = the imaged sample (+ instrument)."""
        prints_by_code: Dict[str, PrintJob] = {}
        for job in self.data.prints:
            prints_by_code.setdefault(str(job.print_code), job)
        for event in imaging:
            job = prints_by_code[str(event.print_code)]  # the checker guarantees it exists
            if self._blocked(job, Stage.IMAGING):
                logger.info(f"Imaging row {event.row}: print {job.print_code} is blocked by an "
                            f"earlier error. Skipping.")
                continue
            sample_code = (job.sintered_sample_code
                           if event.sample_state == SAMPLE_STATE_SINTERED
                           else job.printed_sample_code)
            new = object_builders.imaging_step(
                event, self.config.collection_paths["imaging"], self.stats.permids[sample_code])
            self._ensure(new, existing, [], Stage.IMAGING, origin=f"Imaging row {event.row}")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _blocked(self, job: PrintJob, stage: Stage) -> bool:
        """True if the checker or an earlier upload failure blocks *job* at *stage*."""
        stages = [s for s in (self.check.blocked_from(SHEET_PRINTJOBS, job.row),
                              self._upload_failed.get(job.row)) if s is not None]
        return bool(stages) and min(stages) <= stage

    def _fail(self, jobs: List[PrintJob], stage: Stage) -> None:
        """Count one error and block *jobs* from *stage* on."""
        self.stats.errors += 1
        for job in jobs:
            current = self._upload_failed.get(job.row)
            self._upload_failed[job.row] = stage if current is None else min(current, stage)

    def _ensure(self, new: NewObject, existing: Dict[str, ExistingObject],
                jobs: List[PrintJob], stage: Stage,
                origin: Optional[str] = None) -> Optional[str]:
        """
        Create *new*, or skip it if its code exists (adding missing parent links).

        Args:
            new: Object to create.
            existing: Objects found in openBIS, by code.
            jobs: Prints the object belongs to (several for a shared run step);
                all are blocked from *stage* on if it fails.
            stage: Stage of the object.
            origin: Where the object comes from, for log messages (default:
                the PrintJobs rows of *jobs*).

        Returns:
            The permId (placeholder in dry-run), or None on error.
        """
        origin = origin or "PrintJobs row(s) " + ", ".join(str(job.row) for job in jobs)
        found = existing.get(new.code)
        try:
            if found is not None:
                if found.type_code != new.type_code:
                    logger.error(f"{new.code} exists as {found.type_code}, expected "
                                 f"{new.type_code}. {origin} skipped.")
                    self._fail(jobs, stage)
                    self._record(new, found.permid, "error: exists with another type", origin)
                    return None
                logger.info(f"INFO: {new.type_code} {new.code} already exists. Skipping.")
                self.stats.skipped += 1
                status = ["existing"]
                if self.update:
                    changed = found.changed_properties(new.properties)
                    if changed:
                        self.manager.update_properties(found, changed)
                        self.stats.updated += 1
                        status.append("updated")
                if self.manager.add_parents(found, new.parents):
                    self.stats.linked += 1
                    status.append("linked")
                permid = found.permid
            else:
                permid = self.manager.create(new)
                self.stats.created += 1
                status = ["would create" if self.manager.dry_run else "created"]
        except ValueError as exc:  # openBIS rejected the write
            logger.error(f"{new.type_code} {new.code} ({origin}): {exc}")
            self._fail(jobs, stage)
            self._record(new, "", f"error: {exc}", origin)
            return None
        self.stats.permids[new.code] = permid
        self._record(new, permid, " + ".join(status), origin)
        return permid

    def _record(self, new: NewObject, permid: str, status: str, origin: str) -> None:
        """Add one row to the end report."""
        self.stats.records.append(ReportRow(new.code, new.type_code, permid, status, origin))


def write_report(stats: UploadStats, report_dir: Path, dry_run: bool) -> Path:
    """
    Save the end report as CSV (``code, type, permId, status, origin``).

    Args:
        stats: Result of :meth:`Uploader.run`.
        report_dir: Directory (created if missing; git-ignored).
        dry_run: Adds ``_dry-run`` to the file name (permIds of new objects are placeholders).

    Returns:
        Path of the written file.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = report_dir / f"upload_{stamp}{'_dry-run' if dry_run else ''}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(REPORT_COLUMNS)
        for row in stats.records:
            writer.writerow([row.code, row.type_code, row.permid, row.status, row.origin])
    return path
