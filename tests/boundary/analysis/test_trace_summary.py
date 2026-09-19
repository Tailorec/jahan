"""Phase 1: `trace_summary` — the five shapes joined once, written beside the report.

Belief histories, edges, grouped verbatims, event counts per kind and costs per role,
each from the shape that owns it; storage is reached no other way; two summaries of
one trace are identical; a study writes the file and a paused run writes what it has.
"""

import ast
import json
from collections import Counter
from pathlib import Path

from simcore import trace as trace_pkg
from simcore.analysis import trace_summary
from simcore.schemas import EventFilter, TraceSummary, VerbatimGrouping
from simcore.trace import TraceStore
from simcore.trace import derive as derive_shapes
from tests.boundary.trace.support import seed_header_and_entry, seed_store, write_by_tick


def _views(store: TraceStore, run_id: str):
    return {world_id: store.view(run_id, world_id) for world_id in store.world_ids(run_id)}


def test_every_quantity_matches_the_same_quantity_recomputed_from_raw_events(tmp_path):
    store = TraceStore(tmp_path / "trace")
    _, entry, _ = seed_store(store)
    views = _views(store, entry.config.run_id)
    summary = trace_summary(views, run_id=entry.config.run_id)

    raw = []
    for world_id in store.world_ids(entry.config.run_id):
        raw.extend(store.read_live(entry.config.run_id, world_id))
    assert {event.world_id for event in raw} == set(summary.worlds)

    for world in summary.per_world:
        scoped = [event for event in raw if event.world_id == world.world_id]
        assert dict(world.event_counts) == dict(Counter(event.payload.kind for event in scoped))
        assert world.max_tick == max(event.tick for event in scoped)
        assert world.edges == derive_shapes.derive_edges(scoped)
        for grouping in VerbatimGrouping:
            assert tuple(world.verbatim_groups[grouping.value]) == derive_shapes.derive_verbatims(
                scoped, grouping
            )
        snapshots = Counter(
            event.persona_id for event in scoped
            if event.payload.kind == "belief_snapshot" and event.persona_id is not None
        )
        assert world.belief_total_personas == len(snapshots)
        for history in world.belief_histories:
            assert history == derive_shapes.derive_beliefs(scoped, history.persona_id)

    cost_events = [event for event in raw if event.payload.kind == "cost"]
    assert sum(cost.calls for cost in summary.costs) == len(cost_events)
    known = sum(event.payload.cost for event in cost_events if event.payload.cost is not None)
    assert summary.recorded_cost == known
    assert summary.unknown_cost_calls == sum(1 for event in cost_events if event.payload.cost is None)


def test_two_summaries_of_one_trace_are_identical(tmp_path):
    store = TraceStore(tmp_path / "trace")
    _, entry, _ = seed_store(store)
    views = _views(store, entry.config.run_id)
    first = trace_summary(views, run_id=entry.config.run_id)
    second = trace_summary(views, run_id=entry.config.run_id)
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(TraceSummary.model_validate(json.loads(first.model_dump_json())), TraceSummary)


def test_the_summary_reaches_storage_only_through_the_five_shapes():
    """The module answers what the shapes answer: no path, no frame, no second way in."""
    source = (Path(trace_pkg.__file__).parent.parent / "analysis" / "_trace_summary.py").read_text()
    tree = ast.parse(source)
    allowed_views = {"events", "beliefs", "edges", "verbatims", "resolve"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"read_live", "read_finalized", "read_partition"}:
            raise AssertionError(f"trace_summary reads storage past the shapes: .{node.attr}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "view":
            assert node.attr in allowed_views, f"trace_summary asks the view for .{node.attr}"
    forbidden_imports = {"sqlite3", "pyarrow", "pandas", "numpy", "pathlib", "store", "finalize", "registry"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_imports, f"imports {alias.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_imports, f"imports from {node.module}"


def test_a_paused_run_writes_what_it_has(tmp_path):
    """A live view shows every closed tick and nothing more, so the summary of a
    run interrupted mid-way is the summary of its closed ticks."""
    from simcore.schemas import TraceEvent
    from tests.study_builders import partition_payload

    store = TraceStore(tmp_path / "trace")
    header, entry = seed_header_and_entry(store)
    payload = partition_payload()
    events = [TraceEvent.model_validate(record) for record in payload["events"]]
    first_tick = min(event.tick for event in events)
    write_by_tick(store, [event for event in events if event.tick == first_tick])

    summary = trace_summary(_views(store, entry.config.run_id), run_id=entry.config.run_id)
    assert summary.worlds
    for world in summary.per_world:
        assert world.max_tick == first_tick


def test_a_fake_study_writes_the_summary_beside_the_report(tmp_path, monkeypatch):
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "71"
    code, output = run_command(*fake_args(out, run_id))
    assert code == 0, output
    summary_path = out / run_id / "trace-summary.json"
    assert summary_path.is_file()
    summary = TraceSummary.model_validate(json.loads(summary_path.read_text()))
    assert summary.run_id == run_id and summary.worlds

    store = TraceStore(out / run_id / "trace")
    for world in summary.per_world:
        kinds = Counter(
            event.payload.kind
            for event in store.view(run_id, world.world_id).events(EventFilter())
        )
        assert dict(world.event_counts) == dict(kinds)
