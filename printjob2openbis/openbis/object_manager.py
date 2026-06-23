"""
openBIS object creation and validation manager for printjob2openbis.

Handles:
- Checking whether an object (identified by code or permId) already exists.
- Creating EXPERIMENTAL_STEP objects for print jobs.
- Sample deduplication per Substrate with automatic parent assignment.
"""

from typing import Dict, List, Optional

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
        
        # Feature 1: Default instrument parent
        self.instrument_permid: str = self._cfg.printer_permid
        logger.debug(f"Instrument permId: {self.instrument_permid}")
        
        # Feature 2: Track samples per substrate for deduplication
        # Maps substrate_id -> (sample_number, sample_permId)
        self._substrate_to_sample: Dict[str, tuple] = {}
        self._next_sample_number = 1

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

    # ── Sample creation with deduplication ─────────────────────────────────

    def create_or_get_sample(self, substrate_id: str) -> Optional[tuple]:
        """
        Create or retrieve a deduplicated sample for a substrate.

        Feature 2: If a sample already exists for this substrate,
        return its details. Otherwise, create a new sample.

        Feature 3: The sample's parent is always the substrate.

        Args:
            substrate_id: The permId of the substrate (UV-Sheet).

        Returns:
            Tuple of (sample_code, sample_permId) or None if creation failed.
            Example: ("PRINTED_1", "20210101000000000-54321")
        """
        # Check if we've already created a sample for this substrate
        if substrate_id in self._substrate_to_sample:
            sample_number, sample_permid = self._substrate_to_sample[substrate_id]
            logger.debug(
                f"Substrate '{substrate_id}' already mapped to sample "
                f"PRINTED_{sample_number} (permId: {sample_permid})"
            )
            return (f"PRINTED_{sample_number}", sample_permid)

        # Create a new sample for this substrate
        sample_number = self._next_sample_number
        sample_code = f"PRINTED_{sample_number}"
        sample_name = f"Printed_{sample_number}"

        try:
            obj = self.openbis.new_sample(
                type="EXPERIMENTAL_STEP",  # Assuming samples are also EXPERIMENTAL_STEP type
                code=sample_code,
                collection=self.collection_path,
            )

            # Set object name
            obj.p["$name"] = sample_name

            # Feature 3: Set substrate as parent
            obj.parents = [substrate_id]
            logger.debug(f"Set substrate '{substrate_id}' as parent for sample '{sample_code}'")

            obj.save()
            logger.info(f"Created sample: {sample_code} (name: {sample_name})")

            # Retrieve permId of the newly created sample
            created = self.openbis.get_sample(f"{self.collection_path}/{sample_code}")
            sample_permid: str = created.permId
            logger.debug(f"Sample permId: {sample_permid}")

            # Track this substrate -> sample mapping
            self._substrate_to_sample[substrate_id] = (sample_number, sample_permid)
            self._next_sample_number += 1

            return (sample_code, sample_permid)

        except Exception as exc:
            logger.error(f"Error creating sample for substrate '{substrate_id}': {exc}")
            return None

    # ── Object creation ────────────────────────────────────────────────────

    def create_experimental_step(
        self,
        name: str,
        code: str,
        parents: List[str],
        description: str,
        substrate_id: Optional[str] = None,
        print_date: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create an ``EXPERIMENTAL_STEP`` object for a print job.

        Feature 1: Always adds the instrument as the first parent.
        Feature 2 & 3: Creates or retrieves a deduplicated sample for the substrate.

        Args:
            name: Human-readable object name (Print #).
            code: Unique object code.
            parents: List of parent permIds (Resin ID, Substrate ID).
            description: Formatted description text.
            substrate_id: The substrate permId for sample deduplication (Feature 2 & 3).
            print_date: Optional print date string.

        Returns:
            permId of the created object, or ``None`` if creation failed.
        """
        try:
            # Feature 1: Always add instrument as first parent
            all_parents = [self.instrument_permid] + parents
            logger.debug(
                f"Creating EXPERIMENTAL_STEP with parents: "
                f"[{self.instrument_permid} (instrument)] + {parents}"
            )

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

            # Link parent objects (including instrument)
            if all_parents:
                obj.parents = all_parents
                logger.debug(f"Set {len(all_parents)} parent(s) for {code}")

            # Feature 2 & 3: Create/retrieve deduplicated sample
            sample_permid = None
            if substrate_id:
                sample_result = self.create_or_get_sample(substrate_id)
                if sample_result:
                    sample_code, sample_permid = sample_result
                    logger.debug(
                        f"Linked experimental step '{code}' to sample '{sample_code}'"
                    )
                else:
                    logger.warning(f"Could not create/retrieve sample for substrate '{substrate_id}'")

            obj.save()
            logger.info(f"Created EXPERIMENTAL_STEP: {code}")

            # Retrieve permId of the newly created object
            created = self.openbis.get_sample(f"{self.collection_path}/{code}")
            perm_id: str = created.permId
            logger.debug(f"Object permId: {perm_id}")
            return perm_id

        except Exception as exc:
            logger.error(f"Error creating EXPERIMENTAL_STEP '{code}': {exc}")
            return None
