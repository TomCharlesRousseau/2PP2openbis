"""Tests for the models: step entries, run grouping, codes."""

import sys
import unittest
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from models import ImagingEvent, PrintJob, StepKind, group_runs, run_ids_by_kind
from models.printjob import poli_code_from_filename, poli_job_file_name


def _job(row: int, code: str, **kwargs) -> PrintJob:
    return PrintJob(row=row, print_code=code, **kwargs)


class TestStepKind(unittest.TestCase):
    """Fixed order and own columns of the post-processing steps."""

    def test_order(self):
        self.assertIsNone(StepKind.WASHING.previous)
        self.assertIs(StepKind.CPD.previous, StepKind.WASHING)
        self.assertIs(StepKind.SINTERING.previous, StepKind.CPD)

    def test_own_fields(self):
        self.assertEqual(StepKind.WASHING.own_fields, ["washing_solvent", "washing_duration_min"])
        self.assertEqual(StepKind.CPD.own_fields, ["cpd_program"])
        self.assertIn("furnace_name", StepKind.SINTERING.own_fields)
        self.assertNotIn("sintering_run_id", StepKind.SINTERING.own_fields)


class TestPrintJob(unittest.TestCase):
    """Status flags, step entries and codes of a print."""

    def test_step_entry(self):
        job = _job(3, "2PP-000001", washing_date=date(2026, 3, 21), washing_run_id="WASH-0012",
                   washing_operator="Op A", washing_solvent="IPA")
        entry = job.step(StepKind.WASHING)
        self.assertTrue(entry.exists)
        self.assertEqual(entry.run_id, "WASH-0012")
        self.assertEqual(entry.attributes, {"washing_solvent": "IPA", "washing_duration_min": None})
        self.assertFalse(job.step(StepKind.CPD).exists)

    def test_run_id_without_date_is_visible(self):
        entry = _job(3, "2PP-000001", cpd_run_id="CPD-0001").step(StepKind.CPD)
        self.assertFalse(entry.exists)
        self.assertEqual(entry.run_id, "CPD-0001")

    def test_flags(self):
        self.assertTrue(_job(3, "x", openbis_upload="no").upload_disabled)
        self.assertFalse(_job(3, "x").upload_disabled)
        self.assertTrue(_job(3, "x", print_status="Failed").is_failed)
        self.assertFalse(_job(3, "x", print_status="Partial").is_failed)

    def test_codes_uppercase(self):
        job = _job(3, "2pp-000001", sintering_run_id="sint-0003")
        self.assertEqual(job.print_step_code, "2PP-000001")
        self.assertEqual(job.printed_sample_code, "2PP_PRINTED_2PP-000001")
        self.assertEqual(job.sintered_sample_code, "2PP_SINTERED_2PP-000001")
        self.assertEqual(job.run_code(StepKind.SINTERING), "2PP_SINT-0003")
        self.assertIsNone(job.run_code(StepKind.WASHING))

    def test_poli_job_code(self):
        job = _job(3, "x", poli_job_file=r"\\SHARE\2PP\Experimente chronologisch"
                                         r"\20260303_Array mit Text Logo und QR Code-fix2.txt")
        self.assertEqual(job.poli_job_code,
                         "2PP_POLI_20260303_ARRAY_MIT_TEXT_LOGO_UND_QR_CODE-FIX2")
        self.assertIsNone(_job(3, "x").poli_job_code)


class TestPoliCode(unittest.TestCase):
    """Code of the 3DPoli job object from the file name."""

    def test_umlauts_and_accents(self):
        self.assertEqual(poli_code_from_filename("Gitter größe Ü1 café.txt"),
                         "2PP_POLI_GITTER_GROESSE_UE1_CAFE")

    def test_spaces_and_special_characters(self):
        self.assertEqual(poli_code_from_filename("A  b (2)+c.v2.TXT"), "2PP_POLI_A_B_2C.V2")

    def test_file_name_from_path(self):
        self.assertEqual(poli_job_file_name(r"C:\jobs\Array v1.txt"), "Array v1.txt")
        self.assertEqual(poli_job_file_name("/mnt/jobs/Array v1.txt "), "Array v1.txt")


class TestRuns(unittest.TestCase):
    """Grouping prints into runs and run consistency."""

    def setUp(self) -> None:
        wash = dict(washing_date=date(2026, 3, 21), washing_operator="Op A", washing_solvent="IPA")
        self.jobs = [
            _job(3, "2PP-000001", washing_run_id="WASH-0001", cpd_run_id="CPD-0001", **wash),
            _job(4, "2PP-000002", washing_run_id="WASH-0001", cpd_run_id="CPD-0001", **wash),
            _job(5, "2PP-000003", washing_run_id="WASH-0002", **wash),
            _job(6, "2PP-000004"),
        ]

    def test_group_by_run_id(self):
        runs = group_runs(self.jobs, StepKind.WASHING)
        self.assertEqual(list(runs), ["WASH-0001", "WASH-0002"])
        self.assertEqual(runs["WASH-0001"].rows, [3, 4])
        self.assertEqual(runs["WASH-0001"].code, "2PP_WASH-0001")

    def test_consistent_run(self):
        run = group_runs(self.jobs, StepKind.WASHING)["WASH-0001"]
        self.assertTrue(run.is_consistent())

    def test_mismatch_in_own_columns(self):
        self.jobs[1].washing_solvent = "Ethanol"
        self.jobs[1].washing_date = date(2026, 3, 22)
        run = group_runs(self.jobs, StepKind.WASHING)["WASH-0001"]
        self.assertEqual(run.mismatched_fields(), ["washing_date", "washing_solvent"])

    def test_other_step_columns_not_compared(self):
        self.jobs[1].print_operator = "Op B"
        self.jobs[1].cpd_program = 2
        self.assertTrue(group_runs(self.jobs, StepKind.WASHING)["WASH-0001"].is_consistent())

    def test_run_id_used_for_two_steps(self):
        self.jobs[2].cpd_run_id = "WASH-0001"
        usage = run_ids_by_kind(self.jobs)
        kinds = {kind for kind, _ in usage["WASH-0001"]}
        self.assertEqual(kinds, {StepKind.WASHING, StepKind.CPD})


class TestImagingEvent(unittest.TestCase):
    """Imaging identity and code."""

    def test_code(self):
        event = ImagingEvent(row=3, print_code="2PP-000001", technique="Limi",
                             sample_state="Green", imaging_date=date(2026, 3, 20))
        self.assertEqual(event.code, "2PP_IMG_2PP-000001_LIMI_GREEN_20260320")
        self.assertEqual(event.identity, ("2PP-000001", "Limi", "Green", date(2026, 3, 20)))

    def test_code_needs_date(self):
        with self.assertRaises(ValueError):
            ImagingEvent(row=3, print_code="x", imaging_date="20.03.2026").code


if __name__ == "__main__":
    unittest.main()
