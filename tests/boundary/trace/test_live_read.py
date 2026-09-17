"""M9 phase 3: reading a live run — the first three read shapes over SQLite.

A view opens on a live or paused run and sees only ticks that closed. `events(filter)`
takes a typed filter; `verbatims(grouping)` returns frozen models grouped as asked;
`resolve(trace_ids)` returns exactly the cited events or fails. Nothing returned exposes
storage — no paths, no cursors, no frames.
"""

import pytest

from simcore.schemas import EventFilter, SimBaseModel, TraceEvent, VerbatimGrouping
from simcore.trace import TraceStore
from simcore.trace.errors import UnknownRunError
from tests.study_builders import event, stimulus_id, turn_event, turn_payload

from .support import partition_events, seed_header_and_entry, seed_store


def test_a_view_opens_on_a_live_run_and_on_a_paused_one(tmp_path):
    for status in ("running", "paused"):
        store = TraceStore(tmp_path / status)
        header, entry = seed_header_and_entry(store)
        store.registry.update(entry.model_copy(update={"status": status}))
        events, _ = partition_events()
        store.write([e for e in events if e.tick == 0])
        found = store.view(entry.config.run_id).events(EventFilter())
        assert {e.seq for e in found} == {e.seq for e in events if e.tick == 0}


def test_a_live_view_shows_closed_ticks_and_nothing_unclosed(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, events = seed_store(store)
    run_id = entry.config.run_id
    world_id = events[0].world_id
    # A further tick handed over without its `tick_closed`: on disk, but not shown.
    dangling = [
        turn_event(100, 5, turn_payload("p-000001", 5, [(1, "interest", 0.8)], {
            "subject_stimulus_id": stimulus_id(1), "action": "comment",
            "verbatim": "still thinking about it"}, n=9), "p-000001"),
    ]
    store.write([TraceEvent.model_validate({**record, "world_id": world_id}) for record in dangling])
    seen = store.view(run_id).events(EventFilter())
    assert {e.seq for e in seen} == {e.seq for e in events}
    assert all(e.tick != 5 for e in seen)


def test_events_takes_a_typed_filter_and_refuses_anything_outside_it(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, events = seed_store(store)
    photo = store.view(entry.config.run_id)
    assert len(photo.events(EventFilter())) == len(events)
    assert {e.tick for e in photo.events(EventFilter(ticks=(1, 2)))} == {1, 2}
    assert {e.persona_id for e in photo.events(EventFilter(persona_ids=("p-000001",)))} == {"p-000001"}
    assert {e.payload.kind for e in photo.events(EventFilter(kinds=("turn",)))} == {"turn"}
    with pytest.raises(TypeError):
        photo.events({"kinds": ("turn",)})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        photo.events("turn")  # type: ignore[arg-type]


def test_verbatims_returns_frozen_models_grouped_as_asked(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, _ = seed_store(store)
    photo = store.view(entry.config.run_id)
    by_persona = photo.verbatims(VerbatimGrouping.PERSONA)
    assert by_persona and all(isinstance(group, SimBaseModel) for group in by_persona)
    assert {group.key for group in by_persona} == {"p-000001"}
    assert by_persona[0].records[0].text == "the protein claim would get me"
    by_tick = photo.verbatims(VerbatimGrouping.TICK)
    assert [group.key for group in by_tick] == ["1"]
    by_subject = photo.verbatims(VerbatimGrouping.SUBJECT)
    assert [group.key for group in by_subject] == [stimulus_id(1)]
    with pytest.raises(TypeError):
        photo.verbatims("persona")  # type: ignore[arg-type]


def test_resolve_returns_exactly_the_referenced_events(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, events = seed_store(store)
    photo = store.view(entry.config.run_id)
    wanted = [events[4].event_id, events[0].event_id]
    assert [e.event_id for e in photo.resolve(wanted)] == wanted
    with pytest.raises(KeyError):
        photo.resolve([events[0].event_id, "ev-00000000000000000000000000"])
    with pytest.raises(TypeError):
        photo.resolve(events[0].event_id)  # type: ignore[arg-type]


def test_nothing_returned_exposes_storage(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, events = seed_store(store)
    photo = store.view(entry.config.run_id)
    models = [
        *photo.events(EventFilter(ticks=(0, 0))),
        photo.beliefs("p-000001"),
        *photo.edges(),
        *photo.verbatims(VerbatimGrouping.PERSONA),
    ]
    assert models
    for model in models:
        assert isinstance(model, SimBaseModel)
        rendered = model.model_dump_json().lower()
        for leak in ("sqlite", "parquet", ".db", "cursor", "connection", "/tmp", "/runs/"):
            assert leak not in rendered, f"{type(model).__name__} exposes {leak}"
    with pytest.raises(UnknownRunError):
        store.view("run-00000000000000000000000000")


def test_an_empty_filter_asks_for_everything_live(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, events = seed_store(store)
    assert len(store.view(entry.config.run_id).events(EventFilter())) == len(events)
