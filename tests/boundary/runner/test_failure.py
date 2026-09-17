"""Phase 6 boundary tests: a world that fails."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, WorldFailed, run
from simcore.schemas import BriefPack, CompletedTurn, Population, Reaction, RunConfig, RunResult, Turn, TurnJob, canonical_hash, derive_world_id
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


def _config_two_worlds(horizon: int = 4):
    s1 = scenario_payload(horizon_ticks=horizon, interventions=[],
                          variant={"variant_id": "v1baseline", "name": "Baseline", "description": "Baseline concept", "emphasized_claims": ["C1"]})
    s2 = scenario_payload(horizon_ticks=horizon, interventions=[],
                          price={"amount": 2.99, "currency": "USD"},
                          variant={"variant_id": "v2premium", "name": "Premium", "description": "Premium concept", "emphasized_claims": ["C2"]})
    return RunConfig.model_validate(run_config_payload(scenarios=[s1, s2], seeds=[4021]))


class FakeWorld:
    def __init__(self, header, fail_at: int | None = None, fail_kind: str = "step"):
        from simcore.schemas import Stimulus

        self._header = header
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})
        self._fail_at = fail_at
        self._fail_kind = fail_kind

    def reset(self, plan=None):
        from simcore.schemas import WorldDelta

        if self._fail_at == 0:
            raise WorldFailed("corrupt scenario")
        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns, plan=None):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        if self._fail_at == tick:
            raise WorldFailed("provider outage")
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
                                        "verbatim": "I would try it", "belief_change": {}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32, "costs": []})


def _agent(jobs, plan=None):
    return tuple(_completed(j, i) for i, j in enumerate(jobs))


def test_one_world_raising_leaves_others_running():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config_two_worlds(), pack, population)

    def factory(header):
        if header.scenario.variant.variant_id == "v2premium":
            return FakeWorld(header, fail_at=2)
        return FakeWorld(header)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=_agent)
    by_id = {o.world_id: o for o in result.outcomes}
    assert len(by_id) == 2
    statuses = sorted(o.status.value for o in result.outcomes)
    assert statuses == ["completed", "partial"]


def test_failed_outcome_records_status_and_last_tick():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config_two_worlds(), pack, population)

    def factory(header):
        if header.scenario.variant.variant_id == "v2premium":
            return FakeWorld(header, fail_at=2)
        return FakeWorld(header)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=_agent)
    failed = [o for o in result.outcomes if o.status.value == "partial"][0]
    assert failed.last_closed_tick == 1


def test_run_status_computed_and_refuses_contradiction():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config_two_worlds(), pack, population)

    def factory(header):
        if header.scenario.variant.variant_id == "v2premium":
            return FakeWorld(header, fail_at=1)
        return FakeWorld(header)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=_agent)
    assert result.status.value == "partial"
    with pytest.raises(ValidationError):
        RunResult.model_validate({**result.model_dump(mode="json"),
                                  "registry": {**result.registry.model_dump(mode="json"), "status": "completed"}})


def test_never_started_recorded_not_omitted():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config_two_worlds(), pack, population)

    def factory(header):
        if header.scenario.variant.variant_id == "v2premium":
            raise WorldFailed("never started")
        return FakeWorld(header)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=_agent)
    by_id = {o.world_id: o for o in result.outcomes}
    assert len(by_id) == 2
    not_started = [o for o in result.outcomes if o.status.value == "not_started"]
    assert len(not_started) == 1
    assert not_started[0].last_closed_tick is None


def test_all_failed_returns_result():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config_two_worlds(), pack, population)

    def factory(header):
        return FakeWorld(header, fail_at=1)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=factory, agent_fn=_agent)
    assert len(result.outcomes) == 2
    assert all(o.status.value == "partial" for o in result.outcomes)
    assert result.status.value == "partial"
