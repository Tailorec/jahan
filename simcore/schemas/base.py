"""Shared base model, immutable containers, primitives, identifiers, canonical hashing."""

import hashlib
import json
from collections.abc import (
    Collection,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set,
)
from typing import Annotated, Any, ClassVar, Literal, Self, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, StringConstraints
from pydantic_core import CoreSchema, core_schema

SCHEMA_VERSION = "1.0.0"

# Pydantic refuses field names with a leading underscore, so no field can collide with this key.
_VERSION_KEY = "_schema_version"


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


class FrozenDict[K, V](Mapping[K, V]):
    """Immutable mapping for model fields: freezing a model does not freeze a dict inside it."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[K, V] | Iterable[tuple[K, V]] = ()) -> None:
        self._data: dict[K, V] = dict(data)

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __hash__(self) -> int:
        return hash(frozenset(self._data.items()))

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        key_type, value_type = get_args(source) or (Any, Any)
        dict_schema = handler.generate_schema(dict[key_type, value_type])
        return core_schema.no_info_after_validator_function(
            cls,
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(dict, return_schema=dict_schema),
        )


_MUTABLE_CONTAINERS = (list, dict, set, bytearray, MutableSequence, MutableMapping, MutableSet)
# Read-only abstract types that pydantic nonetheless validates into a mutable list, dict or set.
_MUTABLE_WHEN_VALIDATED = (Sequence, Mapping, Set, Collection, Iterable)


def _mutable_container(annotation: Any) -> Any:
    origin = get_origin(annotation) or annotation
    if origin is Literal:
        return None
    if origin is Annotated:
        return _mutable_container(get_args(annotation)[0])
    if any(origin is abstract for abstract in _MUTABLE_WHEN_VALIDATED) or (
        isinstance(origin, type) and issubclass(origin, _MUTABLE_CONTAINERS)
    ):
        return origin
    for arg in get_args(annotation):
        found = _mutable_container(arg)
        if found is not None:
            return found
    return None


class SimBaseModel(BaseModel):
    """Base for every type crossing a module boundary.

    `_hash_exclude_` names fields that are outputs (observed cost, wall-clock
    timestamps) and must not move a hash, at whatever depth the model is nested.
    `_hash_version_` folds SCHEMA_VERSION into the hash; only the run configuration opts in.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )

    _hash_exclude_: ClassVar[frozenset[str]] = frozenset()
    _hash_version_: ClassVar[bool] = False

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        exclude = cls._hash_exclude_
        if not isinstance(exclude, frozenset) or not all(isinstance(name, str) for name in exclude):
            raise TypeError(f"{cls.__name__}._hash_exclude_ must be a frozenset of field names")
        unknown = exclude - set(cls.model_fields) - set(cls.model_computed_fields)
        if unknown:
            raise TypeError(f"{cls.__name__}._hash_exclude_ names fields that do not exist: {sorted(unknown)}")
        if not isinstance(cls._hash_version_, bool):
            raise TypeError(f"{cls.__name__}._hash_version_ must be a bool")
        for name, field in cls.model_fields.items():
            found = _mutable_container(field.annotation)
            if found is not None:
                raise TypeError(
                    f"{cls.__name__}.{name} uses mutable container {getattr(found, '__name__', found)}: "
                    "use tuple, frozenset or FrozenDict so the model cannot change after it is hashed"
                )

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Copy the model, validating any update; pydantic's own copy bypasses every validator."""
        if not update:
            return super().model_copy(deep=deep)
        current = {name: getattr(self, name) for name in type(self).model_fields}
        return self.model_validate({**current, **update})


def canonical_payload(model: SimBaseModel) -> dict[str, Any]:
    """The JSON-ready structure a hash is computed over.

    Exclusions and version folding apply at every nesting level, set-valued fields are
    sorted, and negative zero is normalised, so structures that compare equal hash equally.
    """
    return _canonical(model, model.model_dump(mode="json"))


def _canonical(value: Any, dumped: Any) -> Any:
    if isinstance(value, SimBaseModel) and isinstance(dumped, dict):
        cls = type(value)
        payload = {
            name: _canonical(getattr(value, name), item)
            for name, item in dumped.items()
            if name not in cls._hash_exclude_
        }
        if cls._hash_version_:
            payload[_VERSION_KEY] = SCHEMA_VERSION
        return payload
    if isinstance(value, Mapping) and isinstance(dumped, dict):
        # Serialization preserves iteration order, so values align even where keys were rewritten for JSON.
        return {
            key: _canonical(item_value, item)
            for (key, item), item_value in zip(dumped.items(), value.values(), strict=True)
        }
    if isinstance(value, (set, frozenset)) and isinstance(dumped, list):
        items = [_canonical(item_value, item) for item_value, item in zip(value, dumped, strict=True)]
        return sorted(items, key=_json_text)
    if isinstance(value, (tuple, list)) and isinstance(dumped, list):
        return [_canonical(item_value, item) for item_value, item in zip(value, dumped, strict=True)]
    if isinstance(dumped, float) and dumped == 0.0:
        return 0.0
    return dumped


def _json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_json(model: SimBaseModel) -> str:
    return _json_text(canonical_payload(model))


def canonical_hash(model: SimBaseModel) -> str:
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()
