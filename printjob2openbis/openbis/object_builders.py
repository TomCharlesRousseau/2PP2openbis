"""
Build the openBIS objects (type, code, properties, parents) from the models.

Pure functions: no openBIS access. Property codes are the verified ones
(see the ``openbis-properties`` skill); ``None`` values are not written.
"""

from pathlib import Path
from typing import List, Optional

from excel.description_builder import (
    build_imaging_description,
    build_poli_job_notes,
    build_print_step_description,
    build_run_step_description,
    build_sample_description,
    format_value,
    text_to_html,
    to_timestamp,
)
from models.cell import CellValue
from models.imaging import ImagingEvent
from models.printjob import PrintJob, poli_job_file_name
from models.run import Run, StepKind
from openbis.object_manager import NewObject

TYPE_EXPERIMENTAL_STEP = "EXPERIMENTAL_STEP"
TYPE_SAMPLE = "SAMPLE"
TYPE_GENERAL_PROTOCOL = "GENERAL_PROTOCOL"

#: ``GENERAL_PROTOCOL.PROTOCOL_TYPE`` of every 3DPoli job object.
POLI_PROTOCOL_TYPE = "3DPoli job file (Femtika 2PP)"


def _text(value: CellValue) -> Optional[str]:
    """Cell value as property text, ``None`` stays ``None``."""
    return None if value is None else format_value(value)


def poli_job(job: PrintJob, collection_path: str) -> NewObject:
    """
    3DPoli job object (GENERAL_PROTOCOL) of the job file of *job*; shared by all
    prints using that file. The job file is uploaded as its dataset.

    No parents; it is a parent of the print steps.
    """
    path = str(job.poli_job_file).strip()
    return NewObject(
        type_code=TYPE_GENERAL_PROTOCOL,
        code=str(job.poli_job_code),
        collection_path=collection_path,
        properties={
            "$name": poli_job_file_name(path),
            "general_protocol.protocol_type": POLI_PROTOCOL_TYPE,
            "notes": build_poli_job_notes(job),
        },
        parents=[],
        dataset_files=[Path(path)],
    )


def print_step(job: PrintJob, collection_path: str, printer_permid: str,
               poli_job_permid: Optional[str] = None) -> NewObject:
    """
    Print step (EXPERIMENTAL_STEP) of one print.

    Parents: printer (settings), resin, substrate, and the 3DPoli job object if the
    job file is filled.
    """
    parents = [printer_permid, str(job.resin_permid), str(job.substrate_permid)]
    if poli_job_permid is not None:
        parents.append(poli_job_permid)
    return NewObject(
        type_code=TYPE_EXPERIMENTAL_STEP,
        code=job.print_step_code,
        collection_path=collection_path,
        properties={
            "$name": _text(job.print_name),
            "start_date": to_timestamp(job.print_date),
            "operator": _text(job.print_operator),
            "experimental_step.experimental_goals": text_to_html(job.purpose),
            "experimental_step.experimental_results": text_to_html(job.print_status),
            "notes": text_to_html(job.comments),
            "experimental_step.experimental_description": build_print_step_description(job),
        },
        parents=parents,
    )


def printed_sample(job: PrintJob, collection_path: str, print_step_permid: str,
                   bam_oe: str) -> NewObject:
    """
    Printed (green) sample of one print (not for Failed prints).

    Parents: the print step, the substrate.
    """
    code = job.printed_sample_code
    return NewObject(
        type_code=TYPE_SAMPLE,
        code=code,
        collection_path=collection_path,
        properties={
            "$name": code,
            "bam_oe": bam_oe,
            "description": build_sample_description(job),
        },
        parents=[print_step_permid, str(job.substrate_permid)],
    )


def run_step(run: Run, job: PrintJob, collection_path: str, parents: List[str]) -> NewObject:
    """
    Shared washing / CPD / sintering step of one run.

    Args:
        run: The run (code, date and operator from its reference entry).
        job: Any print of the run, for the step's own columns (identical within a run).
        collection_path: Collection of this step kind.
        parents: De-duplicated union of the previous objects of the run's prints
            (+ furnace for sintering), built by the uploader.
    """
    entry = run.reference
    return NewObject(
        type_code=TYPE_EXPERIMENTAL_STEP,
        code=run.code,
        collection_path=collection_path,
        properties={
            "$name": run.code,
            "start_date": to_timestamp(entry.date),
            "operator": _text(entry.operator),
            "experimental_step.experimental_description": build_run_step_description(job, run.kind),
        },
        parents=parents,
    )


def sintered_sample(job: PrintJob, collection_path: str, sintering_step_permid: str,
                    printed_sample_permid: str, bam_oe: str) -> NewObject:
    """
    Sintered sample of one print.

    Parents: the sintering step of the print's run, the print's printed sample.
    """
    code = job.sintered_sample_code
    return NewObject(
        type_code=TYPE_SAMPLE,
        code=code,
        collection_path=collection_path,
        properties={
            "$name": code,
            "bam_oe": bam_oe,
            "description": build_sample_description(job),
        },
        parents=[sintering_step_permid, printed_sample_permid],
    )


def imaging_step(event: ImagingEvent, collection_path: str, sample_permid: str) -> NewObject:
    """
    Imaging step of one Imaging row.

    Parents: the print's printed (Green) or sintered sample, and the instrument
    if its permId is filled.
    """
    parents = [sample_permid]
    if event.instrument_permid is not None:
        parents.append(str(event.instrument_permid))
    return NewObject(
        type_code=TYPE_EXPERIMENTAL_STEP,
        code=event.code,
        collection_path=collection_path,
        properties={
            "$name": event.code,
            "start_date": to_timestamp(event.imaging_date),
            "operator": _text(event.imaging_operator),
            "experimental_step.experimental_description": build_imaging_description(event),
            "notes": text_to_html(event.notes),
        },
        parents=parents,
    )
