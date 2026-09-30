"""M9 phase 7: version-aware reads — stored runs survive a schema change.

A partition written under 1.0 loads under a synthetic 1.1 through a registered migration;
one from a newer contract is refused naming both versions; migrations apply in order and a
missing step in the chain fails loudly; a migrated partition validates strictly after
migration; and the contract version appears once per partition, on no event.
"""

import json
import re

import pytest
from pydantic import ValidationError

from simcore.schemas import PartitionHeader, TraceEvent
from simcore.schemas.errors import SchemaVersionError
from simcore.trace import migrations as _migrations
from simcore.trace.migrations import load_partition_data
from tests.study_builders import partition_payload


@pytest.fixture()
def raw_partition():
    """A partition as the first released contract wrote it: every migration since runs on it."""
    payload = partition_payload()
    payload["header"]["contract_version"] = "1.0.0"
    return {"header": payload["header"], "events": payload["events"]}


@pytest.fixture()
def synthetic_next_version():
    """A synthetic 1.2: stamps the new contract and records that it ran, then cleans up."""
    applied: list[str] = []

    def _migrate(raw):
        applied.append("1.2.0")
        raw["header"]["contract_version"] = "1.2.0"
        return raw

    _migrations.register_migration("1.2.0", _migrate)
    yield applied
    # Only the synthetic step goes: the contract's own registered migrations stay registered.
    _migrations.MIGRATION_REGISTRY[:] = [step for step in _migrations.MIGRATION_REGISTRY if step.migrate is not _migrate]


def test_a_1_0_partition_loads_under_a_synthetic_1_2(raw_partition, synthetic_next_version):
    partition = load_partition_data(raw_partition, engine_version="1.2.0")
    assert partition.header.contract_version == "1.2.0"
    assert len(partition.events) == len(raw_partition["events"])
    assert synthetic_next_version == ["1.2.0"]
    # Without the engine moving past the synthetic version, no synthetic migration runs.
    assert load_partition_data(raw_partition).header.contract_version == raw_partition["header"]["contract_version"]


def test_a_newer_contract_is_refused_naming_both_versions(raw_partition):
    from simcore.schemas.base import SCHEMA_VERSION

    raw_partition["header"]["contract_version"] = "9.9.9"
    with pytest.raises(SchemaVersionError, match=rf"(?s)9\.9\.9.*{re.escape(SCHEMA_VERSION)}"):
        load_partition_data(raw_partition)


def test_migrations_apply_in_order_and_a_missing_step_fails_loudly(raw_partition, synthetic_next_version):
    order: list[str] = []

    def _first(raw):
        order.append("1.0.1")
        return raw

    def _second(raw):
        order.append("1.1.0-after")
        raw["header"]["contract_version"] = "1.1.0"
        return raw

    _migrations.register_migration("1.0.1", _first)
    _migrations.register_migration("1.1.0", _second)
    try:
        partition = load_partition_data(raw_partition, engine_version="1.1.0")
        assert order[0] == "1.0.1" and partition.header.contract_version == "1.1.0"
        from simcore.schemas import ContractMigration

        only_second = [step for step in _migrations.MIGRATION_REGISTRY if step.introduced_in == "1.1.0"]
        with pytest.raises(SchemaVersionError, match="1\\.0\\.1"):
            load_partition_data(raw_partition, engine_version="1.1.0", migrations=only_second)
    finally:
        _migrations.MIGRATION_REGISTRY[:] = [
            step for step in _migrations.MIGRATION_REGISTRY
            if step.migrate is not _first and step.migrate is not _second
        ]


def test_a_migrated_partition_validates_strictly_after_migration(raw_partition):
    def _break(raw):
        raw["events"][0]["payload"] = {"kind": "tick_closed", "extra": "not_a_field"}
        raw["header"]["contract_version"] = "1.1.0"
        return raw

    _migrations.register_migration("1.1.0", _break)
    try:
        with pytest.raises(ValidationError):
            load_partition_data(raw_partition, engine_version="1.1.0")
    finally:
        _migrations.MIGRATION_REGISTRY[:] = [step for step in _migrations.MIGRATION_REGISTRY if step.migrate is not _break]


def test_the_contract_version_appears_once_per_partition_and_on_no_event():
    assert "contract_version" in PartitionHeader.model_fields
    assert "contract_version" not in TraceEvent.model_fields
    for name, field in TraceEvent.model_fields.items():
        assert "contract" not in name, f"TraceEvent.{name} carries contract metadata"
