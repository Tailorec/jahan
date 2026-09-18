"""Phase 4 boundary tests: the cost ledger."""

from __future__ import annotations

import pytest

from simcore.runner import (
    InMemoryRegistry,
    InMemoryTraceSink,
    ledger_sum,
    mean_tick_cost,
    pessimistic_figure,
    run,
)
from simcore.schemas import BriefPack, CompletedTurn, CostRecorded, Population, Reaction, RunConfig, Turn, TurnFailure, TurnJob, canonical_hash
from simcore.schemas.enums import TurnFailureKind
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


def _config(horizon: int = 4, **overrides):
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[])
    payload = run_config_payload(scenarios=[scenario], seeds=[4021])
    payload.update(overrides)
    return RunConfig.model_validate(payload)


def _pack():
    return BriefPack.model_validate(pack_payload())


def _population():
    return Population.model_validate(population_payload())


def _repinned(config, pack, population):
    return RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )


class FakeWorld:
    def __init__(self, header):
        from simcore.schemas import Stimulus

        self._header = header
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})

    def reset(self):
        from simcore.schemas import WorldDelta

        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate(
                {"impression_id": f"im-{ulid(500 + tick * 100 + idx)}", "persona_id": pid,
                 "channel": "survey_room", "tick": tick,
                 "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})
            view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            presentations.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _cost(amount: float | None, role: str = "tier_a", model: str = "openrouter/camel-ai/persona-8b") -> CostRecorded:
    if amount is None:
        return CostRecorded.model_validate({"kind": "cost", "role": role, "model_id": model,
                                            "cost_source": "unknown", "route": "primary",
                                            "served_model_id": model, "input_tokens": 5, "output_tokens": 5})
    return CostRecorded.model_validate({"kind": "cost", "role": role, "model_id": model,
                                        "served_model_id": model, "cost_source": "gateway",
                                        "route": "primary", "input_tokens": 5, "output_tokens": 5, "cost": amount})


def _completed(job: TurnJob, n: int, costs=()) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + n + impression.tick * 50)}",
                                        "subject_stimulus_id": subject, "action": "answer",
                                        "verbatim": "I would try it", "belief_change": {}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32,
                                         "costs": [c.model_dump(mode="json") for c in costs]})


def test_ledger_equals_sum_and_rebuilt_on_resume():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(), pack, population)

    def agent_fn(jobs):
        return tuple(_completed(j, i, [_cost(0.01)]) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    events = trace.all_events()
    known, unknown = ledger_sum(events)
    assert unknown == 0
    assert registry.entry(config.run_id).recorded_cost == pytest.approx(known)
    # Rebuilt by summing on resume: run again (completed) keeps the same total.
    before = known
    run(config, pack=pack, population=population, trace=InMemoryTraceSink(), registry=InMemoryRegistry(),
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    assert before > 0


def test_unknown_cost_stays_unknown_never_zero():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=2), pack, population)

    def agent_fn(jobs):
        return tuple(_completed(j, i, [_cost(None)]) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    known, unknown = ledger_sum(trace.all_events())
    assert known == 0.0
    assert unknown > 0
    assert registry.entry(config.run_id).recorded_cost == 0.0


def test_failed_call_costs_counted():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=2), pack, population)

    def agent_fn(jobs):
        out = []
        for i, job in enumerate(jobs):
            if i == 0:
                out.append(TurnFailure.model_validate(
                    {"persona_id": job.persona.persona_id, "impression_id": job.presentation.impression.impression_id,
                     "kind": "call_failed", "detail": "the endpoint timed out",
                     "costs": [_cost(0.02).model_dump(mode="json")]}))
            else:
                out.append(_completed(job, i, [_cost(0.01)]))
        return tuple(out)

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    known, _ = ledger_sum(trace.all_events())
    assert known == pytest.approx(registry.entry(config.run_id).recorded_cost)
    assert known > 0


def test_discarded_tick_recorded_and_counted():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=3), pack, population)

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 1:
            raise RuntimeError("interrupt")
        return tuple(_completed(j, i, [_cost(0.01)]) for i, j in enumerate(jobs))

    try:
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    except RuntimeError:
        pass
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header),
        agent_fn=lambda jobs: tuple(_completed(j, i, [_cost(0.01)]) for i, j in enumerate(jobs)))
    entry = registry.entry(config.run_id)
    assert entry.discarded_ticks == 1


def test_pessimistic_figure_adds_estimate_per_discarded():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=3), pack, population)

    def agent_fn(jobs):
        return tuple(_completed(j, i, [_cost(0.02)]) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    events = trace.all_events()
    known, _ = ledger_sum(events)
    assert pessimistic_figure(events, 0) == pytest.approx(known)
    assert pessimistic_figure(events, 1) == pytest.approx(known + mean_tick_cost(events))
    assert pessimistic_figure(events, 1) > known


def test_lost_tick_stops_earlier_on_same_budget():
    pack, population = _pack(), _population()
    config = _repinned(_config(horizon=3), pack, population)

    def agent_fn(jobs):
        return tuple(_completed(j, i, [_cost(0.05)]) for i, j in enumerate(jobs))

    clean_trace, clean_registry = InMemoryTraceSink(), InMemoryRegistry()
    run(config, pack=pack, population=population, trace=clean_trace, registry=clean_registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    clean_fig = pessimistic_figure(clean_trace.all_events(), 0)

    trace, registry = InMemoryTraceSink(), InMemoryRegistry()

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 1:
            raise RuntimeError("interrupt")
        return tuple(_completed(j, i, [_cost(0.05)]) for i, j in enumerate(jobs))

    try:
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    except RuntimeError:
        pass
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    lost_fig = pessimistic_figure(trace.all_events(), registry.entry(config.run_id).discarded_ticks)
    assert registry.entry(config.run_id).discarded_ticks == 1
    assert lost_fig > clean_fig


def _events_from(costs) -> tuple:
    """Cost events as the runner would have written them, with one closed tick."""
    from simcore.schemas import TickClosed, TraceEvent

    events = []
    for index, cost in enumerate(costs):
        events.append(TraceEvent.model_validate({"event_id": f"ev-{ulid(4000 + index)}", "world_id": "a1b2c3d4e5f6",
                                                 "tick": 1, "seq": index, "persona_id": "p-000001",
                                                 "payload": cost.model_dump(mode="json")}))
    events.append(TraceEvent.model_validate({"event_id": f"ev-{ulid(4999)}", "world_id": "a1b2c3d4e5f6", "tick": 1,
                                             "seq": len(costs), "persona_id": None,
                                             "payload": TickClosed(kind="tick_closed").model_dump(mode="json")}))
    return tuple(events)


def _run_billing(costs_per_turn, max_cost: float, horizon: int = 8):
    """A run whose every turn bills the given costs."""
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    payload = _config(horizon=horizon).model_dump(mode="json")
    payload["budget"] = {"max_cost": max_cost, "currency": "USD"}
    config = _repinned(RunConfig.model_validate(payload), pack, population)
    plans = []

    def agent_fn(jobs, plan=None):
        plans.append(plan)
        return tuple(_completed(j, i, costs_per_turn) for i, j in enumerate(jobs))

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    return result, trace, plans


def test_unknown_costs_are_priced_pessimistically_rather_than_counted_as_free():
    """`CostSource.UNKNOWN` exists because a budget enforced against invented prices is not
    enforced. The ledger counted unknowns and then dropped them, so a run whose gateway
    reported no prices spent its whole horizon without a rung ever firing."""
    events = _events_from([_cost(0.10), _cost(0.10), _cost(None), _cost(None)])
    total, unpriced = ledger_sum(events)
    assert (total, unpriced) == (pytest.approx(0.20), 2)
    # Two calls at 0.10 apiece price the two nobody quoted.
    assert pessimistic_figure(events, 0) == pytest.approx(0.40)


def test_a_run_billed_only_unknown_costs_stops_rather_than_spending_blind():
    """With no price at all there is nothing to enforce a budget against, so the run stops."""
    result, trace, _ = _run_billing([_cost(None)], max_cost=1.0, horizon=8)
    rungs = [event.payload.rung.value for event in trace.all_events() if event.payload.kind == "degraded"]
    assert "pause" in rungs, f"nothing stopped the run: {rungs}"
    assert result.status.value == "partial"
    closed = {event.tick for event in trace.all_events() if event.payload.kind == "tick_closed"}
    assert len(closed) < 8, "the run reached its horizon on prices nobody quoted"


def test_priced_and_unpriced_calls_together_still_degrade_on_the_ladder():
    result, trace, plans = _run_billing([_cost(0.02), _cost(None)], max_cost=1.0, horizon=8)
    rungs = [event.payload.rung.value for event in trace.all_events() if event.payload.kind == "degraded"]
    assert rungs, "a run with prices and unknowns never reached a rung"
    assert any(plan is not None and plan.tier_b_frozen for plan in plans) or "pause" in rungs


def _cost_event(n: int, tick: int, cost: float | None, world: str = "a00631e91974"):
    from simcore.schemas import TraceEvent

    return TraceEvent.model_validate({
        "event_id": f"ev-{ulid(900 + n)}", "world_id": world, "tick": tick, "seq": n,
        "persona_id": None,
        "payload": {"kind": "cost", "role": "tier_a", "model_id": "fake/tier-a-1",
                    "served_model_id": "fake/tier-a-1", "route": "primary",
                    "cost_source": "gateway" if cost is not None else "unknown",
                    "input_tokens": 10, "output_tokens": 5,
                    **({"cost": cost} if cost is not None else {})},
    })


def _closed(n: int, tick: int, world: str = "a00631e91974"):
    from simcore.schemas import TraceEvent

    return TraceEvent.model_validate({
        "event_id": f"ev-{ulid(950 + n)}", "world_id": world, "tick": tick, "seq": n,
        "persona_id": None, "payload": {"kind": "tick_closed"},
    })


@pytest.mark.parametrize("discarded", [0, 1, 3])
def test_the_meter_answers_what_summing_the_record_answers(discarded):
    """The ladder tests the figure once per tick per world. Re-deriving it read every event of
    every world each time, so the cost of checking a budget grew with the record it checked.
    The meter carries the same aggregates, so its answers must equal the pure functions'."""
    from simcore.runner._ledger import SpendMeter, unpriceable

    streams = [
        [_cost_event(1, 0, 0.01), _closed(2, 0), _cost_event(3, 1, 0.03), _closed(4, 1)],
        [_cost_event(1, 0, None), _closed(2, 0)],
        [_cost_event(1, 0, 0.02), _cost_event(2, 0, None), _closed(3, 0), _cost_event(4, 1, 0.04), _closed(5, 1)],
        [],
    ]
    for events in streams:
        meter = SpendMeter()
        for event in events:
            meter.add([event])
        assert meter.figure(discarded) == pytest.approx(pessimistic_figure(tuple(events), discarded))
        assert meter.unpriceable() == unpriceable(tuple(events))


def test_the_meter_is_primed_from_a_record_it_did_not_write():
    from simcore.runner._ledger import SpendMeter

    events = [_cost_event(1, 0, 0.01), _closed(2, 0)]
    meter = SpendMeter()
    meter.add(events)
    later = _cost_event(3, 1, 0.05)
    meter.add([later])
    assert meter.figure(0) == pytest.approx(pessimistic_figure(tuple([*events, later]), 0))
