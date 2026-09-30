"""
Reader for one Femtika / 3DPoli output folder (one print run).

Each run creates a folder ``<job name>_<YYYYMMDD>_<HHMMSS>/`` holding the job
script, timing, structure and calibration files and the device settings.
:func:`read_run_folder` extracts the values the print protocol needs, in the
units of the files (µm, µm/s, mW, s). Converting them to Excel values is the
job of the mapping, not of the reader.

Never raises for a missing or unreadable file: the value stays ``None`` and
the problem is recorded in :attr:`FemtikaRun.problems`.

Conventions of the files (verified on a real run folder):

- JSON / text files are UTF-8 with a BOM and Windows line ends.
- SO = shutter open (what was printed), SC = shutter closed (travel moves).
- The laser power is the attenuator axis ``W`` (``structure.json`` → ``ATT``), in mW.
"""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

TIMING_FILE = "timing.json"
STRUCTURE_JSON = "structure.json"
STRUCTURE_TXT = "structure.txt"
CALIBRATION_FILE = "calibration.json"
SCRIPT_FILE = "Script.txt"
FABRICATION_INI = "3DPoliFabrication.ini"
STAGES_INI = "ST12_ATT_SH_FC_Aerotech.ini"

#: Files the reader uses; any of them missing is reported.
EXPECTED_FILES = (TIMING_FILE, STRUCTURE_JSON, STRUCTURE_TXT, CALIBRATION_FILE,
                  SCRIPT_FILE, FABRICATION_INI, STAGES_INI)

#: ``.ini`` keys read.
TILT_COMPENSATION_KEY = "Sample enable TC"
INFINITE_FOV_KEY = "Use infinite Field Of View (IFOV)?"

AXES = ("X", "Y", "Z")

#: Folder of the 3DPoli job files, on the printer PCs and on the share.
JOB_FOLDER = "Experimente chronologisch"

#: Motion stages of the STAGE VELOCITIES table (``PW`` = power axes, not a scan speed).
SPEED_STAGES = ("XYZ", "ABC")

#: (min, max) of a value that may change during a run (parameter sweep).
Range = Tuple[float, float]


@dataclass
class FemtikaRun:
    """
    Values of one run folder; ``None`` = not found (see :attr:`problems`).

    Attributes:
        folder: The run folder.
        files: File names found in the folder.
        missing_files: Expected files that are not there.
        problems: Human-readable reasons for values that could not be read.
        start / end: Run start / end (``timing.json``).
        duration_s: Run duration in seconds.
        aborted: True if the run was aborted.
        max_power_mw: Maximal laser power from the power calibration.
        laser_power_mw: (min, max) of the laser power (W axis) during the run.
        scan_speed_um_s: (min, max) velocity of the stages while the shutter was open.
        tilt_alpha_deg / tilt_beta_deg: Sample tilt angles.
        tilt_compensation: Tilt compensation enabled.
        infinite_fov: Infinite field of view (IFOV) enabled.
        printed_min_um / printed_max_um: Absolute stage position (X, Y, Z) range
            while the shutter was open (``TOT`` = stages + galvo).
        job_name: Job name (``Script.txt`` line 1).
        job_source_path: Path of the job file on the printer PC (``Script.txt`` line 2).
        slicing_um / hatching_um: (min, max) of the literal distances set with
            ``SetSlicing`` / ``SetHatching`` in the job script (3DPoli slices an STL).
        notes: Why a value is empty although nothing is wrong (field → reason),
            e.g. the job imports G-code, so slicing / hatching are in the G-code file.
        job_file: Network path of the job file; set by the fill from
            :attr:`job_source_path` with :func:`job_file_on_share` (needs the share root).
    """

    folder: Path
    files: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    duration_s: Optional[float] = None
    aborted: Optional[bool] = None
    max_power_mw: Optional[float] = None
    laser_power_mw: Optional[Range] = None
    scan_speed_um_s: Optional[Range] = None
    tilt_alpha_deg: Optional[float] = None
    tilt_beta_deg: Optional[float] = None
    tilt_compensation: Optional[bool] = None
    infinite_fov: Optional[bool] = None
    printed_min_um: Optional[Dict[str, float]] = None
    printed_max_um: Optional[Dict[str, float]] = None
    job_name: Optional[str] = None
    job_source_path: Optional[str] = None
    slicing_um: Optional[Range] = None
    hatching_um: Optional[Range] = None
    notes: Dict[str, str] = field(default_factory=dict)
    job_file: Optional[Path] = None


def resolve_run_folder(cell_value: str, logs_dir: Optional[Path]) -> Path:
    """
    Run folder of a ``Femtika output folder`` cell.

    A full path is used as is; a bare folder name (e.g.
    ``20260623_Pause-Modulation_v02-3_20260629_151101``) is looked up in *logs_dir*.

    Args:
        cell_value: Cell text.
        logs_dir: Folder holding all run folders, or None if not configured.

    Returns:
        The folder path (not checked for existence).
    """
    text = cell_value.strip().strip('"')
    windows = PureWindowsPath(text)
    is_bare_name = len(windows.parts) == 1 and "/" not in text
    if is_bare_name and logs_dir is not None:
        return Path(logs_dir) / text
    return Path(text)


def job_file_on_share(source_path: Optional[str],
                      share_root: Optional[Path]) -> Tuple[Optional[Path], Optional[str]]:
    """
    Network path of the 3DPoli job file given by ``Script.txt`` (path on a printer PC).

    The printer PCs keep the jobs in a folder ``Experimente chronologisch`` that is
    mirrored on the share: the part of the path from that folder on is put behind
    *share_root*. E.g. ``C:\\Users\\<user>\\Documents\\Experimente chronologisch\\X.txt``
    → ``<share_root>\\Experimente chronologisch\\X.txt``.

    Args:
        source_path: Path from the ``Source:`` line, or None.
        share_root: Folder on the share holding ``Experimente chronologisch``, or None.

    Returns:
        (path, None) if the file exists on the share, else (None, reason).
    """
    if not source_path:
        return None, "no job file path in Script.txt (script not saved?)"
    if share_root is None:
        return None, "share root not configured (femtika.job_share_root)"
    parts = PureWindowsPath(source_path).parts
    index = next((i for i, part in enumerate(parts) if part.lower() == JOB_FOLDER.lower()), None)
    if index is None:
        return None, f"job file is not in '{JOB_FOLDER}' on the printer PC: fill by hand"
    path = Path(share_root).joinpath(JOB_FOLDER, *parts[index + 1:])
    if not path.is_file():
        return None, f"job file not found on the share: {path}"
    return path, None


def read_run_folder(folder: Path) -> FemtikaRun:
    """
    Read every value the print protocol needs from one run folder.

    Args:
        folder: The run folder.

    Returns:
        The values; missing files / values are listed in ``missing_files`` / ``problems``.
    """
    folder = Path(folder)
    run = FemtikaRun(folder=folder)
    if not folder.is_dir():
        run.problems.append(f"Folder not found: {folder}")
        run.missing_files = list(EXPECTED_FILES)
        return run
    run.files = sorted(p.name for p in folder.iterdir() if p.is_file())
    run.missing_files = [name for name in EXPECTED_FILES if name not in run.files]

    for reader in (_read_timing, _read_structure_json, _read_structure_txt,
                   _read_calibration, _read_script, _read_ini_files):
        reader(run)
    return run


# ── File readers ─────────────────────────────────────────────────────────────

def _load_json(run: FemtikaRun, name: str) -> Optional[Dict[str, Any]]:
    """JSON content of *name*, or None (problem recorded) if missing / invalid."""
    if name in run.missing_files:
        return None
    try:
        return json.loads((run.folder / name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        run.problems.append(f"{name}: cannot be read ({exc})")
        return None


def _load_text(run: FemtikaRun, name: str) -> Optional[str]:
    """Text of *name*, or None (problem recorded) if missing / unreadable."""
    if name in run.missing_files:
        return None
    try:
        return (run.folder / name).read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        run.problems.append(f"{name}: cannot be read ({exc})")
        return None


def _number(run: FemtikaRun, source: str, value: Any) -> Optional[float]:
    """*value* as float, or None (problem recorded) if it is not a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        run.problems.append(f"{source}: '{value}' is not a number")
        return None
    return number if math.isfinite(number) else None


def _dig(data: Dict[str, Any], *keys: str) -> Any:
    """``data[k1][k2]…`` or None if a key is missing."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _read_timing(run: FemtikaRun) -> None:
    """Start, end, duration and aborted flag."""
    data = _load_json(run, TIMING_FILE)
    if data is None:
        return
    for attr in ("start", "end"):
        value = data.get(attr)
        try:
            setattr(run, attr, datetime.fromisoformat(value) if value else None)
        except (TypeError, ValueError):
            run.problems.append(f"{TIMING_FILE}: {attr} '{value}' is not a date/time")
    if data.get("duration_s") is not None:
        run.duration_s = _number(run, f"{TIMING_FILE} duration_s", data["duration_s"])
    if isinstance(data.get("aborted"), bool):
        run.aborted = data["aborted"]


def _read_structure_json(run: FemtikaRun) -> None:
    """Tilt angles, printed position range (TOT, shutter open), laser power range (ATT)."""
    data = _load_json(run, STRUCTURE_JSON)
    if data is None:
        return
    for attr, key in (("tilt_alpha_deg", "tilt_alpha_deg"), ("tilt_beta_deg", "tilt_beta_deg")):
        if data.get(key) is not None:
            setattr(run, attr, _number(run, f"{STRUCTURE_JSON} {key}", data[key]))

    if _dig(data, "TOT", "SO_min_um") == {}:
        run.problems.append(f"{STRUCTURE_JSON}: the shutter never opened (nothing printed)")
        return
    for attr, key in (("printed_min_um", "SO_min_um"), ("printed_max_um", "SO_max_um")):
        position = _dig(data, "TOT", key)
        if isinstance(position, dict) and all(axis in position for axis in AXES):
            values = {axis: _number(run, f"{STRUCTURE_JSON} TOT.{key}.{axis}", position[axis])
                      for axis in AXES}
            if all(v is not None for v in values.values()):
                setattr(run, attr, values)
        else:
            run.problems.append(f"{STRUCTURE_JSON}: TOT.{key} not found")

    low, high = _dig(data, "ATT", "SC_min_um", "Z"), _dig(data, "ATT", "SC_max_um", "Z")
    if low is not None and high is not None:
        low_n = _number(run, f"{STRUCTURE_JSON} ATT.SC_min_um.Z", low)
        high_n = _number(run, f"{STRUCTURE_JSON} ATT.SC_max_um.Z", high)
        if low_n is not None and high_n is not None:
            run.laser_power_mw = (low_n, high_n)
    else:
        run.problems.append(f"{STRUCTURE_JSON}: laser power (ATT.SC_min_um / SC_max_um Z) not found")


#: One row of the STAGE VELOCITIES table: stage | initial final | min max delta (SC) | min max delta (SO).
_VELOCITY_ROW = re.compile(r"^\s*(\S+)\s*\|([^|]*)\|([^|]*)\|([^|]*)$")


def _read_structure_txt(run: FemtikaRun) -> None:
    """Scan speed: min / max SO velocity over the motion stages that moved with the shutter open."""
    text = _load_text(run, STRUCTURE_TXT)
    if text is None:
        return
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "STAGE VELOCITIES" in line)
    except StopIteration:
        run.problems.append(f"{STRUCTURE_TXT}: STAGE VELOCITIES table not found")
        return
    lows: List[float] = []
    highs: List[float] = []
    for line in lines[start + 2:]:  # skip the title and the column header
        match = _VELOCITY_ROW.match(line)
        if not match:
            break
        if match.group(1) not in SPEED_STAGES:
            continue
        so = match.group(4).split()
        if len(so) < 2 or "NAN" in (so[0].upper(), so[1].upper()):
            continue
        low = _number(run, f"{STRUCTURE_TXT} {match.group(1)} MinSO", so[0])
        high = _number(run, f"{STRUCTURE_TXT} {match.group(1)} MaxSO", so[1])
        if low is not None and high is not None:
            lows.append(low)
            highs.append(high)
    if lows:
        run.scan_speed_um_s = (min(lows), max(highs))
    else:
        run.problems.append(f"{STRUCTURE_TXT}: no stage velocity with the shutter open")


def _read_calibration(run: FemtikaRun) -> None:
    """Maximal laser power of the power calibration."""
    data = _load_json(run, CALIBRATION_FILE)
    if data is None:
        return
    if data.get("max_power_mW") is not None:
        run.max_power_mw = _number(run, f"{CALIBRATION_FILE} max_power_mW", data["max_power_mW"])
    else:
        run.problems.append(f"{CALIBRATION_FILE}: max_power_mW not found")


#: ``{ <job name> }`` and ``{ Source: <path> }`` header lines of Script.txt.
_BRACED = re.compile(r"^\s*\{\s*(.*?)\s*\}\s*$")


def _read_script(run: FemtikaRun) -> None:
    """Job name (line 1) and job file path on the printer PC (line 2)."""
    text = _load_text(run, SCRIPT_FILE)
    if text is None:
        return
    lines = text.splitlines()
    name = _BRACED.match(lines[0]) if lines else None
    source = _BRACED.match(lines[1]) if len(lines) > 1 else None
    if name:
        run.job_name = name.group(1)
    if source and source.group(1).lower().startswith("source:"):
        run.job_source_path = source.group(1)[len("source:"):].strip()
    else:
        run.problems.append(f"{SCRIPT_FILE}: no 'Source:' line with the job file path")
    _read_slicing_hatching(run, lines[2:])


#: ``{...}`` parameter labels 3DPoli writes inside calls, e.g. ``SetSlicing({dZ} -0.2, …)``.
_LABEL = re.compile(r"\{[^}]*\}")


def _call_arguments(lines: List[str], function: str) -> List[List[str]]:
    """Arguments of every call of *function* in code lines (``//`` comments and labels removed)."""
    pattern = re.compile(rf"\b{function}\s*\(([^)]*)\)", re.IGNORECASE)
    calls: List[List[str]] = []
    for line in lines:
        code = line.split("//", 1)[0]
        for match in pattern.finditer(code):
            calls.append([arg.strip() for arg in _LABEL.sub("", match.group(1)).split(",")])
    return calls


def _read_slicing_hatching(run: FemtikaRun, lines: List[str]) -> None:
    """
    Slicing / hatching distance set literally in the job script (3DPoli slices an STL).

    ``SetSlicing(dZ, …)``: layer distance = |dZ| (negative = slicing direction).
    ``SetHatching(mode, distance, …)``: line distance. Several calls give a range.
    Jobs that import G-code set these in the slicer (the G-code file), and jobs
    that draw lines directly have none; both are recorded in :attr:`FemtikaRun.notes`.
    """
    uses_gcode = bool(_call_arguments(lines, "ImportGCode"))
    for attr, function, index in (("slicing_um", "SetSlicing", 0), ("hatching_um", "SetHatching", 1)):
        values: List[float] = []
        variable = False
        for args in _call_arguments(lines, function):
            try:
                values.append(abs(float(args[index])))
            except (IndexError, ValueError):
                variable = True  # e.g. SetSlicing($dz, …): value only known when the job runs
        if values:
            setattr(run, attr, (min(values), max(values)))
        elif variable:
            run.notes[attr] = f"{function} uses a variable in the job script: fill by hand"
        elif uses_gcode:
            run.notes[attr] = "job imports G-code (set in the slicer): fill by hand"
        else:
            run.notes[attr] = f"no {function} in the job script (no slicing)"


def _ini_values(run: FemtikaRun, name: str) -> Optional[Dict[str, str]]:
    """
    ``key → value`` of an .ini file (first occurrence, sections ignored).

    Split on the first ``=`` only: keys may contain ``:`` (e.g. ``IFOV: field of view``).
    """
    text = _load_text(run, name)
    if text is None:
        return None
    values: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip())
    return values


def _flag(run: FemtikaRun, source: str, value: Optional[str]) -> Optional[bool]:
    """``1`` / ``0`` as bool, or None (problem recorded)."""
    if value in ("1", "0"):
        return value == "1"
    run.problems.append(f"{source}: expected 1 or 0, found {value!r}")
    return None


def _read_ini_files(run: FemtikaRun) -> None:
    """Tilt compensation (3DPoliFabrication.ini) and infinite FOV (stage settings)."""
    fabrication = _ini_values(run, FABRICATION_INI)
    if fabrication is not None:
        run.tilt_compensation = _flag(run, f"{FABRICATION_INI} '{TILT_COMPENSATION_KEY}'",
                                      fabrication.get(TILT_COMPENSATION_KEY))
    stages = _ini_values(run, STAGES_INI)
    if stages is not None:
        run.infinite_fov = _flag(run, f"{STAGES_INI} '{INFINITE_FOV_KEY}'",
                                 stages.get(INFINITE_FOV_KEY))
