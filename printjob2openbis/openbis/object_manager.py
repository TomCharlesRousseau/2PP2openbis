"""
openBIS object creation and validation manager for printjob2openbis.

Handles:
- Checking whether an object (identified by code or permId) already exists.
- Creating EXPERIMENTAL_STEP objects for print jobs.
"""

from typing import List, Optional

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ObjectManager:
    """Manage creation and validation of openBIS print-job objects."""

    def __init__(self, openbis) -> None:
        """
        Initialise the manager.

        Args:
            openbis: Connected ``pybis.Openbis`` instance.
        """
        self.openbis = openbis
        self._cfg = Settings()
        self.collection_path = self._cfg.collection_path

    # ── Existence checks ───────────────────────────────────────────────────

    def object_exists(self, identifier: str) -> bool:
        """
        Check whether an openBIS object exists.

        The *identifier* may be:
        - An object **code** (e.g. ``"PJ001"``): searched inside the
          configured print-job collection.
        - An object **permId** (e.g. ``"20210101000000000-12345"``): looked
          up directly via ``get_sample``.

        Args:
            identifier: Object code or permId.

        Returns:
            ``True`` if the object exists, ``False`` otherwise.
        """
        # 1. Try direct permId / path lookup (works for any object type).
        try:
            result = self.openbis.get_sample(identifier)
            if result is not None:
                logger.debug(f"Object '{identifier}' found via direct lookup")
                return True
        except Exception:
            pass

        # 2. Fall back to code-based search within the print-job collection.
        try:
            results = self.openbis.get_samples(
                code=identifier, collection=self.collection_path
            )
            if len(results) > 0:
                logger.debug(
                    f"Object '{identifier}' found by code in {self.collection_path}"
                )
                return True
        except Exception as exc:
            logger.error(f"Error checking existence of '{identifier}': {exc}")

        return False

    # ── Object creation ────────────────────────────────────────────────────

    def create_experimental_step(
        self,
        name: str,
        code: str,
        parents: List[str],
        description: str,
        print_date: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create an ``EXPERIMENTAL_STEP`` object for a print job.

        Args:
            name: Human-readable object name (Printjob Name #).
            code: Unique object code.
            parents: List of parent permIds (Resin ID, Substrate ID).
            description: Formatted description text.
            print_date: Optional print date string.

        Returns:
            permId of the created object, or ``None`` if creation failed.
        """
        try:
            obj = self.openbis.new_sample(
                type="EXPERIMENTAL_STEP",
                code=code,
                collection=self.collection_path,
            )

            # Set object name
            obj.p["$name"] = name

            # Set description
            if description:
                try:
                    obj.p["experimental_step.experimental_description"] = description
                except Exception:
                    try:
                        obj.p["description"] = description
                    except Exception as exc:
                        logger.debug(f"Could not set description property: {exc}")

            # Set print date if provided
            if print_date:
                try:
                    obj.p["print_date"] = print_date
                except Exception as exc:
                    logger.debug(f"Could not set print_date property: {exc}")

            # Link parent objects
            if parents:
                obj.parents = parents
                logger.debug(f"Set {len(parents)} parent(s) for {code}")

            obj.save()
            logger.info(f"Created EXPERIMENTAL_STEP: {code}")

            # Retrieve permId of the newly created object.
            created = self.openbis.get_sample(f"{self.collection_path}/{code}")
            perm_id: str = created.permId
            logger.debug(f"Object permId: {perm_id}")
            return perm_id

        except Exception as exc:
            logger.error(f"Error creating EXPERIMENTAL_STEP '{code}': {exc}")
            return None
