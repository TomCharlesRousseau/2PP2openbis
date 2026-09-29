"""Tests for the object builders and the uploader (fake openBIS, synthetic data)."""

import csv
import sys
import zlib
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from checks.checker import check_protocol
from excel.description_builder import (
    build_print_step_description,
    format_value,
    text_to_html,
    to_timestamp,
)
from excel.excel_reader import ProtocolData
from openbis import object_builders
from unittest.mock import MagicMock

import pandas as pd

from openbis.object_manager import DatasetFile, ExistingObject, NewObject, ObjectManager
from openbis.uploader import UploadConfig, Uploader, write_report
from tests.test_checker import INSTRUMENT, PRINTER, make_imaging, make_print
from tests.workbook_builder import (
    FAKE_FURNACE_PERMID,
    FAKE_RESIN_PERMID,
    FAKE_SUBSTRATE_PERMID,
)

PRINTJOBS = "/SPACE/PROJECT/PRINTJOBS"
SAMPLES = "/SPACE/PROJECT/SAMPLES"
CONFIG = UploadConfig(printer_permid=PRINTER, bam_oe="OE_1.1", collection_paths={
    "printjobs": PRINTJOBS, "samples": SAMPLES, "washing": "/SPACE/PROJECT/WASHING",
    "cpd": "/SPACE/PROJECT/CPD", "sintering": "/SPACE/PROJECT/SINTERING",
    "imaging": "/SPACE/PROJECT/IMAGING", "poli": "/SPACE/PROJECT/3DPOLI"})

NO_POST_PROCESSING = dict(
    washing_date=None, washing_run_id=None, cpd_date=None, cpd_run_id=None,
    sintering_date=None, sintering_run_id=None)


def print_only(row: int, code: str, **overrides):
    """A valid print without washing / CPD / sintering."""
    return make_print(row, code, **{**NO_POST_PROCESSING, **overrides})


class FakeManager:
    """Stands in for ObjectManager; records writes."""

    def __init__(self, existing: Dict[str, ExistingObject] = None,
                 reject: Iterable[str] = ()) -> None:
        self.existing = existing or {}
        self.reject = set(reject)
        self.dry_run = False
        self.created: List[NewObject] = []
        self.linked: Dict[str, List[str]] = {}
        self.updated: Dict[str, Dict[str, str]] = {}
        self.stored_files: Dict[str, List[DatasetFile]] = {}  # permId -> files in openBIS
        self.uploaded: List[tuple] = []  # (permId, code, file names)
        self.reject_upload = False

    def missing_collections(self, paths: Iterable[str]) -> List[str]:
        return []

    def find_existing(self, codes: Iterable[str]) -> Dict[str, ExistingObject]:
        return {c: self.existing[c] for c in codes if c in self.existing}

    def create(self, new: NewObject) -> str:
        if new.code in self.reject:
            raise ValueError("rejected by openBIS")
        self.created.append(new)
        return f"20210101000000000-{len(self.created):05d}"

    def update_properties(self, existing: ExistingObject, properties: Dict[str, str]) -> None:
        self.updated[existing.code] = properties

    def dataset_files(self, permid: str) -> List[DatasetFile]:
        return self.stored_files.get(permid, [])

    def upload_dataset(self, permid: str, code: str, files) -> None:
        if self.reject_upload:
            raise ValueError("upload rejected")
        self.uploaded.append((permid, code, [f.name for f in files]))

    def add_parents(self, existing: ExistingObject, parents: Iterable[str]) -> List[str]:
        missing = [p for p in parents if p not in existing.parent_permids]
        if missing:
            self.linked[existing.code] = missing
        return missing


def upload(prints, manager: FakeManager, update: bool = False, imaging=None):
    data = ProtocolData(file_path=Path("x.xlsx"), prints=prints, imaging=imaging or [])
    check = check_protocol(data, printer_permid=PRINTER)
    return Uploader(manager, CONFIG, data, check, update=update).run()


class TestFormatting(unittest.TestCase):

    def test_timestamp_midnight(self):
        self.assertEqual(to_timestamp(date(2026, 3, 20)), "2026-03-20 00:00:00")
        self.assertEqual(to_timestamp(datetime(2026, 3, 20, 9, 30)), "2026-03-20 09:30:00")

    def test_format_value(self):
        self.assertEqual(format_value(100.0), "100")
        self.assertEqual(format_value(0.3), "0.3")
        self.assertEqual(format_value(date(2026, 3, 20)), "2026-03-20")

    def test_print_description_sections(self):
        job = make_print(3, "2PP-000001", laser_power_mw=20.0, z_start_um=0, z_end_um=50)
        text = build_print_step_description(job)
        self.assertIn("<p><strong>General</strong><br>Print code: 2PP-000001<br>Design: Lattice", text)
        self.assertIn("<strong>Printer settings</strong><br>Objective: 63x<br>Laser power [mW]: 20", text)
        self.assertIn("<strong>Print geometry</strong><br>z start [µm]: 0<br>z end [µm]: 50</p>", text)
        # mapped to properties / parents, not repeated
        self.assertNotIn("Print operator", text)
        self.assertNotIn(FAKE_RESIN_PERMID, text)
        self.assertNotIn("Washing", text)  # post-processing belongs to the run steps


    def test_text_to_html_escapes_and_keeps_lines(self):
        self.assertEqual(text_to_html("a < b\nsecond & last"), "a &lt; b<br>second &amp; last")
        self.assertIsNone(text_to_html(None))


class TestBuilders(unittest.TestCase):

    def test_print_step(self):
        job = make_print(3, "2pp-000001", purpose="Test", comments="Note")
        new = object_builders.print_step(job, PRINTJOBS, PRINTER)
        self.assertEqual(new.code, "2PP-000001")
        self.assertEqual(new.type_code, "EXPERIMENTAL_STEP")
        self.assertEqual(new.parents, [PRINTER, FAKE_RESIN_PERMID, FAKE_SUBSTRATE_PERMID])
        props = new.properties
        self.assertEqual(props["start_date"], "2026-03-01 00:00:00")
        self.assertEqual(props["operator"], "Op A")
        self.assertEqual(props["experimental_step.experimental_goals"], "Test")
        self.assertEqual(props["experimental_step.experimental_results"], "OK")
        self.assertEqual(props["notes"], "Note")
        self.assertTrue(props["experimental_step.experimental_description"].startswith("<p>"))

    def test_printed_sample(self):
        new = object_builders.printed_sample(make_print(3, "2PP-000001"), SAMPLES,
                                             "20210101000000000-00001", "OE_1.1")
        self.assertEqual(new.code, "2PP_PRINTED_2PP-000001")
        self.assertEqual(new.properties["$name"], "2PP_PRINTED_2PP-000001")
        self.assertEqual(new.properties["bam_oe"], "OE_1.1")
        self.assertEqual(new.parents, ["20210101000000000-00001", FAKE_SUBSTRATE_PERMID])


class TestUploader(unittest.TestCase):

    def test_creates_step_then_sample(self):
        manager = FakeManager()
        stats = upload([print_only(3, "2PP-000001")], manager)
        self.assertEqual([n.code for n in manager.created],
                         ["2PP-000001", "2PP_PRINTED_2PP-000001"])
        self.assertEqual(manager.created[1].parents[0], stats.permids["2PP-000001"])
        self.assertEqual(stats.created, 2)

    def test_failed_print_gets_no_sample(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", print_status="Failed")], manager)
        self.assertEqual([n.code for n in manager.created], ["2PP-000001"])

    def test_blocked_and_disabled_rows_skipped(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", print_status=None),
                make_print(4, "2PP-000002", openbis_upload="No"),
                make_print(5, "2PP-000003", resin_permid="NOT IN LIST")], manager)
        self.assertEqual(manager.created, [])

    def test_existing_skipped_and_missing_parent_added(self):
        step = ExistingObject("2PP-000001", "20210101000000000-50001", "EXPERIMENTAL_STEP",
                              {PRINTER, FAKE_RESIN_PERMID})
        manager = FakeManager({"2PP-000001": step})
        stats = upload([print_only(3, "2PP-000001")], manager)
        self.assertEqual([n.code for n in manager.created], ["2PP_PRINTED_2PP-000001"])
        self.assertEqual(manager.linked, {"2PP-000001": [FAKE_SUBSTRATE_PERMID]})
        self.assertEqual(manager.created[0].parents[0], "20210101000000000-50001")
        self.assertEqual((stats.skipped, stats.linked), (1, 1))

    def test_existing_code_with_other_type_is_error(self):
        other = ExistingObject("2PP-000001", "20210101000000000-50001", "SAMPLE")
        manager = FakeManager({"2PP-000001": other})
        stats = upload([make_print(3, "2PP-000001")], manager)
        self.assertEqual(manager.created, [])
        self.assertEqual(stats.errors, 1)

    def test_rejected_step_blocks_its_sample_only(self):
        manager = FakeManager(reject={"2PP-000001"})
        stats = upload([print_only(3, "2PP-000001"), print_only(4, "2PP-000002")], manager)
        self.assertEqual([n.code for n in manager.created],
                         ["2PP-000002", "2PP_PRINTED_2PP-000002"])
        self.assertEqual(stats.errors, 1)


class TestPoliJob(unittest.TestCase):
    """3DPoli job objects: one per job file, parent of the print steps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "Array v1.txt"
        self.path.write_text("dvar($a)\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_object_shared_and_linked(self):
        manager = FakeManager()
        stats = upload([print_only(3, "2PP-000001", poli_job_file=str(self.path)),
                        print_only(4, "2PP-000002", poli_job_file=str(self.path)),
                        print_only(5, "2PP-000003")], manager)
        self.assertEqual(codes(manager)[0], "2PP_POLI_ARRAY_V1")
        self.assertEqual(codes(manager).count("2PP_POLI_ARRAY_V1"), 1)
        job = created(manager, "2PP_POLI_ARRAY_V1")
        self.assertEqual((job.type_code, job.collection_path, job.parents),
                         ("GENERAL_PROTOCOL", "/SPACE/PROJECT/3DPOLI", []))
        self.assertEqual(job.properties["$name"], "Array v1.txt")
        self.assertEqual(job.properties["general_protocol.protocol_type"],
                         "3DPoli job file (Femtika 2PP)")
        self.assertIn("Array v1.txt", job.properties["notes"])
        self.assertNotIn("bam_oe", job.properties)
        self.assertEqual(manager.uploaded, [(stats.permids["2PP_POLI_ARRAY_V1"],
                                             "2PP_POLI_ARRAY_V1", ["Array v1.txt"])])
        self.assertEqual(stats.datasets, 1)
        poli_permid = stats.permids["2PP_POLI_ARRAY_V1"]
        self.assertIn(poli_permid, created(manager, "2PP-000001").parents)
        self.assertIn(poli_permid, created(manager, "2PP-000002").parents)
        self.assertEqual(len(created(manager, "2PP-000003").parents), 3)

    def test_failed_print_still_linked(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", print_status="Failed",
                           poli_job_file=str(self.path))], manager)
        self.assertEqual(codes(manager), ["2PP_POLI_ARRAY_V1", "2PP-000001"])

    def test_rejected_job_blocks_its_prints(self):
        manager = FakeManager(reject={"2PP_POLI_ARRAY_V1"})
        stats = upload([print_only(3, "2PP-000001", poli_job_file=str(self.path)),
                        print_only(4, "2PP-000002")], manager)
        self.assertEqual(codes(manager), ["2PP-000002", "2PP_PRINTED_2PP-000002"])
        self.assertEqual(stats.errors, 1)

    def test_existing_job_linked_to_existing_print(self):
        job = ExistingObject("2PP_POLI_ARRAY_V1", "20210101000000000-60001", "GENERAL_PROTOCOL")
        step = ExistingObject("2PP-000001", "20210101000000000-50001", "EXPERIMENTAL_STEP",
                              {PRINTER, FAKE_RESIN_PERMID, FAKE_SUBSTRATE_PERMID})
        manager = FakeManager({"2PP_POLI_ARRAY_V1": job, "2PP-000001": step})
        upload([print_only(3, "2PP-000001", poli_job_file=str(self.path))], manager)
        self.assertNotIn("2PP_POLI_ARRAY_V1", codes(manager))
        self.assertEqual(manager.linked, {"2PP-000001": ["20210101000000000-60001"]})


class TestJobFileDataset(unittest.TestCase):
    """Job file dataset of an existing 3DPoli job object: no duplicates."""

    JOB_PERMID = "20210101000000000-60001"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "Array v1.txt"
        self.content = b"dvar($a)\n"
        self.path.write_bytes(self.content)

    def tearDown(self):
        self.tmp.cleanup()

    def _upload(self, stored: List[DatasetFile], update: bool = False):
        job = ExistingObject("2PP_POLI_ARRAY_V1", self.JOB_PERMID, "GENERAL_PROTOCOL")
        manager = FakeManager({"2PP_POLI_ARRAY_V1": job})
        manager.stored_files[self.JOB_PERMID] = stored
        stats = upload([print_only(3, "2PP-000001", poli_job_file=str(self.path))], manager,
                       update=update)
        return manager, stats

    def _same(self, name: str = "Array v1.txt") -> DatasetFile:
        return DatasetFile(name, len(self.content), zlib.crc32(self.content))

    def _other(self, name: str = "Array v1.txt") -> DatasetFile:
        return DatasetFile(name, 3, zlib.crc32(b"old"))

    def test_same_content_not_uploaded(self):
        manager, stats = self._upload([self._other(), self._same()])
        self.assertEqual(manager.uploaded, [])
        self.assertEqual(stats.datasets, 0)

    def test_same_content_under_other_name_not_uploaded(self):
        manager, _ = self._upload([self._same("renamed.txt")])
        self.assertEqual(manager.uploaded, [])

    def test_no_dataset_yet_uploaded(self):
        manager, stats = self._upload([])
        self.assertEqual(len(manager.uploaded), 1)
        self.assertIn("dataset", stats.records[0].status)

    def test_changed_without_update_only_warns(self):
        with self.assertLogs("openbis.uploader", "WARNING") as logs:
            manager, _ = self._upload([self._other()])
        self.assertEqual(manager.uploaded, [])
        self.assertIn("--update", logs.output[0])

    def test_changed_with_update_uploads_new_dataset(self):
        with self.assertLogs("openbis.uploader", "WARNING"):
            manager, stats = self._upload([self._other()], update=True)
        self.assertEqual(len(manager.uploaded), 1)
        self.assertEqual(stats.datasets, 1)

    def test_missing_checksum_not_uploaded(self):
        manager, _ = self._upload([DatasetFile("Array v1.txt", 3, None)], update=True)
        self.assertEqual(manager.uploaded, [])

    def test_failed_upload_is_error_but_print_goes_on(self):
        manager = FakeManager()
        manager.reject_upload = True
        stats = upload([print_only(3, "2PP-000001", poli_job_file=str(self.path))], manager)
        self.assertEqual(stats.errors, 1)
        self.assertIn("2PP-000001", codes(manager))
        self.assertIn("dataset error", stats.records[0].status)


def codes(manager: FakeManager) -> List[str]:
    return [n.code for n in manager.created]


def created(manager: FakeManager, code: str) -> NewObject:
    return next(n for n in manager.created if n.code == code)


class TestRuns(unittest.TestCase):
    """Washing / CPD / sintering steps shared per run ID, and sintered samples."""

    def test_full_chain_in_order(self):
        manager = FakeManager()
        stats = upload([make_print(3, "2PP-000001")], manager)
        self.assertEqual(codes(manager), [
            "2PP-000001", "2PP_PRINTED_2PP-000001", "2PP_WASH-0001", "2PP_CPD-0001",
            "2PP_SINT-0001", "2PP_SINTERED_2PP-000001"])
        p = stats.permids
        self.assertEqual(created(manager, "2PP_WASH-0001").parents, [p["2PP_PRINTED_2PP-000001"]])
        self.assertEqual(created(manager, "2PP_CPD-0001").parents, [p["2PP_WASH-0001"]])
        self.assertEqual(created(manager, "2PP_SINT-0001").parents,
                         [p["2PP_CPD-0001"], FAKE_FURNACE_PERMID])
        self.assertEqual(created(manager, "2PP_SINTERED_2PP-000001").parents,
                         [p["2PP_SINT-0001"], p["2PP_PRINTED_2PP-000001"]])

    def test_run_step_properties(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", washing_duration_min=30)], manager)
        wash = created(manager, "2PP_WASH-0001")
        self.assertEqual(wash.collection_path, "/SPACE/PROJECT/WASHING")
        self.assertEqual(wash.properties["$name"], "2PP_WASH-0001")
        self.assertEqual(wash.properties["start_date"], "2026-03-02 00:00:00")
        self.assertEqual(wash.properties["operator"], "Op B")
        description = wash.properties["experimental_step.experimental_description"]
        self.assertIn("Washing solvent: IPA<br>Washing duration [min]: 30", description)
        self.assertNotIn("Washing operator", description)
        sint = created(manager, "2PP_SINT-0001").properties["experimental_step.experimental_description"]
        self.assertIn("Furnace name: Furnace 1", sint)
        self.assertNotIn(FAKE_FURNACE_PERMID, sint)

    def test_shared_run_parents_are_deduplicated_union(self):
        # Two prints washed separately, dried together in one CPD run.
        manager = FakeManager()
        stats = upload([make_print(3, "2PP-000001"),
                        make_print(4, "2PP-000002", washing_run_id="WASH-0002")], manager)
        self.assertEqual(codes(manager).count("2PP_CPD-0001"), 1)
        self.assertEqual(created(manager, "2PP_CPD-0001").parents,
                         [stats.permids["2PP_WASH-0001"], stats.permids["2PP_WASH-0002"]])
        # Both prints in one washing run: one parent per printed sample.
        manager = FakeManager()
        stats = upload([make_print(3, "2PP-000001"), make_print(4, "2PP-000002")], manager)
        self.assertEqual(created(manager, "2PP_WASH-0001").parents,
                         [stats.permids["2PP_PRINTED_2PP-000001"],
                          stats.permids["2PP_PRINTED_2PP-000002"]])
        self.assertEqual(created(manager, "2PP_CPD-0001").parents, [stats.permids["2PP_WASH-0001"]])

    def test_washed_only_print(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", cpd_date=None, cpd_run_id=None,
                           sintering_date=None, sintering_run_id=None)], manager)
        self.assertEqual(codes(manager)[-1], "2PP_WASH-0001")

    def test_failed_print_takes_no_part(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", print_status="Failed")], manager)
        self.assertEqual(codes(manager), ["2PP-000001"])

    def test_checker_error_in_washing_blocks_later_steps_of_that_print_only(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001"),
                make_print(4, "2PP-000002", washing_run_id="WASH-0002", washing_solvent=None)],
               manager)
        self.assertNotIn("2PP_WASH-0002", codes(manager))
        self.assertNotIn("2PP_SINTERED_2PP-000002", codes(manager))
        self.assertIn("2PP_PRINTED_2PP-000002", codes(manager))
        self.assertIn("2PP_SINTERED_2PP-000001", codes(manager))

    def test_rejected_run_blocks_all_its_prints(self):
        manager = FakeManager(reject={"2PP_CPD-0001"})
        stats = upload([make_print(3, "2PP-000001"), make_print(4, "2PP-000002")], manager)
        self.assertNotIn("2PP_SINT-0001", codes(manager))
        self.assertNotIn("2PP_SINTERED_2PP-000001", codes(manager))
        self.assertEqual(stats.errors, 1)

    def test_print_added_to_existing_run_gets_linked(self):
        wash = ExistingObject("2PP_WASH-0001", "20210101000000000-60001", "EXPERIMENTAL_STEP",
                              {"20210101000000000-70001"})
        manager = FakeManager({"2PP_WASH-0001": wash})
        stats = upload([make_print(3, "2PP-000001", cpd_date=None, cpd_run_id=None,
                                   sintering_date=None, sintering_run_id=None)], manager)
        self.assertEqual(manager.linked["2PP_WASH-0001"], [stats.permids["2PP_PRINTED_2PP-000001"]])


class TestImaging(unittest.TestCase):
    """One imaging step per Imaging row, linked to the imaged sample."""

    def test_green_and_sintered(self):
        manager = FakeManager()
        stats = upload([make_print(3, "2PP-000001")], manager, imaging=[
            make_imaging(3, "2PP-000001", notes="Line 1\nLine 2"),
            make_imaging(4, "2PP-000001", sample_state="Sintered", instrument_permid=None)])
        green = created(manager, "2PP_IMG_2PP-000001_SEM_GREEN_20260305")
        self.assertEqual(green.parents, [stats.permids["2PP_PRINTED_2PP-000001"], INSTRUMENT])
        self.assertEqual(green.collection_path, "/SPACE/PROJECT/IMAGING")
        self.assertEqual(green.properties["start_date"], "2026-03-05 00:00:00")
        self.assertEqual(green.properties["operator"], "Op E")
        self.assertEqual(green.properties["notes"], "Line 1<br>Line 2")
        self.assertIn("Technique: SEM<br>Sample state: Green",
                      green.properties["experimental_step.experimental_description"])
        sintered = created(manager, "2PP_IMG_2PP-000001_SEM_SINTERED_20260305")
        self.assertEqual(sintered.parents, [stats.permids["2PP_SINTERED_2PP-000001"]])
        self.assertEqual(codes(manager)[-2:], [green.code, sintered.code])

    def test_blocked_print_blocks_its_imaging(self):
        # Washing error on the print: no imaging for it (CLAUDE.md upload rule).
        manager = FakeManager()
        upload([make_print(3, "2PP-000001", washing_solvent=None)], manager,
               imaging=[make_imaging(3, "2PP-000001")])
        self.assertFalse(any(c.startswith("2PP_IMG_") for c in codes(manager)))

    def test_disabled_and_invalid_rows_skipped(self):
        manager = FakeManager()
        upload([make_print(3, "2PP-000001")], manager, imaging=[
            make_imaging(3, "2PP-000001", openbis_upload="No"),
            make_imaging(4, "2PP-000001", sample_state="Wet")])
        self.assertFalse(any(c.startswith("2PP_IMG_") for c in codes(manager)))

    def test_rejected_imaging_does_not_block_other_rows(self):
        manager = FakeManager(reject={"2PP_IMG_2PP-000001_SEM_GREEN_20260305"})
        stats = upload([make_print(3, "2PP-000001")], manager, imaging=[
            make_imaging(3, "2PP-000001"), make_imaging(4, "2PP-000001", technique="LIMI")])
        self.assertIn("2PP_IMG_2PP-000001_LIMI_GREEN_20260305", codes(manager))
        self.assertEqual(stats.errors, 1)


class TestReport(unittest.TestCase):
    """End report: one CSV row per object touched."""

    def test_rows_and_statuses(self):
        step = ExistingObject("2PP-000001", "20210101000000000-50001", "EXPERIMENTAL_STEP",
                              {PRINTER, FAKE_RESIN_PERMID})
        manager = FakeManager({"2PP-000001": step}, reject={"2PP_PRINTED_2PP-000002"})
        stats = upload([print_only(3, "2PP-000001"), print_only(4, "2PP-000002")], manager)
        rows = {r.code: r for r in stats.records}
        self.assertEqual(rows["2PP-000001"].status, "existing + linked")
        self.assertEqual(rows["2PP-000001"].permid, "20210101000000000-50001")
        self.assertEqual(rows["2PP_PRINTED_2PP-000001"].status, "created")
        self.assertEqual(rows["2PP_PRINTED_2PP-000001"].origin, "PrintJobs row(s) 3")
        self.assertTrue(rows["2PP_PRINTED_2PP-000002"].status.startswith("error"))
        self.assertEqual(rows["2PP_PRINTED_2PP-000002"].permid, "")

    def test_dry_run_status_and_csv(self):
        manager = FakeManager()
        manager.dry_run = True
        stats = upload([print_only(3, "2PP-000001")], manager)
        self.assertEqual({r.status for r in stats.records}, {"would create"})
        with tempfile.TemporaryDirectory() as tmp:
            report = write_report(stats, Path(tmp) / "reports", dry_run=True)
            self.assertTrue(report.name.endswith("_dry-run.csv"))
            with open(report, encoding="utf-8", newline="") as handle:
                lines = list(csv.reader(handle))
        self.assertEqual(lines[0], ["code", "type", "permId", "status", "origin"])
        self.assertEqual([line[0] for line in lines[1:]], ["2PP-000001", "2PP_PRINTED_2PP-000001"])


class TestUpdate(unittest.TestCase):

    def _existing_step(self, **props: str) -> ExistingObject:
        job = make_print(3, "2PP-000001")
        stored = {k.upper(): v for k, v in
                  object_builders.print_step(job, PRINTJOBS, PRINTER).properties.items()
                  if v is not None}
        stored["START_DATE"] = "2026-03-01 00:00:00 +0100"  # as openBIS returns it
        stored.update(props)
        return ExistingObject("2PP-000001", "20210101000000000-50001", "EXPERIMENTAL_STEP",
                              {PRINTER, FAKE_RESIN_PERMID, FAKE_SUBSTRATE_PERMID}, stored)

    def test_only_changed_properties_updated(self):
        manager = FakeManager({"2PP-000001": self._existing_step()})
        stats = upload([make_print(3, "2PP-000001", print_status="Failed")], manager, update=True)
        self.assertEqual(manager.updated, {"2PP-000001": {
            "experimental_step.experimental_results": "Failed"}})
        self.assertEqual(stats.updated, 1)

    def test_timezone_suffix_is_not_a_change(self):
        manager = FakeManager({"2PP-000001": self._existing_step()})
        upload([make_print(3, "2PP-000001", print_status="Failed")], manager, update=True)
        self.assertNotIn("start_date", manager.updated["2PP-000001"])

    def test_empty_cell_does_not_clear(self):
        manager = FakeManager({"2PP-000001": self._existing_step(NOTES="typed in the ELN")})
        upload([make_print(3, "2PP-000001", print_status="Failed")], manager, update=True)
        self.assertNotIn("notes", manager.updated["2PP-000001"])

    def test_without_update_flag_nothing_changes(self):
        manager = FakeManager({"2PP-000001": self._existing_step(OPERATOR="Someone else")})
        stats = upload([make_print(3, "2PP-000001", print_status="Failed")], manager)
        self.assertEqual((manager.updated, stats.updated), ({}, 0))


class TestObjectManager(unittest.TestCase):

    def test_dry_run_never_writes(self):
        openbis = MagicMock()
        manager = ObjectManager(openbis, "SPACE", "PROJECT", dry_run=True)
        new = NewObject("SAMPLE", "X", SAMPLES, {"$name": "X"}, [PRINTER])
        self.assertEqual(manager.create(new), "(new) X")
        existing = ExistingObject("Y", "20210101000000000-00002", "SAMPLE")
        self.assertEqual(manager.add_parents(existing, [PRINTER]), [PRINTER])
        manager.update_properties(existing, {"$name": "Z"})
        manager.upload_dataset("(new) X", "X", [Path("a.txt")])
        openbis.new_sample.assert_not_called()
        openbis.get_sample.assert_not_called()
        openbis.new_dataset.assert_not_called()

    def test_dataset_files_parses_listing(self):
        openbis = MagicMock()
        openbis.get_datasets.return_value = [MagicMock(permId="DS1")]
        openbis.get_dataset.return_value.get_files.return_value = pd.DataFrame([
            {"isDirectory": True, "pathInDataSet": "original", "fileSize": 0, "crc32Checksum": 0},
            {"isDirectory": False, "pathInDataSet": "original/a.txt", "fileSize": 9,
             "crc32Checksum": "0686806d"},
            {"isDirectory": False, "pathInDataSet": "original/b.txt", "fileSize": 4,
             "crc32Checksum": ""},
        ])
        manager = ObjectManager(openbis, "SPACE", "PROJECT", dry_run=False)
        self.assertEqual(manager.dataset_files("P1"), [
            DatasetFile("a.txt", 9, 0x0686806d), DatasetFile("b.txt", 4, None)])
        openbis.get_datasets.assert_called_once_with(sample="P1")

    def test_find_existing_parses_response(self):
        openbis = MagicMock()
        openbis.get_sample.return_value = {"k": {
            "code": "2PP-000001", "permId": {"permId": "20210101000000000-00001"},
            "type": {"code": "EXPERIMENTAL_STEP"},
            "parents": [{"permId": {"permId": PRINTER}}],
        }}
        manager = ObjectManager(openbis, "SPACE", "PROJECT", dry_run=False)
        found = manager.find_existing(["2PP-000001", "2PP-000002"])
        openbis.get_sample.assert_called_once_with(
            ["/SPACE/PROJECT/2PP-000001", "/SPACE/PROJECT/2PP-000002"], raw_response=True)
        self.assertEqual(found["2PP-000001"].parent_permids, {PRINTER})


if __name__ == "__main__":
    unittest.main()
