"""
Configuration management for printjob2openbis.

Loads settings from ``config/settings.json`` and exposes them as typed
properties. The class is a singleton so the JSON file is parsed only once.
"""

import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_FILE = Path(__file__).parent / "settings.json"

#: Object groups, each stored in its own collection (``collections.<group>``).
COLLECTION_GROUPS = ("printjobs", "samples", "washing", "cpd", "sintering", "imaging")


class Settings:
    """Centralised configuration class for printjob2openbis.

    Usage::

        from config.settings import Settings

        cfg = Settings()
        print(cfg.openbis_url)
    """

    _instance: "Settings | None" = None
    _data: Dict[str, Any] = {}

    def __new__(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    # ── Loading ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Parse ``settings.json`` into ``_data``."""
        if not _CONFIG_FILE.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {_CONFIG_FILE}\n"
                "Create config/settings.json – copy settings.json.example and fill it in."
            )
        with open(_CONFIG_FILE, "r") as fh:
            try:
                self._data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in settings.json: {exc}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value using dot-separated key notation.

        Args:
            key: Dot-separated path, e.g. ``"openbis.api_url"``.
            default: Value returned when the key is absent.

        Returns:
            The configuration value or *default*.
        """
        node = self._data
        for part in key.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(part)
            if node is None:
                return default
        return node

    # ── openBIS ────────────────────────────────────────────────────────────

    @property
    def openbis_url(self) -> str:
        """openBIS API URL."""
        return self.get("openbis.api_url", "")

    @property
    def openbis_username(self) -> str:
        """openBIS username."""
        return self.get("openbis.username", "")

    @property
    def openbis_space(self) -> str:
        """openBIS space name."""
        return self.get("openbis.space", "")

    @property
    def project_name(self) -> str:
        """openBIS project code."""
        return self.get("openbis.project", "")

    @property
    def project_path(self) -> str:
        """Full openBIS project path, e.g. ``/SPACE/PROJECT``."""
        return f"/{self.openbis_space}/{self.project_name}"

    # ── Collections ────────────────────────────────────────────────────────

    def collection(self, group: str) -> str:
        """
        openBIS collection code for one object group.

        Args:
            group: One of :data:`COLLECTION_GROUPS`, e.g. ``"washing"``.

        Returns:
            The collection code from ``collections.<group>``.

        Raises:
            ValueError: If *group* is unknown or not set in settings.json.
        """
        if group not in COLLECTION_GROUPS:
            raise ValueError(
                f"Unknown collection group '{group}'. Expected one of {COLLECTION_GROUPS}."
            )
        value = self.get(f"collections.{group}")
        if not value:
            raise ValueError(
                f"'collections.{group}' is required in config/settings.json"
            )
        return value

    def collection_path(self, group: str) -> str:
        """Full openBIS collection path, e.g. ``/SPACE/PROJECT/COLLECTION``."""
        return f"{self.project_path}/{self.collection(group)}"

    # ── Instrument / Printer ───────────────────────────────────────────────

    @property
    def printer_permid(self) -> str:
        """Instrument (printer) permId – default parent for all experimental steps."""
        value = self.get("printer.permid")
        if not value:
            raise ValueError(
                "'printer.permid' is required in config/settings.json"
            )
        return value

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def bam_oe(self) -> str:
        """BAM Organisational Unit property – mandatory for samples."""
        value = self.get("properties.bam_oe")
        if not value:
            raise ValueError(
                "'properties.bam_oe' is required in config/settings.json"
            )
        return value

    # ── Excel ──────────────────────────────────────────────────────────────

    @property
    def excel_file_path(self) -> str:
        """Path to the Excel file."""
        return self.get("excel.file_path", "2PP_print_protocol_v5.xlsx")

    # ── Output ─────────────────────────────────────────────────────────────

    @property
    def report_dir(self) -> str:
        """Directory for the upload report (code → permId CSV)."""
        return self.get("output.report_dir", "reports")
