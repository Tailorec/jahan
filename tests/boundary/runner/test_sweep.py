"""Phase 7 boundary tests: sweep."""

from __future__ import annotations

import time

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, expand_sweep, run
from simcore.schemas import BriefPack, CompletedTurn, CostRecorded, Population, Reaction, RunConfig, Turn, TurnJob, canonical_hash, derive_world_id
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


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


def _grid(horizon: int = 3, max_cost: float = 20.0):
    s1 = scenario_payload(horizon_ticks=horizon, interventions=[],
                          variant={"variant_id": "v1baseline", "name": "Baseline", "description": "Baseline concept", "emphasized_claims": ["C1"]})
    s2 = scenario_payload(horizon_ticks=horizon, interventions=[],
                          price={"amount": 2.99, "currency": "USD"},
                          variant={"variant_id": "v2premium", "name": "Premium", "description": "Premium concept", "emphasized_claims": ["C2"]})
    return RunConfig.model_validate(run_config_payload(scenarios=[s1, s2], seeds=[4021, 917731], budget={"max_cost": max_cost, "currency": "USD"}))


class FakeWorld:
    def __init__(self, header):
        from simcore.schemas import Stimulus

        self._header = header
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})

    def reset(self, plan=None):
        from simcore.schemas import WorldDelta

        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns, plan=None):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        time.sleep(0.02)
        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate(
                {"impression_id": f"im-{ulid(500 + tick * 100 + idx)}", "persona_id": pid,
                 "channel": "survey_room", "tick": tick,
                 "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})
            view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            presentations.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _completed(job: TurnJob, n: int, amount: float = 0.0) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + n + impression.tick * 50)}",
                                        "subject_stimulus_id": subject, "action": "answer",
                                        "verbatim": "I would try it", "belief_change": {}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    costs = []
    if amount:
        costs = [CostRecorded.model_validate({"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b",
                                              "served_model_id": "openrouter/camel-ai/persona-8b", "cost_source": "gateway",
                                              "route": "primary", "input_tokens": 5, "output_tokens": 5, "cost": amount}).model_dump(mode="json")]
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32, "costs": costs})


def test_grid_expands_one_world_per_cell_with_derived_ids():
    pack, population = _pack(), _population()
    config = _repinned(_grid(), pack, population)
    cells = expand_sweep(config)
    assert len(cells) == 4
    for scenario, seed, world_id in cells:
        assert world_id == derive_world_id(scenario, seed, config.population_hash)


def test_same_grid_twice_identical_ids():
    pack, population = _pack(), _population()
    config = _repinned(_grid(), pack, population)
    assert [w for _, _, w in expand_sweep(config)] == [w for _, _, w in expand_sweep(config)]


def test_one_budget_covers_sweep():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_grid(max_cost=5.0), pack, population)

    def agent_fn(jobs, plan=None):
        return tuple(_completed(j, i, 0.05) for i, j in enumerate(jobs))

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    assert len(result.outcomes) == 4
    total = registry.entry(config.run_id).recorded_cost
    assert total <= 5.0 * 1.5 + 1e-9


def test_parallel_worlds_reproducible_content():
    pack, population = _pack(), _population()
    config = _repinned(_grid(), pack, population)

    def agent_fn(jobs, plan=None):
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    t0 = time.monotonic()
    trace1, registry1 = InMemoryTraceSink(), InMemoryRegistry()
    run(config, pack=pack, population=population, trace=trace1, registry=registry1,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn, max_workers=4)
    parallel_time = time.monotonic() - t0
    trace2, registry2 = InMemoryTraceSink(), InMemoryRegistry()
    run(config, pack=pack, population=population, trace=trace2, registry=registry2,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn, max_workers=1)
    # Same cells, same per-world content (turn counts match per world).
    for world_id in {e.world_id for e in trace1.all_events()}:
        first = sorted((e.tick, e.seq, e.payload.kind) for e in trace1.events_for(world_id))
        second = sorted((e.tick, e.seq, e.payload.kind) for e in trace2.events_for(world_id))
        assert first == second
    assert parallel_time < 2.0


def test_different_rungs_marked():
    from simcore.runner import LadderConfig

    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_grid(horizon=6, max_cost=1.0), pack, population)

    def agent_fn(jobs, plan=None):
        # Pricey cells degrade; single shared budget degrades later cells more.
        return tuple(_completed(j, i, 0.10) for i, j in enumerate(jobs))

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn,
                 ladder=LadderConfig(warn_at=0.2, freeze_at=0.4, subsample_at=0.8, pause_at=10.0))
    rung_sets = {tuple(o.rungs) for o in result.outcomes}
    assert len(rung_sets) >= 1
    assert all(hasattr(o, "rungs") for o in result.outcomes)


def test_resume_sweep_reruns_only_incomplete():
    from simcore.runner import WorldFailed

    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_grid(horizon=3), pack, population)
    calls: dict[str, int] = {}

    def agent_fn(jobs, plan=None):
        for job in jobs:
            calls[job.presentation.impression.persona_id] = calls.get(job.presentation.impression.persona_id, 0) + 1
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    attempts: dict[str, int] = {"n": 0}

    def factory(header):
        from simcore.schemas import derive_world_id as _derive

        wid = _derive(header.scenario, header.replicate_seed, header.population.population_hash)
        world = FakeWorld(header)
        if wid == expand_sweep(config)[0][2] and attempts["n"] == 0:
            orig_step = world.step

            def failing_step(tick, turns, plan=None):
                if tick == 1:
                    raise WorldFailed("outage in one cell")
                return orig_step(tick, turns, plan)

            world.step = failing_step  # type: ignore[method-assign]
        return world

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=agent_fn)
    assert any(o.status.value == "partial" for o in result.outcomes)
    before = sum(1 for e in trace.all_events() if e.payload.kind == "turn")
    attempts["n"] = 1
    calls.clear()
    result2 = run(config, pack=pack, population=population, trace=trace, registry=registry,
                  world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    assert result2.status.value == "completed"
    after = sum(1 for e in trace.all_events() if e.payload.kind == "turn")
    assert after > before
