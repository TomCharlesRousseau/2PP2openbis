"""
Mapping from a Femtika run (:class:`~femtika_fill.reader.FemtikaRun`) to PrintJobs cells.

The table :data:`FILL_MAP` is data: one entry per target column, with the
function that turns the run values into the Excel value (unit conversion,
ranges, ``On`` / ``Off``). A function returns ``None`` when the run has no
value for that column. Slicing / hatching distance are only filled when the
job script sets them literally (3DPoli slices an STL); G-code jobs set them
in the slicer, so they stay manual there. Objective, R and Structures printed
are manual and never filled.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Union

from femtika_fill.reader import FemtikaRun, Range

ExcelValue = Union[str, float, int, object]

#: Separator of a range written as text, e.g. ``2.5–7.5``.
RANGE_SEPARATOR = "–"


@dataclass(frozen=True)
class Target:
    """
    One PrintJobs column filled from the run folder.

    Attributes:
        field: PrintJob field (the header comes from ``excel.column_mapping``).
        value: Run → Excel value, or None if the run has no value.
        source: Where the value comes from (for the summary of missing values).
        note: ``FemtikaRun.notes`` key explaining an expected empty value, if any.
    """

    field: str
    value: Callable[[FemtikaRun], Optional[ExcelValue]]
    source: str
    note: Optional[str] = None


def number(value: Optional[float], digits: int) -> Optional[Union[int, float]]:
    """*value* rounded to *digits*; a whole number becomes an int (``10.0`` → ``10``)."""
    if value is None:
        return None
    rounded = round(value, digits)
    return int(rounded) if float(rounded).is_integer() else rounded


def range_value(values: Optional[Range], factor: float = 1.0,
                digits: int = 3) -> Optional[Union[int, float, str]]:
    """
    A (min, max) range as Excel value: the number if min = max, else text ``min–max``.

    Args:
        values: (min, max) in file units, or None.
        factor: Unit conversion applied to both ends (e.g. µm/s → mm/s = 1/1000).
        digits: Rounding.
    """
    if values is None:
        return None
    low, high = (number(v * factor, digits) for v in values)
    return low if low == high else f"{low}{RANGE_SEPARATOR}{high}"


def on_off(flag: Optional[bool]) -> Optional[str]:
    """True / False as the ``On`` / ``Off`` list values of the workbook."""
    return None if flag is None else ("On" if flag else "Off")


def _position(run: FemtikaRun, bound: str, axis: str) -> Optional[Union[int, float]]:
    positions = run.printed_min_um if bound == "min" else run.printed_max_um
    return None if positions is None else number(positions[axis], 3)


def _minutes(run: FemtikaRun) -> Optional[Union[int, float]]:
    return None if run.duration_s is None else number(run.duration_s / 60, 2)


FILL_MAP: List[Target] = [
    Target("print_date", lambda r: r.start, "timing.json start"),
    Target("max_laser_power_mw", lambda r: number(r.max_power_mw, 3), "calibration.json max_power_mW"),
    Target("laser_power_mw", lambda r: range_value(r.laser_power_mw), "structure.json ATT (W axis)"),
    Target("scan_speed_mm_s", lambda r: range_value(r.scan_speed_um_s, 1 / 1000),
           "structure.txt STAGE VELOCITIES (shutter open)"),
    Target("infinite_fov", lambda r: on_off(r.infinite_fov), "ST12_ATT_SH_FC_Aerotech.ini IFOV"),
    Target("tilt_compensation", lambda r: on_off(r.tilt_compensation),
           "3DPoliFabrication.ini Sample enable TC"),
    Target("slicing_distance_um", lambda r: range_value(r.slicing_um),
           "Script.txt SetSlicing", note="slicing_um"),
    Target("hatching_distance_um", lambda r: range_value(r.hatching_um),
           "Script.txt SetHatching", note="hatching_um"),
    Target("tilt_alpha_deg", lambda r: number(r.tilt_alpha_deg, 3), "structure.json tilt_alpha_deg"),
    Target("tilt_beta_deg", lambda r: number(r.tilt_beta_deg, 3), "structure.json tilt_beta_deg"),
    Target("print_duration_min", _minutes, "timing.json duration_s"),
    Target("z_start_um", lambda r: _position(r, "min", "Z"), "structure.json TOT.SO_min_um"),
    Target("z_end_um", lambda r: _position(r, "max", "Z"), "structure.json TOT.SO_max_um"),
    Target("x_start_um", lambda r: _position(r, "min", "X"), "structure.json TOT.SO_min_um"),
    Target("x_end_um", lambda r: _position(r, "max", "X"), "structure.json TOT.SO_max_um"),
    Target("y_start_um", lambda r: _position(r, "min", "Y"), "structure.json TOT.SO_min_um"),
    Target("y_end_um", lambda r: _position(r, "max", "Y"), "structure.json TOT.SO_max_um"),
]
