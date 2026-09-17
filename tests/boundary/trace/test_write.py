"""M9 phase 2: the write path — whole ticks, one transaction, refused duplicates.

A tick's events and its `tick_closed` land in one transaction or not at all; a re-sent tick
is refused rather than duplicated, and an identical re-send is a no-op. The hot path takes
payload models without revalidating them, and the same records validate strictly on read.
"""

import sqlite3

import pytest

from simcore.schemas import TraceEvent
from simcore.trace import TraceStore
from simcore.trace.errors import DuplicateSequenceError
from tests.study_builders import partition_payload

from .support import hot, partition_events, seed_header_and_entry, write_by_tick


def test_a_tick_lands_with_its_close_in_one_call(tmp_path):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    events, _ = partition_events()
    tick_zero = [e for e in events if e.tick == 0]
    assert tick_zero[-1].payload.kind == "tick_closed"
    store.write(tick_zero)
    assert [e.seq for e in store.read_live(header.config.run_id, header.world_id)] == [e.seq for e in tick_zero]


def test_a_failed_transaction_leaves_nothing_of_that_tick(tmp_path, monkeypatch):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    events, _ = partition_events()
    tick_one = [e for e in events if e.tick == 1]

    def _fail_halfway(connection, batch):
        connection.execute(
            "INSERT INTO events (world_id, seq, event_id, tick, persona_id, kind, event_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                batch[0].world_id, batch[0].seq, batch[0].event_id, batch[0].tick,
                batch[0].persona_id, batch[0].payload.kind, batch[0].model_dump_json(),
            ),
        )
        raise sqlite3.OperationalError("disk stalled mid-tick")

    monkeypatch.setattr(TraceStore, "_insert_all", staticmethod(_fail_halfway))
    with pytest.raises(sqlite3.OperationalError):
        store.write(tick_one)
    assert store.read_live(header.config.run_id, header.world_id) == ()


def test_a_resent_tick_is_refused_and_an_identical_resend_is_a_noop(tmp_path):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    events, _ = partition_events()
    write_by_tick(store, events)
    run_id, world_id = header.config.run_id, header.world_id
    before = store.read_live(run_id, world_id)
    # Identical re-send of one tick: no duplicate, nothing changes.
    store.write([e for e in events if e.tick == 1])
    assert store.read_live(run_id, world_id) == before
    # Same sequence numbers, different content: refused.
    altered = [e for e in events if e.tick == 1]
    assert altered[0].payload.kind == "turn"
    payload = dict(altered[0].payload.model_dump(mode="json"))
    payload["turn"]["reaction"]["verbatim"] = (payload["turn"]["reaction"]["verbatim"] or "x") + " changed"
    different = TraceEvent.model_validate({**altered[0].model_dump(mode="json"), "payload": payload})
    with pytest.raises(DuplicateSequenceError):
        store.write([different, *altered[1:]])
    assert store.read_live(run_id, world_id) == before


def test_the_write_path_takes_payload_models_and_refuses_mappings(tmp_path):
    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    payload = partition_payload()
    raw_tick_zero = [r for r in payload["events"] if r["tick"] == 0]
    with pytest.raises(TypeError, match="not mappings"):
        store.write(raw_tick_zero)  # type: ignore[arg-type]
    assert store.read_live(header.config.run_id, header.world_id) == ()


def test_hot_path_records_validate_strictly_on_read(tmp_path):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    events, _ = partition_events()
    store.write(hot([e for e in events if e.tick == 0]))
    read = store.read_live(header.config.run_id, header.world_id)
    assert [(e.event_id, e.tick, e.seq) for e in read] == [(e.event_id, e.tick, e.seq) for e in events if e.tick == 0]


def test_reads_are_gapless_and_ordered_by_persona_tick_and_seq(tmp_path):
    from simcore.schemas import EventFilter

    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    events, _ = partition_events()
    # Hand ticks over out of order; the record is still gapless in sequence.
    for tick in (3, 0, 2, 1, 4):
        store.write([e for e in events if e.tick == tick])
    read = store.read_live(header.config.run_id, header.world_id)
    assert [e.seq for e in read] == list(range(len(events)))
    # The read shape orders by `(persona_id, tick, seq)`.
    ordered = store.view(entry.config.run_id).events(EventFilter())
    keys = [(e.persona_id or "", e.tick, e.seq) for e in ordered]
    assert keys == sorted(keys)
    assert {e.event_id for e in ordered} == {e.event_id for e in read}
