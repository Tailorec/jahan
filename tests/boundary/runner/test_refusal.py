"""Phase 3 boundary tests: refusing the wrong resume."""

from __future__ import annotations

import copy

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, ResumeRefused, run
from simcore.schemas import BriefPack, CompletedTurn, Population, Reaction, RunConfig, Turn, TurnJob, canonical_hash
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
        from simcore.schemas import Impression, Presentation, Stimulus, View

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


def _agent(jobs):
    return tuple(_completed(j, i) for i, j in enumerate(jobs))


def _started_run():
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(), pack, population)

    def failing(jobs):
        if jobs and jobs[0].presentation.impression.tick == 1:
            raise RuntimeError("interrupt")
        return _agent(jobs)

    try:
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=failing)
    except RuntimeError:
        pass
    return config, pack, population, trace, registry


@pytest.mark.parametrize("name", ["brief", "ontology", "population", "graph", "scenario", "pins", "engine_version"])
def test_each_moved_input_refuses_resume_naming_it(name):
    config, pack, population, trace, registry = _started_run()
    new_config, new_pack, new_population, engine = config, pack, population, "1.0.0-runner.1"
    if name == "brief":
        payload = pack_payload(claims=[{"id": "C1", "text": "changed claim", "source": "user_asserted"}])
        new_pack = BriefPack.model_validate(payload)
    elif name == "ontology":
        payload = pack.model_dump(mode="json")
        order = list(payload["ontology"]["relevance_order"])
        order[-1], order[-2] = order[-2], order[-1]
        payload["ontology"]["relevance_order"] = order
        new_pack = BriefPack.model_validate(payload)
    elif name == "population":
        from tests.study_builders import population_payload, with_derived_hashes

        raw = population_payload()
        raw["manifest"]["population_seed"] = 9999
        raw["manifest"]["population_hash"] = "00" * 32
        raw.pop("manifest", None) and None
        # Rebuild via helper: force recompute by resetting the sentinel hash.
        import copy

        base = population_payload()
        base["manifest"]["population_seed"] = 9999
        base["manifest"]["population_hash"] = "00" * 32
        base = with_derived_hashes(base)
        new_population = Population.model_validate(base)
    elif name == "graph":
        from tests.study_builders import population_payload, with_derived_hashes

        base = population_payload()
        base["graph"]["edges"] = base["graph"]["edges"][:2]
        base["manifest"]["population_hash"] = "00" * 32
        base["manifest"].pop("graph_hash", None)
        base.pop("graph_hash", None)
        base = with_derived_hashes(base)
        new_population = Population.model_validate(base)
    elif name == "scenario":
        scenario = scenario_payload(horizon_ticks=4, interventions=[], price={"amount": 9.99, "currency": "USD"})
        new_config = RunConfig.model_validate({**config.model_dump(mode="json"), "scenarios": [scenario]})
    elif name == "pins":
        payload = config.model_dump(mode="json")
        payload["pins"]["tier_a"] = "openrouter/camel-ai/persona-8b-v2"
        new_config = RunConfig.model_validate(payload)
    elif name == "engine_version":
        engine = "9.9.9-other-engine"
    with pytest.raises(ResumeRefused, match=name) as exc:
        run(new_config, pack=new_pack, population=new_population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=_agent, engine_version=engine)
    assert exc.value.name == name
    assert exc.value.recorded and exc.value.presented


def test_forced_resume_proceeds_recorded_and_marked():
    config, pack, population, trace, registry = _started_run()
    before = len(trace.all_events())
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=_agent,
                 engine_version="9.9.9-other-engine", force=True)
    assert result.status.value == "completed"
    assert registry.is_forced(config.run_id)
    assert registry.entry(config.run_id).engine_version == "9.9.9-other-engine"
    assert len(trace.all_events()) > before


def test_identical_inputs_proceed_silently():
    config, pack, population, trace, registry = _started_run()
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: FakeWorld(header), agent_fn=_agent)
    assert result.status.value == "completed"
    assert not registry.is_forced(config.run_id)


def test_engine_version_read_from_registry_not_process():
    config, pack, population, trace, registry = _started_run()
    stored = registry.entry(config.run_id)
    assert stored.engine_version == "1.0.0-runner.1"
    with pytest.raises(ResumeRefused, match="engine_version"):
        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: FakeWorld(header), agent_fn=_agent, engine_version="other")
