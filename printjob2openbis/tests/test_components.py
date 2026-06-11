"""
Unit tests for printjob2openbis components.

Tests cover:
- PrintJob dataclass
- Column mapping
- Validators
- Description builder
- Excel parser (using an in-memory fixture)
"""

import sys
import os
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make sure the project root is on sys.path so imports work when the tests
# are run from within the printjob2openbis/ directory.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from models.printjob import PrintJob
from excel.column_mapping import COLUMN_TO_FIELD, REQUIRED_COLUMNS
from excel.description_builder import build_description
from utils.validators import is_empty, is_valid_code, is_valid_perm_id


# ── PrintJob tests ─────────────────────────────────────────────────────────────


class TestPrintJobModel(unittest.TestCase):
    """Test the PrintJob dataclass."""

    def _make_job(self, **kwargs) -> PrintJob:
        defaults = dict(name="PJ-001", code="PJ001")
        defaults.update(kwargs)
        return PrintJob(**defaults)

    def test_creation_minimal(self):
        """PrintJob can be created with only name and code."""
        job = self._make_job()
        self.assertEqual(job.name, "PJ-001")
        self.assertEqual(job.code, "PJ001")
        self.assertIsNone(job.resin_id)
        self.assertIsNone(job.substrate_id)

    def test_parent_ids_both_present(self):
        """parent_ids() returns both IDs when set."""
        job = self._make_job(resin_id="20210101-1", substrate_id="20210101-2")
        self.assertEqual(job.parent_ids(), ["20210101-1", "20210101-2"])

    def test_parent_ids_partial(self):
        """parent_ids() includes only non-None IDs."""
        job = self._make_job(resin_id="20210101-1")
        self.assertEqual(job.parent_ids(), ["20210101-1"])

    def test_parent_ids_empty(self):
        """parent_ids() returns empty list when neither parent is set."""
        job = self._make_job()
        self.assertEqual(job.parent_ids(), [])

    def test_all_optional_fields_default_none(self):
        """All optional fields default to None."""
        job = self._make_job()
        for attr in [
            "print_date", "responsible_person", "design", "poli_path",
            "spacer", "zmin", "zmax", "max_z_height",
            "xmin", "xmax", "max_x_height",
            "ymin", "ymax", "max_y_height",
            "lense", "r", "max_power", "infinite_fov",
            "tilt_alpha", "tilt_beta", "tilt_compensation",
        ]:
            self.assertIsNone(getattr(job, attr), f"{attr} should default to None")


# ── Column mapping tests ───────────────────────────────────────────────────────


class TestColumnMapping(unittest.TestCase):
    """Test the COLUMN_TO_FIELD mapping."""

    def test_required_columns_in_mapping(self):
        """All REQUIRED_COLUMNS must appear in COLUMN_TO_FIELD."""
        for col in REQUIRED_COLUMNS:
            self.assertIn(
                col,
                COLUMN_TO_FIELD,
                f"Required column '{col}' missing from COLUMN_TO_FIELD",
            )

    def test_ignored_columns_absent(self):
        """Ignored columns must not be in COLUMN_TO_FIELD."""
        for col in ("Resin Name", "Substrate Name", "F path"):
            self.assertNotIn(
                col,
                COLUMN_TO_FIELD,
                f"Ignored column '{col}' should not be in COLUMN_TO_FIELD",
            )

    def test_name_maps_to_name(self):
        self.assertEqual(COLUMN_TO_FIELD["Printjob Name #"], "name")

    def test_code_maps_to_code(self):
        self.assertEqual(COLUMN_TO_FIELD["Code"], "code")

    def test_resin_id_maps_correctly(self):
        self.assertEqual(COLUMN_TO_FIELD["Resin ID"], "resin_id")

    def test_substrate_id_maps_correctly(self):
        self.assertEqual(COLUMN_TO_FIELD["Substrate ID"], "substrate_id")

    def test_all_values_are_valid_printjob_fields(self):
        """Each mapped field must be a real PrintJob attribute."""
        dummy = PrintJob(name="x", code="y")
        for header, field in COLUMN_TO_FIELD.items():
            self.assertTrue(
                hasattr(dummy, field),
                f"COLUMN_TO_FIELD maps '{header}' → '{field}' but PrintJob has no '{field}'",
            )


# ── Validator tests ────────────────────────────────────────────────────────────


class TestValidators(unittest.TestCase):
    """Test utility validator functions."""

    def test_is_empty_none(self):
        self.assertTrue(is_empty(None))

    def test_is_empty_nan_string(self):
        self.assertTrue(is_empty("nan"))
        self.assertTrue(is_empty("NaN"))

    def test_is_empty_blank(self):
        self.assertTrue(is_empty(""))
        self.assertTrue(is_empty("   "))

    def test_is_empty_none_string(self):
        self.assertTrue(is_empty("none"))

    def test_is_empty_na_string(self):
        self.assertTrue(is_empty("n/a"))

    def test_is_empty_real_value(self):
        self.assertFalse(is_empty("PJ001"))
        self.assertFalse(is_empty(42))
        self.assertFalse(is_empty("0"))

    def test_is_valid_code_valid(self):
        self.assertTrue(is_valid_code("PJ001"))

    def test_is_valid_code_invalid(self):
        self.assertFalse(is_valid_code(""))
        self.assertFalse(is_valid_code(None))
        self.assertFalse(is_valid_code("nan"))

    def test_is_valid_perm_id_valid(self):
        self.assertTrue(is_valid_perm_id("20210101000000000-12345"))

    def test_is_valid_perm_id_invalid(self):
        self.assertFalse(is_valid_perm_id(""))
        self.assertFalse(is_valid_perm_id(None))


# ── Description builder tests ──────────────────────────────────────────────────


class TestDescriptionBuilder(unittest.TestCase):
    """Test description generation from PrintJob instances."""

    def _make_job(self, **kwargs) -> PrintJob:
        defaults = dict(name="PJ-001", code="PJ001")
        defaults.update(kwargs)
        return PrintJob(**defaults)

    def test_empty_job_yields_empty_string(self):
        """A job with no optional fields produces an empty description."""
        job = self._make_job()
        self.assertEqual(build_description(job), "")

    def test_responsible_person_included(self):
        job = self._make_job(responsible_person="Tom Rousseau")
        desc = build_description(job)
        self.assertIn("Responsible person: Tom Rousseau", desc)

    def test_design_included(self):
        job = self._make_job(design="Test design")
        desc = build_description(job)
        self.assertIn("Design: Test design", desc)

    def test_spacer_included(self):
        job = self._make_job(spacer="50")
        desc = build_description(job)
        self.assertIn("Spacer: 50", desc)

    def test_z_axis_block(self):
        job = self._make_job(zmin="0", zmax="10", max_z_height="10.5")
        desc = build_description(job)
        self.assertIn("zmin: 0", desc)
        self.assertIn("zmax: 10", desc)
        self.assertIn("max z height [µm]: 10.5", desc)

    def test_x_axis_block(self):
        job = self._make_job(xmin="1", xmax="5", max_x_height="4.0")
        desc = build_description(job)
        self.assertIn("xmin: 1", desc)
        self.assertIn("xmax: 5", desc)
        self.assertIn("max x height [µm]: 4.0", desc)

    def test_y_axis_block(self):
        job = self._make_job(ymin="2", ymax="8", max_y_height="6.0")
        desc = build_description(job)
        self.assertIn("ymin: 2", desc)
        self.assertIn("ymax: 8", desc)
        self.assertIn("max y height [µm]: 6.0", desc)

    def test_optics_block(self):
        job = self._make_job(
            lense="25x",
            r="0.5",
            max_power="100",
            infinite_fov="True",
            tilt_alpha="2",
            tilt_beta="3",
            tilt_compensation="yes",
        )
        desc = build_description(job)
        self.assertIn("Lense: 25x", desc)
        self.assertIn("R: 0.5", desc)
        self.assertIn("Max power from calibration: 100", desc)
        self.assertIn("Infinite FOV: True", desc)
        self.assertIn("Tilt alpha degree: 2", desc)
        self.assertIn("Tilt beta degree: 3", desc)
        self.assertIn("Tilt compensation: yes", desc)

    def test_none_fields_omitted(self):
        """None values must not appear in the description."""
        job = self._make_job(responsible_person="Tom", lense=None)
        desc = build_description(job)
        self.assertNotIn("Lense", desc)
        self.assertIn("Responsible person: Tom", desc)

    def test_sections_separated_by_blank_lines(self):
        """Axis sections should be separated by blank lines."""
        job = self._make_job(
            spacer="50",
            zmin="0",
            xmin="1",
            ymin="2",
        )
        desc = build_description(job)
        # Blank lines between sections
        self.assertIn("\n\n", desc)

    def test_full_example(self):
        """Integration: full description matches expected format."""
        job = PrintJob(
            name="PJ-001",
            code="PJ001",
            responsible_person="Tom Rousseau",
            design="Test design",
            spacer="50",
            zmin="0",
            zmax="10",
            max_z_height="10.0",
            lense="25x",
        )
        desc = build_description(job)
        self.assertIn("Responsible person: Tom Rousseau", desc)
        self.assertIn("Design: Test design", desc)
        self.assertIn("Spacer: 50", desc)
        self.assertIn("zmin: 0", desc)
        self.assertIn("Lense: 25x", desc)


# ── Excel parser tests ─────────────────────────────────────────────────────────


class TestExcelParser(unittest.TestCase):
    """Test ExcelParser using an in-memory Excel fixture."""

    def _create_fixture(self) -> Path:
        """
        Write a minimal Excel fixture to a temp file and return its path.

        Row 1: metadata / filler (simulates the extra first row)
        Row 2: column headers
        Row 3: first data row
        Row 4: second data row with empty name+code (should be skipped)
        """
        import tempfile
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active

        # Row 1 – filler
        ws.append(["(metadata row)"])

        # Row 2 – headers (must match COLUMN_TO_FIELD keys)
        headers = [
            "Printjob Name #",  # A
            "Code",             # B
            "Print date",       # C
            "Responsible person",  # D
            "Design",           # E
            "3DPoli path",      # F
            "Resin Name",       # G  (ignored)
            "Resin ID",         # H
            "Substrate Name",   # I  (ignored)
            "Substrate ID",     # J
            "Spacer",           # K
            "",                 # L  (empty / ignored)
            "F path",           # M  (ignored)
            "zmin",             # N
            "zmax",             # O
            "max z height [µm]",  # P
            "xmin",             # Q
            "xmax",             # R
            "max x height [µm]",  # S
            "ymin",             # T
            "ymax",             # U
            "max y height [µm]",  # V
            "Lense",            # W
            "R",                # X
            "Max power from calibration",  # Y
            "Infinite FOV",     # Z
            "Tilt alpha degree",   # AA
            "Tilt beta degree",    # AB
            "Tilt compensation",   # AC
        ]
        ws.append(headers)

        # Row 3 – valid data row
        ws.append([
            "First print job",   # name
            "PJ001",             # code
            "2024-01-15",        # print_date
            "Tom Rousseau",      # responsible_person
            "My design",         # design
            "/path/to/poli",     # poli_path
            "Resin Alpha",       # Resin Name (ignored)
            "20240101-1",        # resin_id
            "Substrate Beta",    # Substrate Name (ignored)
            "20240101-2",        # substrate_id
            "50",                # spacer
            "",                  # L (empty)
            "/f/path",           # F path (ignored)
            "0.0",               # zmin
            "10.0",              # zmax
            "10.0",              # max_z_height
            "1.0",               # xmin
            "5.0",               # xmax
            "4.0",               # max_x_height
            "2.0",               # ymin
            "8.0",               # ymax
            "6.0",               # max_y_height
            "25x",               # lense
            "0.5",               # r
            "100",               # max_power
            "True",              # infinite_fov
            "2",                 # tilt_alpha
            "3",                 # tilt_beta
            "yes",               # tilt_compensation
        ])

        # Row 4 – empty row (should be skipped)
        ws.append(["", "", "", "", ""])

        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        wb.save(tmp.name)
        return Path(tmp.name)

    def setUp(self):
        self.fixture_path = self._create_fixture()

    def tearDown(self):
        try:
            self.fixture_path.unlink()
        except Exception:
            pass

    def test_parser_loads_file(self):
        from excel.excel_parser import ExcelParser
        parser = ExcelParser(self.fixture_path)
        self.assertIsNotNone(parser.df)

    def test_parse_returns_one_job(self):
        from excel.excel_parser import ExcelParser
        parser = ExcelParser(self.fixture_path)
        jobs = parser.parse()
        self.assertEqual(len(jobs), 1, "Expected exactly 1 valid print job")

    def test_parse_correct_name_and_code(self):
        from excel.excel_parser import ExcelParser
        parser = ExcelParser(self.fixture_path)
        jobs = parser.parse()
        job = jobs[0]
        self.assertEqual(job.name, "First print job")
        self.assertEqual(job.code, "PJ001")

    def test_parse_parent_ids(self):
        from excel.excel_parser import ExcelParser
        parser = ExcelParser(self.fixture_path)
        jobs = parser.parse()
        job = jobs[0]
        self.assertEqual(job.resin_id, "20240101-1")
        self.assertEqual(job.substrate_id, "20240101-2")

    def test_parse_optional_fields(self):
        from excel.excel_parser import ExcelParser
        parser = ExcelParser(self.fixture_path)
        jobs = parser.parse()
        job = jobs[0]
        self.assertEqual(job.responsible_person, "Tom Rousseau")
        self.assertEqual(job.design, "My design")
        self.assertEqual(job.spacer, "50")
        self.assertEqual(job.lense, "25x")
        self.assertEqual(job.tilt_alpha, "2")

    def test_file_not_found_raises(self):
        from excel.excel_parser import ExcelParser
        with self.assertRaises(FileNotFoundError):
            ExcelParser(Path("/nonexistent/file.xlsx"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
