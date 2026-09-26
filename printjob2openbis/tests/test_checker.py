"""Tests for checks.checker (synthetic data, fake permIds)."""

import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from checks.checker import check_protocol
from checks.issues import CheckResult, Issue, Level, Stage
from excel.excel_reader import ProtocolData
from models import ImagingEvent, PrintJob
from tests.workbook_builder import (
    FAKE_FURNACE_PERMID,
    FAKE_RESIN_PERMID,
    FAKE_SUBSTRATE_PERMID,
)

PRINTER = "20210101000000000-99999"
INSTRUMENT = "20210101000000000-40001"


def make_print(row: int, code: str, **overrides: Any) -> PrintJob:
    """A complete, valid print with washing, CPD and sintering."""
    values: Dict[str, Any] = dict(
        print_code=code, print_name=f"20260301_2PP_{code}", print_date=date(2026, 3, 1),
        print_operator="Op A", design="Lattice", print_status="OK",
        resin_name="Resin 1", resin_permid=FAKE_RESIN_PERMID,
        substrate_name="UV-Sheet 1", substrate_permid=FAKE_SUBSTRATE_PERMID,
        objective="63x",
        washing_date=date(2026, 3, 2), washing_run_id="WASH-0001",
        washing_operator="Op B", washing_solvent="IPA",
        cpd_date=date(2026, 3, 3), cpd_run_id="CPD-0001", cpd_operator="Op C",
        sintering_date=date(2026, 3, 4), sintering_run_id="SINT-0001",
        sintering_operator="Op D", furnace_name="Furnace 1",
        furnace_permid=FAKE_FURNACE_PERMID,
    )
    values.update(overrides)
    return PrintJob(row=row, **values)


def make_imaging(row: int, code: str, **overrides: Any) -> ImagingEvent:
    """A valid imaging row."""
    values: Dict[str, Any] = dict(
        print_code=code, technique="SEM", sample_state="Green",
        imaging_date=date(2026, 3, 5), imaging_operator="Op E", instrument_permid=INSTRUMENT,
    )
    values.update(overrides)
    return ImagingEvent(row=row, **values)


def run(prints: List[PrintJob], imaging: Optional[List[ImagingEvent]] = None,
        lookup=None, **data_kwargs: Any) -> CheckResult:
    data = ProtocolData(file_path=Path("x.xlsx"), prints=prints, imaging=imaging or [],
                        **data_kwargs)
    return check_protocol(data, printer_permid=PRINTER, permid_lookup=lookup)


def issues_at(result: CheckResult, row: int, column: Optional[str] = None) -> List[Issue]:
    return [i for i in result.issues if i.row == row and (column is None or i.column == column)]


class TestValidData(unittest.TestCase):

    def test_no_issues(self):
        prints = [make_print(3, "2PP-000001"), make_print(4, "2PP-000002")]
        imaging = [make_imaging(3, "2PP-000001"),
                   make_imaging(4, "2PP-000001", sample_state="Sintered")]
        result = run(prints, imaging)
        self.assertEqual(result.issues, [], [str(i) for i in result.issues])


class TestFile(unittest.TestCase):

    def test_missing_header_is_fatal(self):
        result = run([make_print(3, "2PP-000001")],
                     missing_headers={"PrintJobs": ["Print status"]})
        self.assertTrue(result.fatal)
        self.assertEqual(len(result.issues), 1)

    def test_not_recalculated_is_fatal(self):
        result = run([make_print(3, "2PP-000001", print_name=None)])
        self.assertTrue(result.fatal)

    def test_row_without_key_warns(self):
        result = run([make_print(3, "2PP-000001")], rows_without_key={"PrintJobs": [7]})
        self.assertEqual([i.level for i in issues_at(result, 7)], [Level.WARNING])
        self.assertFalse(result.fatal)

    def test_invalid_printer_permid(self):
        data = ProtocolData(file_path=Path("x.xlsx"), prints=[make_print(3, "2PP-000001")])
        self.assertTrue(check_protocol(data, printer_permid="TODO").fatal)


class TestPrint(unittest.TestCase):

    def test_duplicate_code(self):
        result = run([make_print(3, "2PP-000001"), make_print(4, "2PP-000001")])
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.PRINT)
        self.assertEqual(result.blocked_from("PrintJobs", 4), Stage.PRINT)

    def test_required_value(self):
        result = run([make_print(3, "2PP-000001", print_operator=None)])
        self.assertEqual(len(issues_at(result, 3, "Print operator")), 1)

    def test_empty_status_is_blocking_warning(self):
        result = run([make_print(3, "2PP-000001", print_status=None)])
        [issue] = issues_at(result, 3, "Print status")
        self.assertIs(issue.level, Level.WARNING)
        self.assertTrue(issue.blocking)

    def test_invalid_status(self):
        result = run([make_print(3, "2PP-000001", print_status="Done")])
        self.assertEqual(issues_at(result, 3, "Print status")[0].level, Level.ERROR)

    def test_resin_not_in_list(self):
        result = run([make_print(3, "2PP-000001", resin_permid="NOT IN LIST")])
        self.assertIn("not in the Lists sheet", issues_at(result, 3, "Resin permId")[0].message)

    def test_upload_no_row_is_ignored(self):
        result = run([make_print(3, "2PP-000001", openbis_upload="No", print_operator=None)])
        self.assertEqual(result.issues, [])

    def test_print_code_not_usable_in_code(self):
        result = run([make_print(3, "2PP 000001")])
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.PRINT)

    def test_invalid_upload_value(self):
        result = run([make_print(3, "2PP-000001", openbis_upload="Maybe")])
        self.assertEqual(len(issues_at(result, 3, "openBIS upload")), 1)

    def test_failed_print_skips_post_processing(self):
        result = run([make_print(3, "2PP-000001", print_status="Failed", washing_operator=None)])
        self.assertEqual([i.level for i in result.issues], [Level.WARNING])


class TestPostProcessing(unittest.TestCase):

    def test_run_id_without_date(self):
        result = run([make_print(3, "2PP-000001", sintering_date=None)])
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.SINTERING)

    def test_required_when_dated(self):
        result = run([make_print(3, "2PP-000001", washing_solvent=None)])
        self.assertEqual(len(issues_at(result, 3, "Washing solvent")), 1)
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.WASHING)

    def test_wrong_prefix(self):
        result = run([make_print(3, "2PP-000001", cpd_run_id="WASH-0001")])
        messages = [i.message for i in issues_at(result, 3, "CPD run ID")]
        self.assertTrue(any("must start with 'CPD-'" in m for m in messages))
        self.assertTrue(any("is used for" in m for m in messages))

    def test_cpd_without_washing(self):
        result = run([make_print(3, "2PP-000001", washing_date=None, washing_run_id=None)])
        self.assertEqual(len(issues_at(result, 3, "CPD date")), 1)

    def test_date_order(self):
        result = run([make_print(3, "2PP-000001", cpd_date=date(2026, 2, 1))])
        self.assertIn("is before", issues_at(result, 3, "CPD date")[0].message)

    def test_date_not_a_date(self):
        result = run([make_print(3, "2PP-000001", washing_date="yesterday")])
        self.assertEqual(len(issues_at(result, 3, "Washing date")), 1)

    def test_run_inconsistency_blocks_whole_run(self):
        prints = [make_print(3, "2PP-000001"),
                  make_print(4, "2PP-000002", cpd_operator="Op X")]
        result = run(prints)
        for row in (3, 4):
            self.assertEqual(result.blocked_from("PrintJobs", row), Stage.CPD)
        self.assertIn("CPD operator", issues_at(result, 3)[0].message)

    def test_other_step_columns_not_compared(self):
        prints = [make_print(3, "2PP-000001"),
                  make_print(4, "2PP-000002", print_operator="Op X", washing_operator="Op Y",
                             washing_run_id="WASH-0002")]
        self.assertEqual(run(prints).errors, [])

    def test_blocked_print_does_not_break_run(self):
        # Row 4 has a washing error, so it does not take part in CPD run CPD-0001.
        prints = [make_print(3, "2PP-000001"),
                  make_print(4, "2PP-000002", washing_solvent=None, washing_run_id="WASH-0002",
                             cpd_operator="Op X")]
        result = run(prints)
        self.assertIsNone(result.blocked_from("PrintJobs", 3))

    def test_same_substrate_different_dates_warns(self):
        prints = [make_print(3, "2PP-000001"),
                  make_print(4, "2PP-000002", washing_date=date(2026, 3, 3),
                             washing_run_id="WASH-0002")]
        result = run(prints)
        self.assertEqual([i.level for i in result.issues], [Level.WARNING])
        self.assertFalse(result.issues[0].blocking)

    def test_furnace_not_in_list(self):
        result = run([make_print(3, "2PP-000001", furnace_permid="NOT IN LIST")])
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.SINTERING)


class TestImaging(unittest.TestCase):

    def setUp(self) -> None:
        self.prints = [make_print(3, "2PP-000001"),
                       make_print(4, "2PP-000002", sintering_date=None, sintering_run_id=None)]

    def test_unknown_print(self):
        result = run(self.prints, [make_imaging(3, "2PP-999999")])
        self.assertEqual(result.blocked_from("Imaging", 3), Stage.IMAGING)

    def test_failed_print(self):
        self.prints[0].print_status = "Failed"
        result = run(self.prints, [make_imaging(3, "2PP-000001")])
        self.assertEqual(len(issues_at(result, 3, "Print code")), 1)

    def test_sintered_needs_sintering(self):
        result = run(self.prints, [make_imaging(3, "2PP-000002", sample_state="Sintered")])
        self.assertEqual(len(issues_at(result, 3, "Sample state")), 1)

    def test_invalid_state(self):
        result = run(self.prints, [make_imaging(3, "2PP-000001", sample_state="Wet")])
        self.assertEqual(len(issues_at(result, 3, "Sample state")), 1)

    def test_duplicate_identity(self):
        result = run(self.prints, [make_imaging(3, "2PP-000001"), make_imaging(4, "2PP-000001")])
        self.assertEqual(len(result.errors), 2)

    def test_instrument_placeholder(self):
        result = run(self.prints, [make_imaging(3, "2PP-000001", instrument_permid="TODO")])
        self.assertEqual(len(issues_at(result, 3, "Instrument permId")), 1)

    def test_technique_not_usable_in_code(self):
        result = run(self.prints, [make_imaging(3, "2PP-000001", technique="Light microscope")])
        self.assertEqual(len(issues_at(result, 3, "Technique")), 1)

    def test_instrument_optional(self):
        result = run(self.prints, [make_imaging(3, "2PP-000001", instrument_permid=None)])
        self.assertEqual(result.issues, [])


class TestOnline(unittest.TestCase):

    def test_missing_objects_reported(self):
        asked: List[Set[str]] = []

        def lookup(permids: Set[str]) -> Set[str]:
            asked.append(permids)
            return permids - {FAKE_SUBSTRATE_PERMID, INSTRUMENT}

        result = run([make_print(3, "2PP-000001")], [make_imaging(3, "2PP-000001")], lookup)
        self.assertEqual(len(asked), 1)  # one batched lookup
        self.assertEqual(result.blocked_from("PrintJobs", 3), Stage.PRINT)
        self.assertEqual(result.blocked_from("Imaging", 3), Stage.IMAGING)

    def test_bam_oe_not_in_vocabulary_is_fatal(self):
        data = ProtocolData(file_path=Path("x.xlsx"), prints=[make_print(3, "2PP-000001")])
        terms = {"BAM_OE": {"OE_1.1", "OE_1.2"}}
        result = check_protocol(data, bam_oe="OE_9.9", vocabulary_lookup=terms.__getitem__)
        self.assertTrue(result.fatal)
        self.assertIn("BAM_OE", result.issues[0].message)
        ok = check_protocol(data, bam_oe="OE_1.1", vocabulary_lookup=terms.__getitem__)
        self.assertEqual(ok.issues, [])

    def test_bam_oe_not_checked_offline(self):
        data = ProtocolData(file_path=Path("x.xlsx"), prints=[make_print(3, "2PP-000001")])
        self.assertEqual(check_protocol(data, bam_oe="anything").issues, [])

    def test_missing_printer_is_fatal(self):
        result = run([make_print(3, "2PP-000001")], lookup=lambda p: p - {PRINTER})
        self.assertTrue(result.fatal)


if __name__ == "__main__":
    unittest.main()
