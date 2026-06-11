"""
PrintJob dataclass model.
Represents one row from the print-job Excel spreadsheet.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PrintJob:
    """
    Represents a single 3D-printing job entry from the Excel spreadsheet.

    Attributes:
        name: Printjob Name # (column A) – used as the openBIS object name.
        code: Unique code (column B) – used as the openBIS object code.
        print_date: Print date (column C).
        responsible_person: Responsible person (column D).
        design: Design name (column E).
        poli_path: 3DPoli path (column F).
        resin_id: Resin permId in openBIS (column H).
        substrate_id: Substrate permId in openBIS (column J).
        spacer: Spacer value (column K).
        zmin: Minimum z value (column N).
        zmax: Maximum z value (column O).
        max_z_height: Maximum z height in µm (column P).
        xmin: Minimum x value (column Q).
        xmax: Maximum x value (column R).
        max_x_height: Maximum x height in µm (column S).
        ymin: Minimum y value (column T).
        ymax: Maximum y value (column U).
        max_y_height: Maximum y height in µm (column V).
        lense: Lens identifier (column W).
        r: R value (column X).
        max_power: Max power from calibration (column Y).
        infinite_fov: Infinite FOV flag (column Z).
        tilt_alpha: Tilt alpha in degrees (column AA).
        tilt_beta: Tilt beta in degrees (column AB).
        tilt_compensation: Tilt compensation value (column AC).
    """

    # Mandatory identification fields
    name: str
    code: str

    # Optional fields
    print_date: Optional[str] = None
    responsible_person: Optional[str] = None
    design: Optional[str] = None
    poli_path: Optional[str] = None

    # Parent references (openBIS permIds)
    resin_id: Optional[str] = None
    substrate_id: Optional[str] = None

    # Geometry – z axis
    spacer: Optional[str] = None
    zmin: Optional[str] = None
    zmax: Optional[str] = None
    max_z_height: Optional[str] = None

    # Geometry – x axis
    xmin: Optional[str] = None
    xmax: Optional[str] = None
    max_x_height: Optional[str] = None

    # Geometry – y axis
    ymin: Optional[str] = None
    ymax: Optional[str] = None
    max_y_height: Optional[str] = None

    # Optics / calibration
    lense: Optional[str] = None
    r: Optional[str] = None
    max_power: Optional[str] = None
    infinite_fov: Optional[str] = None

    # Tilt settings
    tilt_alpha: Optional[str] = None
    tilt_beta: Optional[str] = None
    tilt_compensation: Optional[str] = None

    def parent_ids(self) -> list:
        """
        Return a list of non-empty parent permIds.

        Returns:
            List of parent permId strings.
        """
        parents = []
        if self.resin_id:
            parents.append(self.resin_id)
        if self.substrate_id:
            parents.append(self.substrate_id)
        return parents
