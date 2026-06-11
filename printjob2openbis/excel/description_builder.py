"""
Description builder for print-job openBIS objects.

Generates a human-readable multi-line description from a PrintJob instance.
Empty fields are omitted.
"""

from models.printjob import PrintJob


def build_description(job: PrintJob) -> str:
    """
    Build a formatted description string for a PrintJob.

    Only non-empty fields are included. Sections are separated by blank lines.

    Example output::

        Responsible person: Tom Rousseau
        Design: Test design
        Spacer: 50

        zmin: 0.0
        zmax: 10.0
        max z height [µm]: 10.0

        ...

    Args:
        job: PrintJob instance.

    Returns:
        Formatted description string.
    """
    lines: list[str] = []

    def _add(label: str, value) -> None:
        """Append a 'label: value' line if value is non-empty."""
        if value is not None and str(value).strip():
            lines.append(f"{label}: {value}")

    # ── General ────────────────────────────────────────────────────────────
    _add("Responsible person", job.responsible_person)
    _add("Design", job.design)
    _add("Spacer", job.spacer)

    # ── Z axis ─────────────────────────────────────────────────────────────
    z_lines: list[str] = []
    for label, value in [
        ("zmin", job.zmin),
        ("zmax", job.zmax),
        ("max z height [µm]", job.max_z_height),
    ]:
        if value is not None and str(value).strip():
            z_lines.append(f"{label}: {value}")

    if z_lines:
        if lines:
            lines.append("")
        lines.extend(z_lines)

    # ── X axis ─────────────────────────────────────────────────────────────
    x_lines: list[str] = []
    for label, value in [
        ("xmin", job.xmin),
        ("xmax", job.xmax),
        ("max x height [µm]", job.max_x_height),
    ]:
        if value is not None and str(value).strip():
            x_lines.append(f"{label}: {value}")

    if x_lines:
        if lines:
            lines.append("")
        lines.extend(x_lines)

    # ── Y axis ─────────────────────────────────────────────────────────────
    y_lines: list[str] = []
    for label, value in [
        ("ymin", job.ymin),
        ("ymax", job.ymax),
        ("max y height [µm]", job.max_y_height),
    ]:
        if value is not None and str(value).strip():
            y_lines.append(f"{label}: {value}")

    if y_lines:
        if lines:
            lines.append("")
        lines.extend(y_lines)

    # ── Optics / calibration ───────────────────────────────────────────────
    optics_lines: list[str] = []
    for label, value in [
        ("Lense", job.lense),
        ("R", job.r),
        ("Max power from calibration", job.max_power),
        ("Infinite FOV", job.infinite_fov),
        ("Tilt alpha degree", job.tilt_alpha),
        ("Tilt beta degree", job.tilt_beta),
        ("Tilt compensation", job.tilt_compensation),
    ]:
        if value is not None and str(value).strip():
            optics_lines.append(f"{label}: {value}")

    if optics_lines:
        if lines:
            lines.append("")
        lines.extend(optics_lines)

    return "\n".join(lines)
