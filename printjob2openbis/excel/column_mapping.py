"""
Column mapping for the 2PP print protocol (layout v5).

Each sheet is described by an ordered list of :class:`Column` entries that map
an Excel header (row 2) to a model field. Columns are always located by header
name, never by letter. The order and ``section`` of the entries follow the
workbook and are used to group values in openBIS descriptions.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# Sheet names
SHEET_PRINTJOBS = "PrintJobs"
SHEET_IMAGING = "Imaging"
#: Sheets the parser needs (Lists feeds the lookup formulas). README / Model / Columns are
#: documentation for the people filling in the workbook and are optional.
REQUIRED_SHEETS: List[str] = [SHEET_PRINTJOBS, SHEET_IMAGING, "Lists"]

# Row layout: row 1 = section band, row 2 = headers, data from row 3.
HEADER_ROW = 2
FIRST_DATA_ROW = 3

# Section names used as ``Column.section`` for post-processing steps.
SECTION_WASHING = "Washing"
SECTION_CPD = "Drying (CPD)"
SECTION_SINTERING = "Sintering"


@dataclass(frozen=True)
class Column:
    """
    One Excel column.

    Attributes:
        header: Header text in row 2 (exact, after whitespace normalisation).
        field: Attribute name on the model class.
        section: Section of the sheet the column belongs to (row-1 band).
        formula: True for grey formula columns (value read from Excel's cache).
    """

    header: str
    field: str
    section: str
    formula: bool = False


PRINTJOB_COLUMNS: List[Column] = [
    # General
    Column("Print code", "print_code", "General"),
    Column("Print name", "print_name", "General", formula=True),
    Column("Print date", "print_date", "General"),
    Column("Print operator", "print_operator", "General"),
    Column("Design", "design", "General"),
    Column("3DPoli job file", "poli_job_file", "General"),
    Column("Purpose", "purpose", "General"),
    Column("Print status", "print_status", "General"),
    # Materials
    Column("Resin name", "resin_name", "Materials"),
    Column("Resin permId", "resin_permid", "Materials", formula=True),
    Column("Substrate name", "substrate_name", "Materials"),
    Column("Substrate permId", "substrate_permid", "Materials"),
    Column("Spacer type", "spacer_type", "Materials"),
    Column("Spacer count", "spacer_count", "Materials"),
    Column("Spacer thickness [mm]", "spacer_thickness_mm", "Materials"),
    # Printer files
    Column("Femtika output folder", "femtika_output_folder", "Printer files"),
    # Printer settings
    Column("Objective", "objective", "Printer settings"),
    Column("R", "r", "Printer settings"),
    Column("Max laser power (calibration) [mW]", "max_laser_power_mw", "Printer settings"),
    Column("Laser power [mW]", "laser_power_mw", "Printer settings"),
    Column("Scan speed [mm/s]", "scan_speed_mm_s", "Printer settings"),
    Column("Slicing distance [µm]", "slicing_distance_um", "Printer settings"),
    Column("Hatching distance [µm]", "hatching_distance_um", "Printer settings"),
    Column("Infinite FOV", "infinite_fov", "Printer settings"),
    Column("Tilt compensation", "tilt_compensation", "Printer settings"),
    Column("Tilt alpha [°]", "tilt_alpha_deg", "Printer settings"),
    Column("Tilt beta [°]", "tilt_beta_deg", "Printer settings"),
    Column("Print duration [min]", "print_duration_min", "Printer settings"),
    Column("Structures printed", "structures_printed", "Printer settings"),
    # Print geometry
    Column("z start [µm]", "z_start_um", "Print geometry"),
    Column("z end [µm]", "z_end_um", "Print geometry"),
    Column("z height [µm]", "z_height_um", "Print geometry", formula=True),
    Column("x start [µm]", "x_start_um", "Print geometry"),
    Column("x end [µm]", "x_end_um", "Print geometry"),
    Column("x width [µm]", "x_width_um", "Print geometry", formula=True),
    Column("y start [µm]", "y_start_um", "Print geometry"),
    Column("y end [µm]", "y_end_um", "Print geometry"),
    Column("y depth [µm]", "y_depth_um", "Print geometry", formula=True),
    # Washing
    Column("Washing date", "washing_date", SECTION_WASHING),
    Column("Washing run ID", "washing_run_id", SECTION_WASHING),
    Column("Washing operator", "washing_operator", SECTION_WASHING),
    Column("Washing solvent", "washing_solvent", SECTION_WASHING),
    Column("Washing duration [min]", "washing_duration_min", SECTION_WASHING),
    # Drying (CPD)
    Column("CPD date", "cpd_date", SECTION_CPD),
    Column("CPD run ID", "cpd_run_id", SECTION_CPD),
    Column("CPD operator", "cpd_operator", SECTION_CPD),
    Column("CPD program", "cpd_program", SECTION_CPD),
    # Sintering
    Column("Sintering date", "sintering_date", SECTION_SINTERING),
    Column("Sintering run ID", "sintering_run_id", SECTION_SINTERING),
    Column("Sintering operator", "sintering_operator", SECTION_SINTERING),
    Column("Furnace name", "furnace_name", SECTION_SINTERING),
    Column("Furnace permId", "furnace_permid", SECTION_SINTERING, formula=True),
    Column("Furnace program", "furnace_program", SECTION_SINTERING),
    Column("Max temperature [°C]", "max_temperature_c", SECTION_SINTERING),
    Column("Dwell time [h]", "dwell_time_h", SECTION_SINTERING),
    Column("Sintering profile file", "sintering_profile_file", SECTION_SINTERING),
    # openBIS / Notes
    Column("openBIS upload", "openbis_upload", "openBIS"),
    Column("Comments", "comments", "Notes"),
]

IMAGING_COLUMNS: List[Column] = [
    Column("Print code", "print_code", "Imaging"),
    Column("Print name", "print_name", "Imaging", formula=True),
    Column("Substrate permId", "substrate_permid", "Imaging", formula=True),
    Column("Technique", "technique", "Imaging"),
    Column("Sample state", "sample_state", "Imaging"),
    Column("Imaging date", "imaging_date", "Imaging"),
    Column("Imaging operator", "imaging_operator", "Imaging"),
    Column("Instrument permId", "instrument_permid", "Imaging", formula=True),
    Column("Image folder", "image_folder", "Imaging"),
    Column("Notes", "notes", "Imaging"),
    Column("openBIS upload", "openbis_upload", "openBIS"),
]

#: Columns per data sheet.
SHEET_COLUMNS: Dict[str, List[Column]] = {
    SHEET_PRINTJOBS: PRINTJOB_COLUMNS,
    SHEET_IMAGING: IMAGING_COLUMNS,
}

#: Key column per data sheet: a row is data only if this column is filled.
#: ``None`` = no key column; a row is data if any non-formula column is filled.
SHEET_KEY_FIELD: Dict[str, Optional[str]] = {
    SHEET_PRINTJOBS: "print_code",
    SHEET_IMAGING: None,
}


def column_by_field(sheet: str, field: str) -> Column:
    """
    Return the column of *sheet* mapped to *field*.

    Args:
        sheet: Sheet name, e.g. :data:`SHEET_PRINTJOBS`.
        field: Model field name, e.g. ``"washing_date"``.

    Raises:
        KeyError: If no column maps to *field*.
    """
    for col in SHEET_COLUMNS[sheet]:
        if col.field == field:
            return col
    raise KeyError(f"No column for field '{field}' in sheet '{sheet}'")


def columns_in_section(sheet: str, section: str) -> List[Column]:
    """Return the columns of *sheet* that belong to *section*, in sheet order."""
    return [col for col in SHEET_COLUMNS[sheet] if col.section == section]
