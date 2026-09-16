"""Frozen anchor versions: immutable JSON identified by content hash, pinned by the run.

An anchor version names its construct and version and holds six sets of five statements, and
nothing else. A changed statement is a new version: loading refuses an edited file as the version
it claims to be, and scoring refuses a version the run did not pin (ADR 0027)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ANCHOR_SETS_PER_VERSION = 6
ANCHORS_PER_SET = 5


class AnchorVersion(BaseModel):
    """One frozen anchor version, exactly as its file states it."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, populate_by_name=True)

    construct_id: str = Field(alias="construct", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    sets: tuple[tuple[str, ...], ...] = Field(min_length=ANCHOR_SETS_PER_VERSION, max_length=ANCHOR_SETS_PER_VERSION)

    @property
    def construct(self) -> str:
        return self.construct_id

    @classmethod
    def model_validate(cls, *args: Any, **kwargs: Any):
        version = super().model_validate(*args, **kwargs)
        for index, anchor_set in enumerate(version.sets):
            if len(anchor_set) != ANCHORS_PER_SET:
                raise ValueError(f"anchor set {index} holds {len(anchor_set)} statements, not five")
            for statement in anchor_set:
                if not statement.strip():
                    raise ValueError(f"anchor set {index} holds an empty statement")
        return version


def anchor_hash(version: AnchorVersion) -> str:
    """A version's identity: the sha256 of its canonical JSON."""
    payload = {"construct": version.construct_id, "sets": [list(anchor_set) for anchor_set in version.sets], "version": version.version}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_anchor_version(path: str | Path) -> AnchorVersion:
    """Read and validate one anchor file; anything else in shape is refused."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"anchor file {path} is not readable JSON: {error}") from error
    try:
        return AnchorVersion.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"anchor file {path} is not a frozen version: {error}") from error


def anchor_path(anchors_dir: str | Path, construct: str, version: str) -> Path:
    return Path(anchors_dir) / construct / f"{version}.json"


def resolve_anchors(
    anchor_set_id: str,
    construct: str,
    version: str,
    pinned_hashes: dict[str, str] | Any,
    anchors_dir: str | Path,
) -> AnchorVersion:
    """Load the version the run pinned, refusing an unpinned or altered version.

    `pinned_hashes` is `RunConfig.anchor_set_hashes`: anchor set id to content hash. A version
    without a pin, or whose file no longer hashes to its pin, is refused — a changed statement is
    a new version, never an edit.
    """
    pinned = dict(pinned_hashes).get(anchor_set_id) if pinned_hashes is not None else None
    if pinned is None:
        raise ValueError(f"anchor set {anchor_set_id!r} is not pinned by this run: refusing to score")
    version_model = load_anchor_version(anchor_path(anchors_dir, construct, version))
    digest = anchor_hash(version_model)
    if digest != pinned:
        raise ValueError(
            f"anchor set {anchor_set_id!r} file altered since pinning: pinned {pinned}, file is {digest}; "
            "a changed statement is a new version"
        )
    return version_model
