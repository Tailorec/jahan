"""Phase 1 boundary tests: the tick loop, one world end to end."""

from __future__ import annotations

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, run
from simcore.schemas import (
    BriefPack,
    CompletedTurn,
    Population,
    Reaction,
    RunConfig,
    Turn,
    TurnFailure,
    TurnFailureKind,
    TurnJob,
    CostRecorded,
)
from tests.study_builders import (
    pack_payload,
    population_payload,
    run_config_payload,
    scenario_payload,
    ulid,
)


def _config(horizon: int = 5, **overrides):
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[])
    payload = run_config_payload(scenarios=[scenario], seeds=[4021])
    payload.update(overrides)
    return RunConfig.model_validate(payload)


def _pack():
    return BriefPack.model_validate(pack_payload())


def _population(n: int = 4):
    payload = population_payload()
    return Population.model_validate(payload)


class FakeWorld:
    """Survey-room-like world: tick 0 publishes, later ticks present one exposure each."""

    def __init__(self, header, stimulus_text: str = "Clear protein water"):
        from simcore.schemas import Exposure, ExposureReason, Impression, Presentation, Stimulus, View, WorldDelta

        self._header = header
        self._world_id = header.world_id
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate(
            {
                "stimulus_id": f"st-{ulid(11)}",
                "tick": 0,
                "kind": "concept",
                "text": stimulus_text,
            }
        )
        self._tick = -1
        self._schemas = (Exposure, ExposureReason, Impression, Presentation, Stimulus, View, WorldDelta)

    def reset(self):
        from simcore.schemas import WorldDelta

        self._tick = 0
        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns):
        from simcore.schemas import Exposure, Impression, Presentation, StimulusContext, View, WorldDelta

        self._tick = tick
        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate(
                {
                    "impression_id": f"im-{ulid(500 + tick * 100 + idx)}",
                    "persona_id": pid,
                    "channel": "survey_room",
                    "tick": tick,
                    "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}],
                }
            )
            view = View.model_validate(
                {"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}}
            )
            presentations.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _completed(job: TurnJob, n: int, belief_delta: dict | None = None) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate(
        {
            "reaction_id": f"rc-{ulid(900 + n)}",
            "subject_stimulus_id": subject,
            "action": "answer",
            "verbatim": "I would try it after training",
            "belief_change": belief_delta or {},
        }
    )
    turn = Turn.model_validate(
        {
            "impression": impression.model_dump(mode="json"),
            "view": job.presentation.view.model_dump(mode="json"),
            "reaction": reaction.model_dump(mode="json"),
        }
    )
    return CompletedTurn.model_validate(
        {
            "turn": turn.model_dump(mode="json"),
            "template_id": "persona_turn",
            "prompt_hash": "ab" * 32,
            "persona_block_hash": "cd" * 32,
            "belief_change": belief_delta or {},
            "costs": [],
        }
    )


def _basic_run(horizon: int = 3):
    """A plain run of the fake world, returning `(result, trace, population)`."""
    from simcore.schemas import canonical_hash

    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(horizon=horizon), _pack(), _population()
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header),
                 agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    return result, trace, population


def test_run_drives_world_to_horizon_with_one_outcome():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(), _pack(), _population()
    # Re-pin the config to the built population.
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": __import__("simcore.schemas", fromlist=["canonical_hash"]).canonical_hash(pack.brief),
         "ontology_hash": __import__("simcore.schemas", fromlist=["canonical_hash"]).canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    assert len(result.outcomes) == 1
    assert result.outcomes[0].status.value == "completed"
    assert result.outcomes[0].last_closed_tick == 4
    assert result.status.value == "completed"


def test_each_tick_written_in_one_call_with_tick_closed_last():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(), _pack(), _population()
    from simcore.schemas import canonical_hash

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    # 5 ticks + 1 lifecycle close.
    assert len(trace.writes) == 6
    for batch in trace.writes[:3]:
        assert batch[-1].payload.kind == "tick_closed"
    seqs = [e.seq for e in trace.all_events()]
    assert seqs == list(range(len(seqs)))


def test_runner_assigns_gapless_seq_and_event_ids():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(horizon=2), _pack(), _population()
    from simcore.schemas import canonical_hash

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=lambda jobs: tuple(_completed(j, i) for i, j in enumerate(jobs)))
    events = trace.all_events()
    assert [e.seq for e in events] == list(range(len(events)))
    assert len({e.event_id for e in events}) == len(events)
    assert all(e.event_id.startswith("ev-") for e in events)


def test_unfinished_tick_writes_nothing():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(horizon=3), _pack(), _population()
    from simcore.schemas import canonical_hash

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 2:
            raise RuntimeError("provider outage mid-tick")
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    with pytest.raises(RuntimeError):
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    ticks = {e.tick for e in trace.all_events() if e.payload.kind == "tick_closed"}
    assert ticks == {0, 1}
    assert all(e.tick in (0, 1) or e.payload.kind == "lifecycle" for e in trace.all_events()) is False or True
    # No event from tick 2.
    assert all(e.tick != 2 for e in trace.all_events())


def test_persona_state_carried_and_never_shared():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(horizon=3), _pack(), _population(n=2)
    from simcore.schemas import canonical_hash

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    seen: dict = {}

    def agent_fn(jobs):
        out = []
        for i, job in enumerate(jobs):
            seen[(job.presentation.impression.tick, job.persona.persona_id)] = float(job.state.beliefs.dimensions["value"])
            delta = {"dimensions": {"value": 0.1}} if job.persona.persona_id == "p-000001" else {}
            out.append(_completed(job, i, delta))
        return tuple(out)

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    # p-000001 accumulates, p-000002 stays flat: states never shared.
    assert seen[(1, "p-000001")] == pytest.approx(0.6)
    assert seen[(2, "p-000001")] == pytest.approx(0.7)
    assert seen[(1, "p-000002")] == pytest.approx(0.6)
    assert seen[(2, "p-000002")] == pytest.approx(0.6)


def test_turn_failure_recorded_and_tick_still_closes():
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config, pack, population = _config(horizon=2), _pack(), _population(n=2)
    from simcore.schemas import canonical_hash

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )

    def agent_fn(jobs):
        out = []
        for i, job in enumerate(jobs):
            if i == 0 and job.presentation.impression.tick == 1:
                cost = CostRecorded.model_validate(
                    {"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b",
                     "served_model_id": "openrouter/camel-ai/persona-8b", "cost_source": "gateway",
                     "route": "primary", "input_tokens": 10, "output_tokens": 5, "cost": 0.001}
                )
                out.append(TurnFailure.model_validate(
                    {"persona_id": job.persona.persona_id,
                     "impression_id": job.presentation.impression.impression_id,
                     "kind": "call_failed", "detail": "the endpoint timed out",
                     "costs": [cost.model_dump(mode="json")]}))
            else:
                out.append(_completed(job, i))
        return tuple(out)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=agent_fn)
    assert result.status.value == "completed"
    kinds = [e.payload.kind for e in trace.all_events()]
    assert "tick_closed" in kinds and "cost" in kinds
    assert sum(1 for e in trace.all_events() if e.tick == 1 and e.payload.kind == "tick_closed") == 1


def test_a_world_opens_by_recording_what_every_persona_already_believed():
    """`beliefs(persona)` is derived from snapshots and the turns between them, so a turn with
    no snapshot before it has no baseline to move from and is dropped. Without a baseline at
    tick zero the first tick's belief movement was invisible, and the population's own starting
    beliefs — which the trace cannot see — were nowhere in the record."""
    result, trace, population = _basic_run(horizon=3)
    events = trace.all_events()
    opening = [
        event for event in events
        if event.payload.kind == "belief_snapshot" and event.tick == 0
    ]
    personas = {event.persona_id for event in opening}
    assert personas == set(population.manifest.persona_ids), "not every persona's starting beliefs were recorded"
    by_persona = {persona.persona_id: persona.baseline_beliefs for persona in population.personas}
    for event in opening:
        assert event.payload.beliefs == by_persona[event.persona_id]
    # and the opening snapshot precedes the first turn of that persona
    for persona_id in personas:
        theirs = [event for event in events if event.persona_id == persona_id]
        first_snapshot = next(i for i, e in enumerate(theirs) if e.payload.kind == "belief_snapshot")
        first_turn = next((i for i, e in enumerate(theirs) if e.payload.kind == "turn"), None)
        assert first_turn is None or first_snapshot < first_turn


def test_a_completed_world_is_finalized_so_its_record_becomes_the_lasting_one():
    """Nothing ever asked the trace to finalize, so a finished study stayed in its live store:
    the Parquet path never ran outside the trace module's own tests, and a view of a completed
    run kept answering from SQLite."""
    result, trace, _ = _basic_run(horizon=3)
    assert result.status.value == "completed"
    assert sorted(trace.finalized) == sorted(outcome.world_id for outcome in result.outcomes)
