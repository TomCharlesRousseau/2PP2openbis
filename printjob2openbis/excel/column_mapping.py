"""
Column mapping for the print-job Excel spreadsheet.

Defines the expected header names (row 2) and maps them to
PrintJob dataclass field names. Columns that should be ignored
are listed separately.
"""

# Mapping from Excel header (as it appears in row 2) to PrintJob field name.
# Columns that are intentionally ignored are NOT listed here.
COLUMN_TO_FIELD: dict[str, str] = {
    "Printjob Name #": "name",
    "Code": "code",
    "Print date": "print_date",
    "Responsible person": "responsible_person",
    "Design": "design",
    "3DPoli path": "poli_path",
    # Column G "Resin Name" is ignored
    "Resin ID": "resin_id",
    # Column I "Substrate Name" is ignored
    "Substrate ID": "substrate_id",
    "Spacer": "spacer",
    # Column L (empty) is ignored
    # Column M "F path" is ignored
    "zmin": "zmin",
    "zmax": "zmax",
    "max z height [µm]": "max_z_height",
    "xmin": "xmin",
    "xmax": "xmax",
    "max x height [µm]": "max_x_height",
    "ymin": "ymin",
    "ymax": "ymax",
    "max y height [µm]": "max_y_height",
    "Lense": "lense",
    "R": "r",
    "Max power from calibration": "max_power",
    "Infinite FOV": "infinite_fov",
    "Tilt alpha degree": "tilt_alpha",
    "Tilt beta degree": "tilt_beta",
    "Tilt compensation": "tilt_compensation",
}

# Headers that must be present for the parser to proceed.
REQUIRED_COLUMNS: list[str] = [
    "Printjob Name #",
    "Code",
]

# Headers that are explicitly ignored (for documentation purposes).
IGNORED_COLUMNS: list[str] = [
    "Resin Name",
    "Substrate Name",
    "F path",
]
