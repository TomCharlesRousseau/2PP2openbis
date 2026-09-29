"""
Fill the 2PP print protocol from Femtika / 3DPoli output folders.

Standalone: no openBIS login, no import from ``openbis/`` or ``config/settings.py``.
Private paths (logs directory, share root) are passed in as arguments.
"""

from .reader import FemtikaRun, read_run_folder, resolve_run_folder

__all__ = ["FemtikaRun", "read_run_folder", "resolve_run_folder"]
