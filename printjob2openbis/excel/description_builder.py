"""
Descriptions and value formatting for openBIS objects.

Everything without a dedicated openBIS property goes into a description,
grouped by Excel section as ``Label: value`` lines (label = Excel header, so
units are included). Empty values are omitted. Descriptions are HTML because
the ELN renders MULTILINE_VARCHAR fields as rich text (plain line breaks are lost).
"""

import html
from datetime import date, datetime
from typing import Any, Iterable, List, Optional, Set, Tuple

from config.settings import Settings
from excel.column_mapping import SHEET_COLUMNS, SHEET_PRINTJOBS
from models.cell import CellValue
from models.imaging import ImagingEvent
from models.printjob import PrintJob
from models.run import StepKind

#: PrintJobs sections that go into the print step description.
PRINT_STEP_SECTIONS = ["General", "Materials", "Printer files", "Printer settings", "Print geometry"]

#: PrintJobs fields with their own property or a parent link (not repeated in the description).
PRINT_STEP_MAPPED_FIELDS: Set[str] = {
    "print_name",        # $name
    "print_date",        # start_date
    "print_operator",    # operator
    "purpose",           # experimental_step.experimental_goals
    "print_status",      # experimental_step.experimental_results
    "resin_permid",      # parent
    "substrate_permid",  # parent
}


def format_value(value: CellValue) -> str:
    """
    Cell value as description text.

    Dates as ``YYYY-MM-DD``, whole-number floats without ``.0``, everything
    else as ``str``.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def to_timestamp(value: date) -> str:
    """
    Date for an openBIS TIMESTAMP property (``YYYY-MM-DD HH:MM:SS``).

    A date without time is written at midnight.

    Raises:
        TypeError: If *value* is not a date (the checker prevents this).
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    raise TypeError(f"Expected a date, got {value!r}")


#: A description block: optional bold title and its ``Label: value`` lines.
Block = Tuple[Optional[str], List[str]]


def text_to_html(value: CellValue) -> Optional[str]:
    """
    Cell value as HTML for a rich-text (MULTILINE_VARCHAR) property.

    The ELN renders these fields as HTML, so line breaks become ``<br>`` and
    special characters are escaped. ``None`` stays ``None``.
    """
    if value is None:
        return None
    return "<br>".join(html.escape(line) for line in format_value(value).splitlines())


def blocks_to_html(blocks: List[Block]) -> str:
    """One ``<p>`` per block: bold title (if any), then one line per ``<br>``."""
    paragraphs = []
    for title, lines in blocks:
        parts = ([f"<strong>{html.escape(title)}</strong>"] if title else [])
        parts += [html.escape(line) for line in lines]
        paragraphs.append("<p>" + "<br>".join(parts) + "</p>")
    return "".join(paragraphs)


def section_blocks(sheet: str, obj: Any, sections: Iterable[str],
                   exclude: Optional[Set[str]] = None) -> List[Block]:
    """
    ``Label: value`` lines of *obj*, one block per Excel section.

    Args:
        sheet: Sheet whose columns describe *obj*.
        obj: Model object (PrintJob, ImagingEvent) holding the fields.
        sections: Sections to include, in this order.
        exclude: Fields to leave out.

    Returns:
        (section name, lines) per section; empty sections are omitted.
    """
    exclude = exclude or set()
    blocks: List[Block] = []
    for section in sections:
        lines = [
            f"{col.header}: {format_value(getattr(obj, col.field))}"
            for col in SHEET_COLUMNS[sheet]
            if col.section == section
            and col.field not in exclude
            and getattr(obj, col.field) is not None
        ]
        if lines:
            blocks.append((section, lines))
    return blocks


def _with_footer(blocks: List[Block]) -> str:
    """HTML of *blocks* plus the uploader version footer."""
    version = Settings().get("version", "unknown")
    return blocks_to_html(blocks + [(None, [f"Uploaded using 2PP2openbis version {version}"])])


def build_print_step_description(job: PrintJob) -> str:
    """Description of a print step: General / Materials / Printer / Geometry columns not mapped to a property."""
    return _with_footer(
        section_blocks(SHEET_PRINTJOBS, job, PRINT_STEP_SECTIONS, PRINT_STEP_MAPPED_FIELDS)
    )


def build_run_step_description(job: PrintJob, kind: StepKind) -> str:
    """
    Description of a washing / CPD / sintering step: that step's own columns.

    *job* is any print of the run (the checker ensures these columns are identical
    for all prints of a run). Date, operator and run ID have their own property or
    are the code; the furnace permId is a parent.
    """
    exclude = {f"{kind.key}_date", f"{kind.key}_run_id", f"{kind.key}_operator", "furnace_permid"}
    return _with_footer(section_blocks(SHEET_PRINTJOBS, job, [kind.section], exclude))


def build_imaging_description(event: ImagingEvent) -> str:
    """Description of an imaging step: technique, sample state, image folder."""
    lines = [
        f"{label}: {format_value(value)}"
        for label, value in [
            ("Technique", event.technique),
            ("Sample state", event.sample_state),
            ("Image folder", event.image_folder),
        ]
        if value is not None
    ]
    return _with_footer([(None, lines)] if lines else [])


def build_sample_description(job: PrintJob) -> str:
    """Description of a printed / sintered sample: print code, design, substrate name, resin name."""
    lines = [
        f"{label}: {format_value(value)}"
        for label, value in [
            ("Print code", job.print_code),
            ("Design", job.design),
            ("Substrate name", job.substrate_name),
            ("Resin name", job.resin_name),
        ]
        if value is not None
    ]
    return _with_footer([(None, lines)] if lines else [])
