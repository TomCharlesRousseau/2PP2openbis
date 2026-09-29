"""Tests for femtika_fill.reader (synthetic run folders, made-up values)."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from femtika_fill.reader import EXPECTED_FILES, read_run_folder, resolve_run_folder

BOM = "\ufeff"

STRUCTURE_TXT = """STRUCTURE INFORMATION
============================================
Compilation Time 0.100s

*** STAGE VELOCITIES ***
    Stage |      Initial        Final |        MinSC        MaxSC      DeltaSC |        MinSO        MaxSO      DeltaSO
      XYZ |      100.000     1000.000 |     1000.000     1000.000        0.000 |          NAN          NAN          NAN
      ABC |      100.000     3000.000 |     1000.000     3000.000     2000.000 | {abc_min}     {abc_max}     2000.000
       PW |      100.000      100.000 |      100.000      100.000        0.000 |      100.000      100.000        0.000

*** BUILDING VOLUME ***
"""


#: Job script body: 3DPoli slices an STL with literal slicing / hatching distances.
DEFAULT_BODY = r"""
$power := 5
// SetSlicing(-9, 0, 0, 0)   commented out: ignored
SetSlicing({dZ} -0.25, {Partial?} 0, {PartialFrom} 0, {PartialTo} 1);
SetHatching(hsXYcenter, 0.5, 0, 0)
STL(ABC, "C:\jobs\part.stl", rMid, rMid, rMax, -1, -1, 8, 0, 0, 0)
"""

#: Job script body: the structure comes from an imported G-code file.
GCODE_BODY = r"""
ImportGCode({table index} 1, "C:\gcode\cube.gcode")
RunImportedGCode({index} 1, {Stages} ABC)
"""


def _position(x: float, y: float, z: float) -> Dict[str, float]:
    return {"X": x, "Y": y, "Z": z}


def write_run(folder: Path, skip: tuple = (), abc_min: str = "1000.000",
              abc_max: str = "3000.000", aborted: bool = False,
              power: tuple = (2.5, 7.5), source: Optional[str] =
              r"C:\Users\printer\Documents\Experimente chronologisch\Test job.txt",
              body: str = None) -> Path:
    """A synthetic run folder in the Femtika formats (UTF-8 with BOM, CRLF)."""
    folder.mkdir(parents=True, exist_ok=True)
    body = DEFAULT_BODY if body is None else body
    files = {
        "timing.json": json.dumps({"start": "2026-01-02T10:00:00", "end": "2026-01-02T10:30:00",
                                   "duration_s": 1800.0, "aborted": aborted}, indent=4),
        "structure.json": json.dumps({
            "est_time_s": 1700.0, "tilt_alpha_deg": -1.5, "tilt_beta_deg": 0.5,
            "TOT": {"SO_min_um": _position(-100.0, -50.0, 1000.0),
                    "SO_max_um": _position(100.0, 50.0, 1010.0)},
            "ATT": {"SC_min_um": {"X": 2.0, "Y": 0.0, "Z": power[0]},
                    "SC_max_um": {"X": 2.0, "Y": 0.0, "Z": power[1]}},
        }, indent=4),
        "structure.txt": STRUCTURE_TXT.format(abc_min=abc_min, abc_max=abc_max),
        "calibration.json": json.dumps({"max_power_mW": 12.0, "power_mW": [0.1, 12.0]}, indent=4),
        "Script.txt": "{ Test job }\n" + (f"{{ Source: {source} }}\n" if source else "") + body,
        "3DPoliFabrication.ini": "[STANDARDSETTINGS-GENERAL]\nSample alpha deg=-1.5\nSample enable TC=1\n"
                                 "; comment=ignored\nNAS Password=\n",
        "ST12_ATT_SH_FC_Aerotech.ini": "[CUSTOMSETTINGS-STAGES2]\nIFOV: field of view size [um]=150\n"
                                       "Use infinite Field Of View (IFOV)?=0\n"
                                       "Use infinite Field Of View (IFOV)?-Type=YESNO\n",
        "FC0.PGM": "G1 A0 B0\n",
    }
    for name, text in files.items():
        if name not in skip:
            (folder / name).write_bytes((BOM + text).replace("\n", "\r\n").encode("utf-8"))
    return folder


class TestReadRunFolder(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_values(self):
        run = read_run_folder(write_run(self.root / "Test job_20260102_100000"))
        self.assertEqual(run.missing_files, [])
        self.assertEqual(run.problems, [])
        self.assertEqual(run.start, datetime(2026, 1, 2, 10, 0))
        self.assertEqual(run.end, datetime(2026, 1, 2, 10, 30))
        self.assertEqual(run.duration_s, 1800.0)
        self.assertFalse(run.aborted)
        self.assertEqual(run.max_power_mw, 12.0)
        self.assertEqual(run.laser_power_mw, (2.5, 7.5))
        self.assertEqual(run.scan_speed_um_s, (1000.0, 3000.0))  # ABC only: XYZ is NAN, PW ignored
        self.assertEqual((run.tilt_alpha_deg, run.tilt_beta_deg), (-1.5, 0.5))
        self.assertTrue(run.tilt_compensation)
        self.assertFalse(run.infinite_fov)
        self.assertEqual(run.printed_min_um, {"X": -100.0, "Y": -50.0, "Z": 1000.0})
        self.assertEqual(run.printed_max_um, {"X": 100.0, "Y": 50.0, "Z": 1010.0})
        self.assertEqual(run.job_name, "Test job")
        self.assertEqual(run.job_source_path,
                         r"C:\Users\printer\Documents\Experimente chronologisch\Test job.txt")

    def test_single_value_is_min_equals_max(self):
        run = read_run_folder(write_run(self.root / "r", power=(8.0, 8.0),
                                        abc_min="10000.000", abc_max="10000.000"))
        self.assertEqual(run.laser_power_mw, (8.0, 8.0))
        self.assertEqual(run.scan_speed_um_s, (10000.0, 10000.0))

    def test_aborted(self):
        self.assertTrue(read_run_folder(write_run(self.root / "r", aborted=True)).aborted)

    def test_missing_files_leave_values_empty(self):
        run = read_run_folder(write_run(self.root / "r", skip=("calibration.json", "structure.txt")))
        self.assertEqual(run.missing_files, ["structure.txt", "calibration.json"])
        self.assertIsNone(run.max_power_mw)
        self.assertIsNone(run.scan_speed_um_s)
        self.assertEqual(run.laser_power_mw, (2.5, 7.5))  # other files still read

    def test_folder_not_found(self):
        run = read_run_folder(self.root / "nope")
        self.assertEqual(run.missing_files, list(EXPECTED_FILES))
        self.assertIn("Folder not found", run.problems[0])

    def test_invalid_json_is_a_problem_not_an_exception(self):
        folder = write_run(self.root / "r")
        (folder / "timing.json").write_text("{ broken", encoding="utf-8")
        run = read_run_folder(folder)
        self.assertIsNone(run.start)
        self.assertIn("timing.json", run.problems[0])

    def test_no_speed_with_shutter_open(self):
        run = read_run_folder(write_run(self.root / "r", abc_min="NAN", abc_max="NAN"))
        self.assertIsNone(run.scan_speed_um_s)
        self.assertIn("no stage velocity", run.problems[0])

    def test_nothing_printed(self):
        folder = write_run(self.root / "r", abc_min="NAN", abc_max="NAN")
        data = json.loads((folder / "structure.json").read_text(encoding="utf-8-sig"))
        data["TOT"] = {"SO_min_um": {}, "SO_max_um": {}}
        data["ATT"] = {"SO_min_um": {}, "SC_min_um": {"X": 1.0, "Y": 0.0}}
        (folder / "structure.json").write_text(json.dumps(data), encoding="utf-8")
        run = read_run_folder(folder)
        self.assertIsNone(run.printed_min_um)
        self.assertIsNone(run.laser_power_mw)
        self.assertIn("shutter never opened", run.problems[0])

    def test_slicing_and_hatching_from_script(self):
        run = read_run_folder(write_run(self.root / "r"))
        self.assertEqual((run.slicing_um, run.hatching_um), ((0.25, 0.25), (0.5, 0.5)))
        self.assertEqual(run.notes, {})

    def test_several_slicing_values_give_a_range(self):
        body = "SetSlicing(-0.2, 0, 0, 0)\nSetSlicing(-0.4, 0, 0, 0)\nSetHatching(hsXY, 0.3, 0, 0)\n"
        run = read_run_folder(write_run(self.root / "r", body=body))
        self.assertEqual(run.slicing_um, (0.2, 0.4))

    def test_gcode_job_has_a_note(self):
        run = read_run_folder(write_run(self.root / "r", body=GCODE_BODY))
        self.assertIsNone(run.slicing_um)
        self.assertIn("G-code", run.notes["slicing_um"])
        self.assertIn("G-code", run.notes["hatching_um"])

    def test_variable_and_no_slicing(self):
        body = "SetSlicing($dz, 0, 0, 0)\nLineA(ABC, 1, 2, 3)\n"
        run = read_run_folder(write_run(self.root / "r", body=body))
        self.assertIn("variable", run.notes["slicing_um"])
        self.assertIn("no SetHatching", run.notes["hatching_um"])

    def test_script_without_source_line(self):
        run = read_run_folder(write_run(self.root / "r", source=None))
        self.assertEqual(run.job_name, "Test job")
        self.assertIsNone(run.job_source_path)
        self.assertIn("Source:", run.problems[0])


class TestResolveRunFolder(unittest.TestCase):

    def test_bare_name_is_looked_up_in_logs_dir(self):
        logs = Path("logs")
        self.assertEqual(resolve_run_folder("Job_20260102_100000", logs), logs / "Job_20260102_100000")

    def test_full_path_used_as_is(self):
        path = r"\\server\share\logs\Job_20260102_100000"
        self.assertEqual(resolve_run_folder(f' "{path}" ', Path("logs")), Path(path))

    def test_bare_name_without_logs_dir(self):
        self.assertEqual(resolve_run_folder("Job", None), Path("Job"))


if __name__ == "__main__":
    unittest.main()
