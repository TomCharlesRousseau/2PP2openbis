"""Tests for excel.excel_reader (synthetic workbooks only)."""

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from excel.column_mapping import SHEET_IMAGING, SHEET_PRINTJOBS
from excel.excel_reader import clean_cell, normalise_header, read_protocol
from tests.workbook_builder import FAKE_SUBSTRATE_PERMID, write_workbook


class TestCleaning(unittest.TestCase):
    """Cell and header normalisation."""

    def test_text_is_stripped_and_empty_is_none(self):
        self.assertEqual(clean_cell("  OK "), "OK")
        self.assertIsNone(clean_cell("   "))
        self.assertIsNone(clean_cell(None))

    def test_midnight_datetime_becomes_date(self):
        self.assertEqual(clean_cell(datetime(2026, 3, 20)), date(2026, 3, 20))
        self.assertEqual(clean_cell(datetime(2026, 3, 20, 14, 5)), datetime(2026, 3, 20, 14, 5))

    def test_numbers_unchanged(self):
        self.assertEqual(clean_cell(2), 2)
        self.assertEqual(clean_cell(0.5), 0.5)

    def test_header_whitespace_collapsed(self):
        self.assertEqual(normalise_header("  Print   code "), "Print code")


class TestReadProtocol(unittest.TestCase):
    """Reading PrintJobs and Imaging rows by header name."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "protocol.xlsx"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_protocol(self.path)

    def test_reads_print_row(self):
        write_workbook(
            self.path,
            prints=[{
                "print_code": "2PP-000001",
                "print_date": datetime(2026, 3, 20),
                "print_status": "OK",
                "substrate_permid": FAKE_SUBSTRATE_PERMID,
                "spacer_count": 2,
                "slicing_distance_um": 0.3,
                "washing_run_id": "WASH-0001",
            }],
        )
        data = read_protocol(self.path)
        self.assertEqual(len(data.prints), 1)
        job = data.prints[0]
        self.assertEqual(job.row, 3)
        self.assertEqual(job.print_code, "2PP-000001")
        self.assertEqual(job.print_date, date(2026, 3, 20))
        self.assertEqual(job.spacer_count, 2)
        self.assertEqual(job.slicing_distance_um, 0.3)
        self.assertEqual(job.washing_run_id, "WASH-0001")
        self.assertIsNone(job.cpd_date)
        self.assertEqual(data.missing_headers, {})
        self.assertEqual(data.missing_sheets, [])

    def test_row_without_print_code_is_not_data_but_reported(self):
        write_workbook(
            self.path,
            prints=[
                {"print_code": "2PP-000001"},
                {"design": "Lattice"},          # input value, no key
                {"print_name": "20260320_2PP_x"},  # formula column only → empty template row
                {"openbis_upload": "No"},        # not data on its own
            ],
        )
        data = read_protocol(self.path)
        self.assertEqual([p.print_code for p in data.prints], ["2PP-000001"])
        self.assertEqual(data.rows_without_key, {SHEET_PRINTJOBS: [4]})

    def test_columns_found_by_name_not_position(self):
        # Dropping a column shifts all columns to its right.
        write_workbook(
            self.path,
            prints=[{"print_code": "2PP-000001", "comments": "hello"}],
            drop_headers={SHEET_PRINTJOBS: ["Design", "R"]},
        )
        data = read_protocol(self.path)
        self.assertEqual(data.prints[0].comments, "hello")
        self.assertIsNone(data.prints[0].design)
        self.assertEqual(data.missing_headers, {SHEET_PRINTJOBS: ["Design", "R"]})

    def test_missing_sheet_reported(self):
        write_workbook(self.path, sheets=["README", SHEET_PRINTJOBS, "Lists"])
        data = read_protocol(self.path)
        self.assertEqual(data.missing_sheets, [SHEET_IMAGING])
        self.assertEqual(data.imaging, [])

    def test_documentation_sheets_optional(self):
        write_workbook(self.path, sheets=[SHEET_PRINTJOBS, SHEET_IMAGING, "Lists"])
        self.assertEqual(read_protocol(self.path).missing_sheets, [])

    def test_imaging_row_is_data_if_any_input_filled(self):
        write_workbook(
            self.path,
            imaging=[
                {"print_code": "2PP-000001", "technique": "LIMI", "sample_state": "Green",
                 "imaging_date": datetime(2026, 3, 21)},
                {"substrate_permid": FAKE_SUBSTRATE_PERMID},  # formula only → not data
                {"technique": "SEM"},                          # no print code → still a row
            ],
        )
        data = read_protocol(self.path)
        self.assertEqual([e.row for e in data.imaging], [3, 5])
        self.assertEqual(data.imaging[0].imaging_date, date(2026, 3, 21))



class TestExampleWorkbook(unittest.TestCase):
    """The committed example.xlsx has every sheet and header the reader expects, and no data."""

    def test_example_matches_layout(self):
        data = read_protocol(_PROJECT_ROOT / "example.xlsx")
        self.assertEqual(data.missing_sheets, [])
        self.assertEqual(data.missing_headers, {})
        self.assertEqual(data.duplicate_headers, {})
        self.assertEqual((data.prints, data.imaging), ([], []))


if __name__ == "__main__":
    unittest.main()
