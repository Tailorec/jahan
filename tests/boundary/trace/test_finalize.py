"""M9 phase 5: finalization — a finished world's lasting record.

`finalize(world_id)` writes events, beliefs and edges as Parquet, sorted by
`(persona_id, tick)`; every read shape answers identically before and after; calling it
twice changes nothing; a finalized world refuses writes; the contract version lands in the
partition metadata and the registry; and Parquet columns are typed per payload kind rather
than a JSON blob.
"""

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from simcore.schemas import EventFilter, VerbatimGrouping
from simcore.trace import TraceStore
from simcore.trace.errors import FinalizedError
from tests.boundary.trace.support import partition_events, seed_header_and_entry, seed_store, write_by_tick

from .support import seed_store


def _shapes(photo, personas):
    return {
        "events": photo.events(EventFilter()),
        "beliefs": {persona: photo.beliefs(persona) for persona in personas},
        "edges": photo.edges(),
        "verbatims": {grouping: photo.verbatims(grouping) for grouping in VerbatimGrouping},
    }


def test_finalize_writes_events_beliefs_and_edges_sorted(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, events = seed_store(store)
    world_dir = store.finalize(header.world_id)
    for name in ("events.parquet", "beliefs.parquet", "edges.parquet"):
        assert (world_dir / name).exists(), f"finalization writes {name}"
    table = pq.read_table(str(world_dir / "events.parquet"))
    rows = table.to_pylist()
    assert len(rows) == len(events)
    assert [(r["persona_id"] or "", r["tick"], r["seq"]) for r in rows] == sorted(
        (r["persona_id"] or "", r["tick"], r["seq"]) for r in rows
    )
    personas = sorted({e.persona_id for e in events if e.persona_id})
    assert {r["persona_id"] for r in pq.read_table(str(world_dir / "beliefs.parquet")).to_pylist()} <= set(personas)


def test_every_shape_answers_identically_before_and_after(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, events = seed_store(store)
    personas = sorted({e.persona_id for e in events if e.persona_id})
    before = _shapes(store.view(entry.config.run_id), personas)
    resolve_ids = [events[4].event_id, events[10].event_id]
    before_resolve = store.view(entry.config.run_id).resolve(resolve_ids)
    store.finalize(header.world_id)
    after = _shapes(store.view(entry.config.run_id), personas)
    assert after["events"] == before["events"]
    assert after["beliefs"] == before["beliefs"]
    assert after["edges"] == before["edges"]
    assert after["verbatims"] == before["verbatims"]
    assert store.view(entry.config.run_id).resolve(resolve_ids) == before_resolve


def test_finalization_is_idempotent_and_locks_the_world(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, events = seed_store(store)
    first = store.finalize(header.world_id)
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(first.glob("*.parquet"))}
    second = store.finalize(header.world_id)
    assert second == first
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(first.glob("*.parquet"))} == digests
    with pytest.raises(FinalizedError):
        store.write([e for e in events if e.tick == 0])


def test_the_contract_version_is_written_once_into_metadata_and_registry(tmp_path):
    from simcore.schemas.base import SCHEMA_VERSION

    store = TraceStore(tmp_path)
    header, entry, _ = seed_store(store)
    store.finalize(header.world_id)
    metadata = pq.read_table(str(store._world_dir(entry.config.run_id, header.world_id) / "events.parquet")).schema.metadata
    assert metadata[b"contract_version"].decode() == SCHEMA_VERSION == header.contract_version
    assert store.registry.entry(entry.config.run_id).contract_version == SCHEMA_VERSION


def test_parquet_columns_are_typed_per_payload_kind(tmp_path):
    import pyarrow as pa

    store = TraceStore(tmp_path)
    header, entry, _ = seed_store(store)
    store.finalize(header.world_id)
    schema = pq.read_table(str(store._world_dir(entry.config.run_id, header.world_id) / "events.parquet")).schema
    assert "kind" in schema.names
    for kind in ("turn", "belief_snapshot", "cost", "tick_closed"):
        field = schema.field(kind)
        assert pa.types.is_struct(field.type), f"{kind} is a typed struct, not a blob"
    assert not {"payload_json", "event_json", "payload", "blob"} & set(schema.names)
    for name in schema.names:
        if name in ("event_id", "world_id", "persona_id", "kind"):
            continue
        assert not pa.types.is_string(schema.field(name).type) or name in (), f"{name} holds a blob"


def test_a_paused_world_answers_the_same_live_and_finalized(tmp_path):
    """A run that stopped short records the pause at a tick that never closed: the live view
    hid those records while the finalized view showed them, so the one property the lifecycle
    rests on (ADR 0034) failed in exactly the case it exists for — reading a paused run."""
    from simcore.schemas import RunStatus, TraceEvent
    from tests.study_builders import R

    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    events, _ = partition_events()
    kept = [event for event in events if event.seq < R["completed"]]
    write_by_tick(store, kept)
    tick = max(event.tick for event in kept) + 1
    seq = max(event.seq for event in kept) + 1
    pause = [
        TraceEvent.model_validate(
            {"event_id": f"ev-{'0' * 22}{index:04d}", "world_id": header.world_id, "tick": tick,
             "seq": seq + index, "persona_id": None, "payload": payload}
        )
        for index, payload in enumerate(
            (
                {"kind": "degraded", "rung": "pause", "activation_rate": 0.0, "tier_b_frozen": True},
                {"kind": "lifecycle", "phase": "paused"},
            )
        )
    ]
    store.write(pause)

    run_id = entry.config.run_id
    before = store.view(run_id)
    live_ids = {event.event_id for event in before.events(EventFilter())}
    assert {record.event_id for record in pause} <= live_ids, "a live view hides why the run stopped"

    store.registry.update(entry.model_copy(update={"status": RunStatus.PAUSED}))
    store.finalize(header.world_id)
    store.registry.update(entry.model_copy(update={"status": RunStatus.COMPLETED}))
    after = store.view(run_id)
    assert {event.event_id for event in after.events(EventFilter())} == live_ids
    assert after.beliefs("p-000001") == before.beliefs("p-000001")
    assert after.edges() == before.edges()


def test_a_tick_that_never_closed_is_shown_by_neither_backend(tmp_path):
    """The rule applies to a tick's content, not to the world's own lifecycle records."""
    from simcore.schemas import RunStatus, TraceEvent
    from tests.study_builders import R

    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    events, _ = partition_events()
    kept = [event for event in events if event.seq < R["completed"]]
    write_by_tick(store, kept)
    orphan = TraceEvent.model_validate(
        {
            "event_id": f"ev-{'0' * 22}9999", "world_id": header.world_id,
            "tick": max(event.tick for event in kept) + 1,
            "seq": max(event.seq for event in kept) + 1, "persona_id": None,
            "payload": {"kind": "stimulus_published", "stimulus": {
                "stimulus_id": f"st-{'0' * 22}8888", "tick": max(event.tick for event in kept) + 1,
                "kind": "concept", "text": "published into a tick that never closed"}},
        }
    )
    store.write([orphan])
    run_id = entry.config.run_id
    live_ids = {event.event_id for event in store.view(run_id).events(EventFilter())}
    assert orphan.event_id not in live_ids
    store.registry.update(entry.model_copy(update={"status": RunStatus.COMPLETED}))
    store.finalize(header.world_id)
    assert orphan.event_id not in {event.event_id for event in store.view(run_id).events(EventFilter())}
