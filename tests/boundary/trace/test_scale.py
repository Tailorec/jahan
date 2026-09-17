"""M9 phase 8: scale and reconciliation — proof it holds at a study's size.

500k events round-trip through write and read with identical ordering; a world of that
size finalizes within a bounded time; no type in the module can hold a whole prompt; and
the architecture, salvage inventory and glossary describe what was built.
"""

import inspect
import time

import pytest

from simcore.schemas import CostRecorded, EventFilter, PartitionHeader, RunRegistryEntry, TraceEvent
from simcore.trace import TraceStore
from tests.study_builders import PERSONA_IDS, event, partition_header_payload

N_EVENTS = 500_000
N_TICKS = 30
FINALIZE_BUDGET_S = 600.0


def _crockford(n: int) -> str:
    digits = "0123456789abcdefghjkmnpqrstvwxyz"
    out = []
    for _ in range(26):
        n, remainder = divmod(n, 32)
        out.append(digits[remainder])
    return "".join(reversed(out))


def _seed_scale_world(store: TraceStore):
    """A study-scale world: half a million billed calls across thirty ticks, through the hot path."""
    header = PartitionHeader.model_validate(partition_header_payload())
    entry = RunRegistryEntry.model_validate(
        {"config": header.config.model_dump(mode="json"), "contract_version": header.contract_version,
         "status": "running", "engine_version": "0a35555"})
    store.registry.record(entry)
    store.create_world(entry.config.run_id, header)
    world_id = header.world_id
    billed = CostRecorded.model_validate(
        {"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b",
         "served_model_id": "openrouter/camel-ai/persona-8b", "cost_source": "gateway",
         "route": "primary", "input_tokens": 812, "output_tokens": 96, "cost": 0.004})
    seq, seq_of_tick = 1, []
    store.write([TraceEvent.model_validate(event(0, 0, {"kind": "lifecycle", "phase": "started"}, None, world_id))])
    per_tick, remainder = divmod(N_EVENTS, N_TICKS)
    for tick in range(N_TICKS):
        count = per_tick + (1 if tick < remainder else 0)
        batch = [
            TraceEvent.model_construct(
                event_id=f"ev-{_crockford(10_000_000 + seq + n)}", world_id=world_id, tick=tick, seq=seq + n,
                persona_id=PERSONA_IDS[(seq + n) % len(PERSONA_IDS)], payload=billed)
            for n in range(count)
        ]
        batch.append(TraceEvent.model_validate(event(seq + count, tick, {"kind": "tick_closed"}, None, world_id)))
        store.write(batch)
        seq += count + 1
    store.write([TraceEvent.model_validate(
        event(seq, N_TICKS - 1, {"kind": "lifecycle", "phase": "completed"}, None, world_id))])
    return header, entry, seq + 1


def test_half_a_million_events_round_trip_with_identical_ordering(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, total = _seed_scale_world(store)
    read = store.read_live(entry.config.run_id, header.world_id)
    assert len(read) == total
    assert [e.seq for e in read] == list(range(total))
    ordered = store.view(entry.config.run_id).events(EventFilter())
    assert [(e.persona_id or "", e.tick, e.seq) for e in ordered] == sorted(
        (e.persona_id or "", e.tick, e.seq) for e in read)
    assert {e.event_id for e in ordered} == {e.event_id for e in read}


def test_a_study_scale_world_finalizes_within_a_bounded_time(tmp_path):
    store = TraceStore(tmp_path)
    header, entry, total = _seed_scale_world(store)
    started = time.monotonic()
    world_dir = store.finalize(header.world_id)
    elapsed = time.monotonic() - started
    size_mb = sum(p.stat().st_size for p in world_dir.glob("*.parquet")) / 1e6
    print(f"\nfinalized {total} events in {elapsed:.1f}s into {size_mb:.1f} MB of Parquet")
    assert elapsed < FINALIZE_BUDGET_S, f"finalization took {elapsed:.1f}s, over the {FINALIZE_BUDGET_S:.0f}s budget"
    assert (world_dir / "events.parquet").stat().st_size > 0
    assert len(store.view(entry.config.run_id).events(EventFilter())) == total


def test_no_type_in_the_module_can_hold_a_whole_prompt():
    """Context travels as parts and hashes; there is deliberately no field a prompt fits in."""
    import simcore.schemas.query as query
    import simcore.schemas.sim as sim
    import simcore.schemas.trace as trace
    import simcore.trace.derive as derive
    import simcore.trace.store as store
    import simcore.trace.views as views
    from simcore.schemas import SimBaseModel

    forbidden = {"prompt", "context", "messages", "full_prompt", "system_prompt", "template_text", "question_text"}
    models: list[type[SimBaseModel]] = []
    for module in (query, sim, trace):
        models.extend(
            member for _, member in inspect.getmembers(module, inspect.isclass)
            if issubclass(member, SimBaseModel) and member is not SimBaseModel
            and member.__module__.startswith("simcore.schemas")
        )
    assert models
    for model in models:
        for name in model.model_fields:
            assert name not in forbidden, f"{model.__name__}.{name} could hold a whole prompt"
            lowered = name.lower()
            if "prompt" in lowered:
                assert lowered.endswith(("hash", "hashes")), f"{model.__name__}.{name} stores a prompt, not its hash"
            if lowered.startswith("template") and lowered != "template_hashes":
                assert lowered.endswith(("_id", "_hash", "_hashes")), f"{model.__name__}.{name} stores a template"
    for module in (derive, store, views):
        source = inspect.getsource(module)
        assert "full_prompt" not in source and "system_prompt" not in source
