"""M9 phase 4: the derived shapes — beliefs and edges computed from the record.

`beliefs(persona_id)` reads snapshots and the turns between them; `edges()` reads
word-of-mouth deliveries into `(u, v, channel, count, last_tick)`. Both match the same
quantities recomputed from raw events, neither reaches another persona's records, and the
derivation has exactly one implementation.
"""

import inspect
from pathlib import Path

import pytest

from simcore.schemas import TraceEvent
from simcore.trace import TraceStore, derive_beliefs, derive_edges
from simcore.trace import views as _views
from simcore.trace import derive as _derive
from tests.study_builders import beliefs_payload, event, stimulus_id, turn_event, turn_payload

from .support import seed_header_and_entry, seed_store


def _closes(world_id: str, ticks: range, start: int) -> list[TraceEvent]:
    return [TraceEvent.model_validate(event(start + n, tick, {"kind": "tick_closed"}, None, world_id))
            for n, tick in enumerate(ticks)]


def _belief_world(world_id: str, persona: str, start: int = 0) -> list[TraceEvent]:
    """Snapshot, then a turn, then a reflection — each moving what the last one left."""
    snapshot = TraceEvent.model_validate(
        event(start, 0, {"kind": "belief_snapshot", "beliefs": beliefs_payload()}, persona, world_id))
    turn = TraceEvent.model_validate(
        turn_event(start + 1, 1, turn_payload(persona, 1, [(1, "interest", 0.8)], {
            "subject_stimulus_id": stimulus_id(1), "action": "comment",
            "verbatim": "twenty grams is plenty",
            "belief_change": {"dimensions": {"value": 0.1}, "claim_credence": {"C1": 0.2}}}, n=21), persona))
    turn_dict = turn.model_dump(mode="json")
    turn_dict["world_id"] = world_id
    reflection = TraceEvent.model_validate(
        event(start + 2, 2, {"kind": "reflection", "trigger": "belief_shift",
                             "change": {"claim_credence": {"C2": -0.1}}}, persona, world_id))
    return [snapshot, TraceEvent.model_validate(turn_dict), reflection]


def test_beliefs_reconstructs_history_from_snapshots_and_turns(tmp_path):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    world_id = header.world_id
    store.write([*_belief_world(world_id, "p-000001"), *_closes(world_id, range(0, 3), 3)])
    history = store.view(header.config.run_id).beliefs("p-000001")
    assert [point.tick for point in history.points] == [0, 1, 2]
    assert history.points[0].beliefs.dimensions["value"] == pytest.approx(0.6)
    assert history.points[1].beliefs.dimensions["value"] == pytest.approx(0.7)
    assert history.points[1].beliefs.claim_credence["C1"] == pytest.approx(1.0)
    assert history.points[2].beliefs.claim_credence["C2"] == pytest.approx(0.2)
    assert history.points[2].beliefs.dimensions["value"] == pytest.approx(0.7)


def test_edges_returns_one_row_per_pair_channel_and_direction(tmp_path):
    store = TraceStore(tmp_path)
    _, entry, _ = seed_store(store)
    edges = store.view(entry.config.run_id).edges()
    assert [(e.u, e.v, e.channel.value, e.count, e.last_tick) for e in edges] == [
        ("p-000001", "p-000002", "social_feed", 1, 3),
        ("p-000001", "p-000003", "social_feed", 1, 4),
    ]


def test_derivations_match_the_raw_events_recomputed_by_hand(tmp_path):
    """The same quantities from the raw events, recomputed here without the module's help."""
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    world_id = header.world_id
    batch = _belief_world(world_id, "p-000001")
    store.write(batch)
    raw = store.read_live(header.config.run_id, world_id)
    # By hand: snapshot anchors, then each change applies and clamps.
    current = dict(beliefs_payload()["dimensions"])
    credence = dict(beliefs_payload()["claim_credence"])
    expected = [(0, dict(current), dict(credence))]
    for record in raw:
        change = None
        if record.payload.kind == "turn":
            change = record.payload.turn.reaction.belief_change
        elif record.payload.kind == "reflection":
            change = record.payload.change
        if change is None or record.persona_id != "p-000001":
            continue
        if record.payload.kind == "belief_snapshot":
            continue
        for dim, delta in change.dimensions.items():
            current[dim] = min(1.0, max(0.0, current[dim] + delta))
        for claim, delta in change.claim_credence.items():
            credence[claim] = min(1.0, max(0.0, credence.get(claim, 0.5) + delta))
        expected.append((record.tick, dict(current), dict(credence)))
    history = derive_beliefs(raw, "p-000001")
    assert [(p.tick, dict(p.beliefs.dimensions), dict(p.beliefs.claim_credence)) for p in history.points] == [
        (tick, dims, cred) for tick, dims, cred in expected if tick > 0 or True
    ][:1] + [
        (tick, dims, cred) for tick, dims, cred in expected[1:]
    ]
    # By hand: every wom exposure counts from its author to its viewer.
    authors = {}
    for record in raw:
        if record.payload.kind == "stimulus_published":
            authors[record.payload.stimulus.stimulus_id] = record.payload.stimulus.author
    counts: dict[tuple[str, str, str], list[int]] = {}
    for record in sorted(raw, key=lambda e: e.seq):
        if record.payload.kind != "turn":
            continue
        for exposure in record.payload.turn.impression.exposures:
            if exposure.reason.value != "wom":
                continue
            author = authors.get(exposure.stimulus_id)
            if author and author != record.persona_id:
                key = (author, record.persona_id, record.payload.turn.impression.channel.value)
                counts.setdefault(key, [0, 0])
                counts[key][0] += 1
                counts[key][1] = record.tick
    assert [(e.u, e.v, e.channel.value, e.count, e.last_tick) for e in derive_edges(raw)] == [
        (u, v, channel, count, last) for (u, v, channel), (count, last) in sorted(counts.items())
    ]


def test_neither_shape_reaches_another_personas_records(tmp_path):
    store = TraceStore(tmp_path)
    header, _ = seed_header_and_entry(store)
    world_id = header.world_id
    store.write([*_belief_world(world_id, "p-000001"), *_belief_world(world_id, "p-000002", start=10),
                 *_closes(world_id, range(0, 3), 20)])
    photo = store.view(header.config.run_id)
    first = photo.beliefs("p-000001")
    assert first.persona_id == "p-000001"
    assert [p.tick for p in first.points] == [0, 1, 2]
    assert photo.beliefs("p-000009").points == ()
    for edge in photo.edges():
        assert edge.u != edge.v


def test_the_derivation_has_exactly_one_implementation():
    package = Path(_derive.__file__).parent
    belief_impls = [p for p in package.glob("*.py") if "def derive_beliefs" in p.read_text()]
    edge_impls = [p for p in package.glob("*.py") if "def derive_edges" in p.read_text()]
    assert [p.name for p in belief_impls] == ["derive.py"]
    assert [p.name for p in edge_impls] == ["derive.py"]
    for cls in (_views.SqliteTraceView, _views.ParquetTraceView):
        assert "derive_beliefs" in inspect.getsource(cls.beliefs), f"{cls.__name__}.beliefs reimplements"
        assert "derive_edges" in inspect.getsource(cls.edges), f"{cls.__name__}.edges reimplements"
