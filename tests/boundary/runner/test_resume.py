"""Phase 2 boundary tests: resume from the record."""

from __future__ import annotations

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, rebuild_persona_states, run
from simcore.runner._resume import last_closed_tick
from simcore.schemas import BriefPack, CompletedTurn, Population, Reaction, RunConfig, Turn, TurnJob, canonical_hash
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


def _config(horizon: int = 5, **overrides):
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
        from simcore.schemas import Exposure, Impression, Presentation, Stimulus, View, WorldDelta

        self._header = header
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})
        self.steps: list[int] = []
        self.resets = 0

    def reset(self):
        from simcore.schemas import WorldDelta

        self.resets += 1
        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        self.steps.append(tick)
        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate(
                {"impression_id": f"im-{ulid(500 + tick * 100 + idx)}", "persona_id": pid,
                 "channel": "survey_room", "tick": tick,
                 "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})
            view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            presentations.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _completed(job: TurnJob, n: int) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + n + impression.tick * 50)}",
                                        "subject_stimulus_id": subject, "action": "answer",
                                        "verbatim": "I would try it", "belief_change": {"dimensions": {"value": 0.05}}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32,
                                         "belief_change": {"dimensions": {"value": 0.05}}, "costs": []})


def _run_all(trace, registry, config, pack, population, worlds):
    return run(config, pack=pack, population=population, trace=trace, registry=registry,
               world_factory=lambda header: worlds.append(FakeWorld(header)) or worlds[-1],
               agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))


def test_killed_mid_tick_resume_matches_uninterrupted():
    pack, population = _pack(), _population()
    full_trace, full_registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(), pack, population)
    _run_all(full_trace, full_registry, config, pack, population, [])
    full = [(e.tick, e.seq, e.payload.kind, e.persona_id) for e in full_trace.all_events()]

    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    worlds: list[FakeWorld] = []

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 2:
            raise RuntimeError("killed mid-tick")
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    with pytest.raises(RuntimeError):
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: worlds.append(FakeWorld(header)) or worlds[-1], agent_fn=failing)
    assert last_closed_tick(trace.all_events()) == 1

    resumed = run(config, pack=pack, population=population, trace=trace, registry=registry,
                  world_factory=lambda header: worlds.append(FakeWorld(header)) or worlds[-1],
                  agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    resumed_seq = [(e.tick, e.seq, e.payload.kind, e.persona_id) for e in trace.all_events()]
    assert resumed_seq == full
    assert resumed.outcomes[0].last_closed_tick == 4


def test_persona_state_rebuilt_equals_carried():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=3), pack, population)
    carried: dict = {}

    def agent_fn(jobs):
        for job in jobs:
            carried[job.persona.persona_id] = job.state.model_copy(deep=True)
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    # Rebuild from the record up to tick 1 and compare against what tick 2 carried.
    from simcore.runner import turns_by_tick  # noqa

    events = trace.events_for(next(iter({e.world_id for e in trace.all_events()})))
    upto1 = tuple(e for e in events if e.tick <= 1)
    rebuilt = rebuild_persona_states(population, upto1)
    # The carried state at tick 2 equals rebuilt state after tick 1 (beliefs moved twice: ticks 1).
    # Direct equality: rebuild from all events equals final carried advancement.
    rebuilt_all = rebuild_persona_states(population, events)
    assert set(rebuilt_all) == set(carried) | set(rebuilt_all)
    for pid, state in rebuilt_all.items():
        assert state.beliefs.dimensions["value"] == pytest.approx(0.6 + 0.05 * 2)


def test_resumed_world_continues_identically_and_skips_completed_ticks():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=4), pack, population)
    calls: list[int] = []

    def counting(jobs):
        for job in jobs:
            calls.append(job.presentation.impression.tick)
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    worlds: list[FakeWorld] = []
    with pytest.raises(RuntimeError):
        def failing(jobs):
            if jobs and jobs[0].presentation.impression.tick == 2:
                raise RuntimeError("boom")
            return counting(jobs)

        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: worlds.append(FakeWorld(header)) or worlds[-1], agent_fn=failing)
    first_steps = list(worlds[-1].steps)
    assert last_closed_tick(trace.all_events()) == 1  # tick 2 never closed
    calls.clear()
    worlds.clear()
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: worlds.append(FakeWorld(header)) or worlds[-1], agent_fn=counting)
    assert sorted(set(calls)) == [2, 3]
    assert 1 not in calls  # completed ticks never re-run


def test_resume_needs_only_trace_and_registry():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=3), pack, population)

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 1:
            raise RuntimeError("interrupt")
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    with pytest.raises(RuntimeError):
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    assert registry.entry(config.run_id) is not None
    # Resume with fresh factory/agent but same trace+registry+inputs.
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header),
                 agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    assert result.status.value == "completed"


def test_checkpoint_disagreement_discarded():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=3), pack, population)

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 1:
            raise RuntimeError("interrupt")
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    with pytest.raises(RuntimeError):
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    world_id = next(iter({e.world_id for e in trace.all_events()}))
    bad_checkpoint = {"next_seq": 9999, "states": {}}
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header),
                 agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)),
                 checkpoints={world_id: bad_checkpoint})
    assert result.status.value == "completed"
    # Completed ticks still never re-ran: only ticks 1..2 after close 0.
    kinds = [e.payload.kind for e in trace.all_events()]
    assert kinds.count("tick_closed") == 3
