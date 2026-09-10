"""Shared base model, bounded primitives, identifiers, hashes, canonical hashing."""

import hashlib
import json
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "1.0.0"


UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
SignedUnitInterval = Annotated[float, Field(ge=-1.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]

RunId = Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[0-9a-z]+$")]
StimulusId = Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[0-9a-z]+$")]
PersonaId = Identifier

HashDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BriefHash = HashDigest
PopulationHash = HashDigest
ConfigHash = HashDigest
GraphHash = HashDigest


class SimBaseModel(BaseModel):
    """Base for every type crossing a module boundary.

    `_hash_exclude_` names fields that are outputs (observed cost, wall-clock
    timestamps) and must not move a hash. `_hash_version_` folds
    SCHEMA_VERSION into the hash; only the run configuration opts in.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )

    _hash_exclude_: ClassVar[frozenset[str]] = frozenset()
    _hash_version_: ClassVar[bool] = False


def canonical_payload(model: SimBaseModel) -> dict[str, Any]:
    payload = model.model_dump(mode="json", exclude=set(model._hash_exclude_))
    if model._hash_version_:
        payload = {"schema_version": SCHEMA_VERSION, **payload}
    return payload


def canonical_json(model: SimBaseModel) -> str:
    return json.dumps(
        canonical_payload(model),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(model: SimBaseModel) -> str:
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()
