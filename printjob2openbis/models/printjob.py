"""
PrintJob model: one row of the PrintJobs sheet = one print and its post-processing.

Field names match :data:`excel.column_mapping.PRINTJOB_COLUMNS`. All fields
hold raw cell values (see :mod:`models.cell`); nothing is validated here.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Optional

from models.cell import CellValue, is_no
from models.run import StepEntry, StepKind

PRINT_STATUS_OK = "OK"
PRINT_STATUS_PARTIAL = "Partial"
PRINT_STATUS_FAILED = "Failed"
PRINT_STATUSES = (PRINT_STATUS_OK, PRINT_STATUS_PARTIAL, PRINT_STATUS_FAILED)

#: Prefix of the 3DPoli job object code.
POLI_CODE_PREFIX = "2PP_POLI_"

#: German letters transliterated before the accents of other letters are dropped.
_TRANSLITERATION = {"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS"}


def poli_job_file_name(path: str) -> str:
    """
    File name of a 3DPoli job file path (Windows or POSIX separators).

    Example: ``\\\\share\\2PP\\Array v1.txt`` → ``Array v1.txt``.
    """
    return PureWindowsPath(path.strip()).name


def poli_code_from_filename(name: str) -> str:
    """
    openBIS code of a 3DPoli job object, derived from the job file name.

    The ``.txt`` extension is removed, the rest is uppercased; umlauts are
    transliterated (Ä → AE …), accents dropped, spaces become ``_`` and any
    character outside ``A-Z 0-9 _ - .`` is removed.

    Example: ``20260303_Array mit Text Logo und QR Code-fix2.txt``
    → ``2PP_POLI_20260303_ARRAY_MIT_TEXT_LOGO_UND_QR_CODE-FIX2``.

    Args:
        name: File name (not a path), e.g. from :func:`poli_job_file_name`.

    Returns:
        The code; only the prefix if nothing usable is left of the name.
    """
    stem = name[:-4] if name.lower().endswith(".txt") else name
    text = stem.upper()
    for letter, replacement in _TRANSLITERATION.items():
        text = text.replace(letter, replacement)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^A-Z0-9_.\-]", "", text)
    return f"{POLI_CODE_PREFIX}{text}"


@dataclass
class PrintJob:
    """One PrintJobs row. ``row`` is the Excel row number (1-based)."""

    row: int

    # General
    print_code: CellValue = None
    print_name: CellValue = None
    print_date: CellValue = None
    print_operator: CellValue = None
    design: CellValue = None
    poli_job_file: CellValue = None
    purpose: CellValue = None
    print_status: CellValue = None

    # Materials
    resin_name: CellValue = None
    resin_permid: CellValue = None
    substrate_name: CellValue = None
    substrate_permid: CellValue = None
    spacer_type: CellValue = None
    spacer_count: CellValue = None
    spacer_thickness_mm: CellValue = None

    # Printer files
    femtika_output_folder: CellValue = None

    # Printer settings
    objective: CellValue = None
    r: CellValue = None
    max_laser_power_mw: CellValue = None
    laser_power_mw: CellValue = None
    scan_speed_mm_s: CellValue = None
    slicing_distance_um: CellValue = None
    hatching_distance_um: CellValue = None
    infinite_fov: CellValue = None
    tilt_compensation: CellValue = None
    tilt_alpha_deg: CellValue = None
    tilt_beta_deg: CellValue = None
    print_duration_min: CellValue = None
    structures_printed: CellValue = None

    # Print geometry
    z_start_um: CellValue = None
    z_end_um: CellValue = None
    z_height_um: CellValue = None
    x_start_um: CellValue = None
    x_end_um: CellValue = None
    x_width_um: CellValue = None
    y_start_um: CellValue = None
    y_end_um: CellValue = None
    y_depth_um: CellValue = None

    # Washing
    washing_date: CellValue = None
    washing_run_id: CellValue = None
    washing_operator: CellValue = None
    washing_solvent: CellValue = None
    washing_duration_min: CellValue = None

    # Drying (CPD)
    cpd_date: CellValue = None
    cpd_run_id: CellValue = None
    cpd_operator: CellValue = None
    cpd_program: CellValue = None

    # Sintering
    sintering_date: CellValue = None
    sintering_run_id: CellValue = None
    sintering_operator: CellValue = None
    furnace_name: CellValue = None
    furnace_permid: CellValue = None
    furnace_program: CellValue = None
    max_temperature_c: CellValue = None
    dwell_time_h: CellValue = None
    sintering_profile_file: CellValue = None

    # openBIS / Notes
    openbis_upload: CellValue = None
    comments: CellValue = None

    # ── Status ──────────────────────────────────────────────────────────────

    @property
    def upload_disabled(self) -> bool:
        """True if ``openBIS upload`` is ``No`` (row ignored everywhere)."""
        return is_no(self.openbis_upload)

    @property
    def is_failed(self) -> bool:
        """True if Print status is ``Failed`` (print step only, no samples)."""
        return self.print_status == PRINT_STATUS_FAILED

    # ── Post-processing ─────────────────────────────────────────────────────

    def step(self, kind: StepKind) -> StepEntry:
        """
        Return this print's values for one post-processing step.

        The entry is returned even if the step date is empty (check
        ``StepEntry.exists``), so the checker can see a run ID without date.
        """
        return StepEntry(
            kind=kind,
            print_code=self.print_code,
            row=self.row,
            date=getattr(self, f"{kind.key}_date"),
            run_id=getattr(self, f"{kind.key}_run_id"),
            operator=getattr(self, f"{kind.key}_operator"),
            attributes={name: getattr(self, name) for name in kind.own_fields},
        )

    # ── openBIS codes ───────────────────────────────────────────────────────

    @property
    def print_step_code(self) -> str:
        """Code of the print step (the print code, uppercase)."""
        return str(self.print_code).upper()

    @property
    def printed_sample_code(self) -> str:
        """Code of the printed (green) sample, e.g. ``2PP_PRINTED_2PP-000001``."""
        return f"2PP_PRINTED_{self.print_code}".upper()

    @property
    def sintered_sample_code(self) -> str:
        """Code of the sintered sample, e.g. ``2PP_SINTERED_2PP-000001``."""
        return f"2PP_SINTERED_{self.print_code}".upper()

    @property
    def poli_job_code(self) -> Optional[str]:
        """Code of the 3DPoli job object, e.g. ``2PP_POLI_ARRAY_V1``, or None if no job file."""
        if self.poli_job_file is None:
            return None
        return poli_code_from_filename(poli_job_file_name(str(self.poli_job_file)))

    def run_code(self, kind: StepKind) -> Optional[str]:
        """Code of the shared *kind* step this print belongs to, or None if no run ID."""
        run_id = getattr(self, f"{kind.key}_run_id")
        return f"2PP_{run_id}".upper() if run_id is not None else None
