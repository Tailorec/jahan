"""The path that keeps stored runs readable.

A migration registry applies every registered migration newer than a partition's own
contract, in order, then validates strictly. A partition from a newer contract than this
engine is refused rather than half-read. The contract version is written once per
partition, never per event.
"""

import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any

from simcore.schemas import CONTRACT_MIGRATIONS, ContractMigration, TracePartition
from simcore.schemas.base import SCHEMA_VERSION
from simcore.schemas.errors import SchemaVersionError

MIGRATION_REGISTRY: list[ContractMigration] = list(CONTRACT_MIGRATIONS)


def register_migration(introduced_in: str, migrate) -> None:
    """Register the step rewriting the previous shape into `introduced_in`'s shape."""
    _parse(introduced_in)
    MIGRATION_REGISTRY.append(ContractMigration(introduced_in=introduced_in, migrate=migrate))
    MIGRATION_REGISTRY.sort(key=lambda step: _parse(step.introduced_in))


def _parse(text: Any) -> tuple[int, int, int]:
    if not isinstance(text, str) or not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise SchemaVersionError(f"not a contract version: {text!r}")
    return tuple(int(part) for part in text.split("."))  # type: ignore[return-value]


def load_partition_data(
    data: Mapping[str, Any],
    *,
    written_version: str | None = None,
    engine_version: str | None = None,
    migrations: Iterable[ContractMigration] | None = None,
) -> TracePartition:
    """Load one partition through the version-aware path.

    Applies, in order, every registered migration newer than the contract the partition was
    written under, then validates strictly. A partition from a newer contract than this
    engine's is refused, naming both versions. A missing migration in the chain fails loudly:
    the chain must step through every minor/major contract between written and engine.
    """
    engine = _parse(engine_version or SCHEMA_VERSION)
    header = data.get("header") if isinstance(data, Mapping) else None
    text = written_version
    if text is None:
        text = header.get("contract_version") if isinstance(header, Mapping) else None
    written = _parse(text)
    engine_text = engine_version or SCHEMA_VERSION
    if written > engine:
        raise SchemaVersionError(
            f"partition written under contract {text}, newer than this engine's {engine_text}"
        )
    steps = sorted(migrations if migrations is not None else MIGRATION_REGISTRY,
                   key=lambda step: _parse(step.introduced_in))
    registry_steps = sorted(MIGRATION_REGISTRY, key=lambda step: _parse(step.introduced_in))
    # A missing migration in the chain fails loudly: every registered step between the written
    # contract and the engine's must be among the steps applied, or the read is refused.
    provided = {step.introduced_in for step in steps}
    missing = sorted({step.introduced_in for step in registry_steps
                      if written < _parse(step.introduced_in) <= engine} - provided)
    if missing:
        raise SchemaVersionError(
            f"migration chain from {text} to {engine_text} is missing {missing};"
            " a partition is migrated through every registered migration, in order"
        )
    applicable = [step for step in steps if written < _parse(step.introduced_in) <= engine]
    raw: dict[str, Any] = copy.deepcopy(dict(data))
    for step in applicable:
        raw = step.migrate(raw)
    partition = TracePartition.model_validate(raw)
    if any("contract_version" in (event if isinstance(event, Mapping) else {}) for event in raw.get("events", [])):
        raise SchemaVersionError("the contract version appears once per partition, never on an event")
    return partition
