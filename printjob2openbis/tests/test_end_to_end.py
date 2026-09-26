"""
End-to-end test: synthetic workbook → reader → checker → uploader (fake openBIS) → report.

Scenario (all data synthetic, permIds fake):

| Row | Print      | Situation                                                     |
|-----|------------|---------------------------------------------------------------|
| 3   | 2PP-000001 | full chain: washed + dried with row 4, sintered alone         |
| 4   | 2PP-000002 | washed + dried with row 3, not sintered                       |
| 5   | 2PP-000003 | Failed → print step only                                      |
| 6   | 2PP-000004 | Print status empty → blocking WARNING, nothing uploaded      |
| 7   | 2PP-000005 | openBIS upload = No → ignored everywhere (even its error)     |
| 8   | 2PP-000006 | own washing run with solvent missing → print + sample only    |

Imaging rows: Green + Sintered of print 1 (created), Green of print 2 (created),
Sintered of print 2 (ERROR: not sintered), print 3 (ERROR: Failed),
print 6 (skipped: its print is blocked from washing on).
"""

import csv
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from checks.checker import check_protocol
from checks.issues import Level
from excel.excel_reader import read_protocol
from openbis.uploader import Uploader, write_report
from tests.test_checker import PRINTER, make_imaging, make_print
from tests.test_uploader import CONFIG, FakeManager
from tests.workbook_builder import write_workbook

NOT_SINTERED = dict(sintering_date=None, sintering_run_id=None)


def _values(obj) -> dict:
    """Model object → field values for the workbook builder (without the row number)."""
    return {k: v for k, v in asdict(obj).items() if k != "row"}


class TestEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        prints = [
            make_print(3, "2PP-000001"),
            make_print(4, "2PP-000002", **NOT_SINTERED),
            make_print(5, "2PP-000003", print_status="Failed", **NOT_SINTERED,
                       washing_date=None, washing_run_id=None, cpd_date=None, cpd_run_id=None),
            make_print(6, "2PP-000004", print_status=None),
            make_print(7, "2PP-000005", openbis_upload="No", print_operator=None),
            make_print(8, "2PP-000006", washing_run_id="WASH-0002", washing_solvent=None,
                       cpd_date=None, cpd_run_id=None, **NOT_SINTERED),
        ]
        imaging = [
            make_imaging(3, "2PP-000001", technique="LIMI"),
            make_imaging(4, "2PP-000001", sample_state="Sintered", imaging_date=date(2026, 3, 6)),
            make_imaging(5, "2PP-000002", technique="LIMI"),
            make_imaging(6, "2PP-000002", sample_state="Sintered"),
            make_imaging(7, "2PP-000003"),
            make_imaging(8, "2PP-000006"),
        ]
        path = write_workbook(tmp / "protocol.xlsx",
                              [_values(p) for p in prints], [_values(e) for e in imaging])

        cls.data = read_protocol(path)
        cls.check = check_protocol(cls.data, printer_permid=PRINTER)
        cls.manager = FakeManager()
        cls.stats = Uploader(cls.manager, CONFIG, cls.data, cls.check).run()
        report = write_report(cls.stats, tmp / "reports", dry_run=False)
        with open(report, encoding="utf-8", newline="") as handle:
            cls.report = list(csv.DictReader(handle))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_workbook_round_trip(self):
        self.assertEqual([p.row for p in self.data.prints], [3, 4, 5, 6, 7, 8])
        self.assertEqual(self.data.prints[0].print_date, date(2026, 3, 1))
        self.assertEqual(self.data.missing_headers, {})

    def test_check_findings(self):
        found = {(i.sheet, i.row, i.level) for i in self.check.issues}
        self.assertEqual(found, {
            ("PrintJobs", 6, Level.WARNING),  # status empty
            ("PrintJobs", 8, Level.ERROR),    # washing solvent missing
            ("Imaging", 6, Level.ERROR),      # Sintered, print not sintered
            ("Imaging", 7, Level.ERROR),      # print Failed
        })
        self.assertFalse(self.check.fatal)

    def test_created_objects_in_upload_order(self):
        self.assertEqual([n.code for n in self.manager.created], [
            "2PP-000001", "2PP-000002", "2PP-000003", "2PP-000006",
            "2PP_PRINTED_2PP-000001", "2PP_PRINTED_2PP-000002", "2PP_PRINTED_2PP-000006",
            "2PP_WASH-0001",
            "2PP_CPD-0001",
            "2PP_SINT-0001",
            "2PP_SINTERED_2PP-000001",
            "2PP_IMG_2PP-000001_LIMI_GREEN_20260305",
            "2PP_IMG_2PP-000001_SEM_SINTERED_20260306",
            "2PP_IMG_2PP-000002_LIMI_GREEN_20260305",
        ])
        self.assertEqual(self.stats.errors, 0)

    def test_shared_runs_link_both_prints(self):
        created = {n.code: n for n in self.manager.created}
        permids = self.stats.permids
        self.assertEqual(created["2PP_WASH-0001"].parents,
                         [permids["2PP_PRINTED_2PP-000001"], permids["2PP_PRINTED_2PP-000002"]])
        self.assertEqual(created["2PP_CPD-0001"].parents, [permids["2PP_WASH-0001"]])

    def test_report_matches_upload(self):
        self.assertEqual(len(self.report), len(self.manager.created))
        self.assertEqual({row["status"] for row in self.report}, {"created"})
        wash = next(row for row in self.report if row["code"] == "2PP_WASH-0001")
        self.assertEqual(wash["origin"], "PrintJobs row(s) 3, 4")
        self.assertEqual(wash["permId"], self.stats.permids["2PP_WASH-0001"])


if __name__ == "__main__":
    unittest.main()
