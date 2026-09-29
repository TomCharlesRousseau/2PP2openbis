"""
Find, create and link openBIS objects.

All reads and writes of the uploader go through :class:`ObjectManager`. In
dry-run mode it still reads (to know what exists) but never writes: a create
returns a placeholder permId and a link is only logged.

Objects are identified by ``/SPACE/PROJECT/CODE``.
"""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
from typing import Dict, Iterable, List, Optional, Set

from pybis import Openbis

from utils.logger import get_logger

logger = get_logger(__name__)

_BATCH_SIZE = 100

#: Dataset type of uploaded files (verified on the instance).
DATASET_TYPE = "RAW_DATA"

#: Prefix of placeholder permIds handed out in dry-run mode.
DRY_RUN_PREFIX = "(new) "

#: Timezone suffix openBIS appends to stored TIMESTAMP values, e.g. `` +0100``.
_TIMEZONE_SUFFIX = re.compile(r"\s[+-]\d{4}$")


def _normalise(value: Optional[str]) -> Optional[str]:
    """Stored property value comparable with a value we would write."""
    if value is None or value == "":
        return None
    return _TIMEZONE_SUFFIX.sub("", str(value))


@dataclass
class ExistingObject:
    """An object found in openBIS."""

    code: str
    permid: str
    type_code: str
    parent_permids: Set[str] = field(default_factory=set)
    properties: Dict[str, str] = field(default_factory=dict)  # UPPERCASE code → stored value

    def changed_properties(self, wanted: Dict[str, Optional[str]]) -> Dict[str, str]:
        """
        Properties of *wanted* whose stored value differs.

        ``None`` (empty Excel cell) never clears a stored value, so it is not a change.
        Stored TIMESTAMP values carry a timezone suffix, which is ignored.
        """
        return {
            code: value
            for code, value in wanted.items()
            if value is not None
            and _normalise(self.properties.get(code.upper())) != _normalise(value)
        }


@dataclass
class NewObject:
    """
    An object to create.

    Attributes:
        type_code: openBIS object type, e.g. ``EXPERIMENTAL_STEP``.
        code: Object code (uppercase).
        collection_path: ``/SPACE/PROJECT/COLLECTION``.
        properties: Property code → value; ``None`` values are not set.
        parents: Parent permIds.
        dataset_files: Local files to upload as one ``RAW_DATA`` dataset of the object.
    """

    type_code: str
    code: str
    collection_path: str
    properties: Dict[str, Optional[str]]
    parents: List[str]
    dataset_files: List[Path] = field(default_factory=list)


@dataclass(frozen=True)
class DatasetFile:
    """
    One file of a dataset already stored in openBIS.

    Attributes:
        name: File name (without the ``original/`` folder).
        size: Size in bytes.
        crc32: CRC32 checksum stored by openBIS, or None if openBIS gave none.
    """

    name: str
    size: int
    crc32: Optional[int]


class ObjectManager:
    """Read / write gateway to openBIS for one project."""

    def __init__(self, openbis: Openbis, space: str, project: str, dry_run: bool) -> None:
        """
        Args:
            openbis: Logged-in pybis session.
            space: Space code from settings.
            project: Project code from settings.
            dry_run: If True, never write.
        """
        self.openbis = openbis
        self.space = space
        self.project = project
        self.dry_run = dry_run

    def identifier(self, code: str) -> str:
        """``/SPACE/PROJECT/CODE`` of an object in the configured project."""
        return f"/{self.space}/{self.project}/{code}"

    # ── Reads ───────────────────────────────────────────────────────────────

    def missing_collections(self, collection_paths: Iterable[str]) -> List[str]:
        """Return the collection paths that do not exist in openBIS."""
        missing = []
        for path in sorted(set(collection_paths)):
            try:
                self.openbis.get_collection(path)
            except ValueError:
                missing.append(path)
        return missing

    def find_existing(self, codes: Iterable[str]) -> Dict[str, ExistingObject]:
        """
        Look up objects by code in the configured project (batched).

        Args:
            codes: Object codes.

        Returns:
            Code → :class:`ExistingObject` for the codes that exist.
        """
        wanted = sorted(set(codes))
        found: Dict[str, ExistingObject] = {}
        for start in range(0, len(wanted), _BATCH_SIZE):
            batch = [self.identifier(code) for code in wanted[start:start + _BATCH_SIZE]]
            response = self.openbis.get_sample(batch, raw_response=True)
            for data in response.values():
                obj = ExistingObject(
                    code=data["code"],
                    permid=data["permId"]["permId"],
                    type_code=data["type"]["code"],
                    parent_permids={p["permId"]["permId"] for p in data.get("parents") or []},
                    properties={k.upper(): v for k, v in (data.get("properties") or {}).items()},
                )
                found[obj.code] = obj
        return found

    def dataset_files(self, permid: str) -> List[DatasetFile]:
        """
        Files of every dataset of the object *permid* (directories left out).

        Uses the size and CRC32 checksum openBIS stores per file; nothing is downloaded.
        """
        files: List[DatasetFile] = []
        for dataset in self.openbis.get_datasets(sample=permid):
            listing = self.openbis.get_dataset(dataset.permId).get_files()
            for _, row in listing.iterrows():
                if row["isDirectory"]:
                    continue
                checksum = str(row.get("crc32Checksum") or "").strip()
                files.append(DatasetFile(
                    name=PurePosixPath(row["pathInDataSet"]).name,
                    size=int(row["fileSize"]),
                    crc32=int(checksum, 16) if checksum not in ("", "0") else None,
                ))
        return files

    # ── Writes ──────────────────────────────────────────────────────────────

    def upload_dataset(self, permid: str, code: str, files: List[Path]) -> None:
        """
        Upload *files* as one ``RAW_DATA`` dataset of the object *permid*.

        Args:
            permid: The object (a placeholder in dry-run).
            code: Object code, for log messages.
            files: Local files.

        Raises:
            ValueError: openBIS rejected the dataset.
        """
        names = ", ".join(f.name for f in files)
        if self.dry_run:
            logger.info(f"DRY-RUN: would upload dataset {names} to {code}")
            return
        try:
            dataset = self.openbis.new_dataset(
                type=DATASET_TYPE, sample=permid, files=[str(f) for f in files])
            dataset.save()
        except Exception as exc:  # pybis raises plain Exceptions for upload failures
            raise ValueError(str(exc)) from exc
        logger.info(f"Uploaded dataset {names} to {code} ({dataset.permId})")

    def create(self, new: NewObject) -> str:
        """
        Create *new* and return its permId (a placeholder in dry-run mode).

        Raises:
            KeyError: Unknown property code (programming error, never caught).
            ValueError: openBIS rejected the object.
        """
        if self.dry_run:
            logger.info(f"DRY-RUN: would create {new.type_code} {new.code} in "
                        f"{new.collection_path} with parents {new.parents}")
            return f"{DRY_RUN_PREFIX}{new.code}"

        obj = self.openbis.new_sample(
            type=new.type_code,
            code=new.code,
            collection=new.collection_path,
            parents=new.parents,
        )
        for code, value in new.properties.items():
            if value is not None:
                obj.p[code] = value
        obj.save()
        logger.info(f"Created {new.type_code} {new.code} ({obj.permId})")
        return obj.permId

    def add_parents(self, existing: ExistingObject, parent_permids: Iterable[str]) -> List[str]:
        """
        Add the parents of *parent_permids* that *existing* does not have yet.

        Existing parents are never removed.

        Returns:
            The permIds that were (or, in dry-run, would be) added.
        """
        missing = [p for p in parent_permids if p not in existing.parent_permids]
        if not missing:
            return []
        if self.dry_run:
            logger.info(f"DRY-RUN: would add parents {missing} to {existing.type_code} {existing.code}")
            return missing
        sample = self.openbis.get_sample(existing.permid)
        sample.add_parents(missing)
        sample.save()
        existing.parent_permids.update(missing)
        logger.info(f"Added parents {missing} to {existing.type_code} {existing.code}")
        return missing

    def update_properties(self, existing: ExistingObject, properties: Dict[str, str]) -> None:
        """
        Overwrite *properties* (code → new value) of *existing*.

        Raises:
            KeyError: Unknown property code (programming error, never caught).
            ValueError: openBIS rejected the change.
        """
        codes = ", ".join(properties)
        if self.dry_run:
            logger.info(f"DRY-RUN: would update {existing.type_code} {existing.code}: {codes}")
            return
        sample = self.openbis.get_sample(existing.permid)
        for code, value in properties.items():
            sample.p[code] = value
        sample.save()
        existing.properties.update({code.upper(): value for code, value in properties.items()})
        logger.info(f"Updated {existing.type_code} {existing.code}: {codes}")
