"""M9 phase 6: the registry — one entry per run, holding everything a replay needs.

An entry pins every hash, seed and pin plus the engine version; recorded cost and
discarded ticks are readable; the status decides which backend a view opens; a second
entry for the same run is refused; and a replay configures from the entry alone.
"""

import pytest

from simcore.schemas import RunRegistryEntry, RunStatus
from simcore.trace import ParquetTraceView, SqliteTraceView, TraceStore, replay_config
from simcore.trace.errors import DuplicateEntryError, UnknownRunError
from simcore.trace.fake import InMemoryRunRegistry

from .support import seed_header_and_entry, seed_store


def test_an_entry_pins_everything_a_replay_needs_plus_the_engine(tmp_path):
    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    found = store.registry.entry(entry.config.run_id)
    assert found == entry
    assert found.engine_version == "0a35555"
    assert found.config.brief_hash and found.config.ontology_hash and found.config.population_hash
    assert list(found.config.seeds) == [4021, 917731]
    assert found.config.pins.tier_a.model_id == "openrouter/camel-ai/persona-8b"
    assert found.config.pins.embed.model_id == "openai/text-embedding-3-small"
    assert found.config_hash == entry.config_hash
    assert found.world_ids == entry.world_ids


def test_recorded_cost_and_discarded_ticks_are_readable(tmp_path):
    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    assert entry.recorded_cost == 0.0 and entry.discarded_ticks == 0
    store.registry.update(entry.model_copy(update={"recorded_cost": 1.25, "discarded_ticks": 2}))
    found = store.registry.entry(entry.config.run_id)
    assert found.recorded_cost == 1.25 and found.discarded_ticks == 2


def test_the_status_decides_which_backend_answers(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, _ = seed_store(store)
    run_id = entry.config.run_id
    assert isinstance(store.view(run_id), SqliteTraceView)
    store.registry.update(entry.model_copy(update={"status": "paused"}))
    assert isinstance(store.view(run_id), SqliteTraceView)
    store.finalize(header.world_id)
    assert store.registry.entry(run_id).status.value == "completed"
    assert isinstance(store.view(run_id), ParquetTraceView)


def test_a_second_entry_for_the_same_run_is_refused(tmp_path):
    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    with pytest.raises(DuplicateEntryError):
        store.registry.record(entry)
    with pytest.raises(DuplicateEntryError):
        store.registry.record(entry.model_copy(update={"recorded_cost": 9.99}))
    assert store.registry.entry(entry.config.run_id) == entry
    assert store.registry.entry("run-00000000000000000000000000") is None


def test_a_replay_configures_from_the_registry_entry_alone(tmp_path):
    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    config = replay_config(store.registry.entry(entry.config.run_id))
    assert config == entry.config
    assert config.pins.tier_b.model_id == entry.config.pins.tier_b.model_id
    assert list(config.scenarios) == list(entry.config.scenarios)


def test_the_registry_port_takes_entries_never_mappings(tmp_path):
    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    with pytest.raises(TypeError, match="not mappings"):
        store.registry.record(entry.model_dump(mode="json"))  # type: ignore[arg-type]
    memory = InMemoryRunRegistry()
    memory.record(entry)
    assert memory.entry(entry.config.run_id) == entry
    with pytest.raises(DuplicateEntryError):
        memory.record(entry)


def test_a_runs_entry_is_updated_as_the_run_moves(tmp_path):
    """A run's status, spend and discarded ticks change while it works, so the registry has to
    take an update through the port it is reached by. `record` refuses a second entry and
    `update` was outside the protocol, so a runner that had only the port could either never
    move the status or crash trying."""
    from simcore.ports.trace import RunRegistry

    assert hasattr(RunRegistry, "update"), "the port a runner holds cannot move a run's status"

    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    run_id = entry.config.run_id
    registry: RunRegistry = store.registry

    with pytest.raises(DuplicateEntryError):
        registry.record(entry)

    moved = entry.model_copy(update={"status": RunStatus.COMPLETED, "recorded_cost": 2.5, "discarded_ticks": 1})
    registry.update(moved)
    stored = registry.entry(run_id)
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED and stored.recorded_cost == 2.5 and stored.discarded_ticks == 1

    with pytest.raises(UnknownRunError):
        registry.update(moved.model_copy(update={"config": moved.config.model_copy(update={"run_id": f"run-{'0' * 25}9"})}))


def test_an_update_cannot_rewrite_what_a_replay_rests_on(tmp_path):
    """Status and spend move; the pins do not. A registry that let them move would make the
    entry a story about the run rather than a record of it."""
    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    registry = store.registry
    with pytest.raises(ValueError, match="pins"):
        registry.update(entry.model_copy(update={"engine_version": "deadbee"}))
    with pytest.raises(ValueError, match="pins"):
        registry.update(entry.model_copy(update={"contract_version": "9.9.9"}))


def test_a_recorded_forced_resume_may_re_pin_the_engine(tmp_path):
    """ADR 0036 allows a forced resume and requires it to be recorded. Two implementations of
    the same rule disagreed — the runner recorded the force on the entry, this registry refused
    the re-pin outright — so a forced resume died on the real registry and passed against the
    fake. One rule, in `schemas`, applied by both."""
    from simcore.schemas import check_registry_update

    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    registry = store.registry

    recorded = entry.model_copy(update={"engine_version": "9.9.9-other", "forced_from": (entry.engine_version,)})
    registry.update(recorded)
    assert registry.entry(entry.config.run_id).engine_version == "9.9.9-other"

    # An unrecorded re-pin is still refused, and by the same rule.
    with pytest.raises(ValueError, match="without recording the force"):
        registry.update(recorded.model_copy(update={"engine_version": "8.8.8", "forced_from": ()}))
    with pytest.raises(ValueError, match="pins"):
        check_registry_update(recorded, recorded.model_copy(update={"contract_version": "9.9.9"}))
