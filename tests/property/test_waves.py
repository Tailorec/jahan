"""A wave only reads, as a property: channel turns are identical with and without waves."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, run
from simcore.schemas import BriefPack, CompletedTurn, Population, Reaction, RunConfig, Turn, TurnJob, canonical_hash
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


def _pack():
    return BriefPack.model_validate(pack_payload())


def _population():
    return Population.model_validate(population_payload())


class ScheduledWorld:
    """Forum turns every tick; survey turns on the scenario's wave ticks when asked."""

    def __init__(self, header, survey):
        from simcore.schemas import Stimulus

        self._header = header
        self._survey = survey
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})

    def _impression(self, pid, tick, channel):
        from simcore.schemas import Impression

        index = sorted(self._personas).index(pid)
        return Impression.model_validate(
            {"impression_id": f"im-{ulid(700 + tick * 10 + index + (4 if channel == 'survey_room' else 0))}",
             "persona_id": pid, "channel": channel, "tick": tick,
             "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})

    def _presentations(self, tick):
        from simcore.schemas import Presentation, View, WorldDelta, wave_ticks  # noqa

        out = []
        for pid in sorted(self._personas):
            impression = self._impression(pid, tick, "forum")
            view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            out.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        if self._survey and tick in wave_ticks(self._header.scenario.survey_every, self._header.scenario.horizon_ticks):
            for pid in sorted(self._personas):
                impression = self._impression(pid, tick, "survey_room")
                view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
                out.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return out

    def reset(self):
        from simcore.schemas import WorldDelta

        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": self._presentations(0)})

    def step(self, tick, turns):
        from simcore.schemas import WorldDelta

        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": self._presentations(tick)})


def _seeing_agent(jobs):
    """A reaction that quotes the carried beliefs: any leak from a wave into state shows up in words."""
    out = []
    for i, job in enumerate(jobs):
        value = float(job.state.beliefs.dimensions["value"])
        impression = job.presentation.impression
        subject = next(iter(impression.stimulus_ids))
        reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + i)}",
                                            "subject_stimulus_id": subject, "action": "answer",
                                            "verbatim": f"saw {impression.tick} as {value:.2f}",
                                            "belief_change": {"dimensions": {"value": 0.01}}})
        turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                    "view": job.presentation.view.model_dump(mode="json"),
                                    "reaction": reaction.model_dump(mode="json")})
        out.append(CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                                 "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32,
                                                 "belief_change": {"dimensions": {"value": 0.01}}, "costs": []}))
    return tuple(out)


def _channel_turns(seed, survey_every, horizon, survey):
    from simcore.schemas import derive_world_id  # noqa

    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[], survey_every=survey_every)
    config = RunConfig.model_validate({
        **run_config_payload(scenarios=[scenario], seeds=[seed]), "seeds": [seed],
        "brief_hash": canonical_hash(pack.brief), "ontology_hash": canonical_hash(pack.ontology),
        "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash})
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: ScheduledWorld(header, survey), agent_fn=_seeing_agent)
    turns = []
    waves = 0
    for event in trace.all_events():
        if event.payload.kind == "turn" and event.payload.turn.impression.channel != "survey_room":
            turn = event.payload.turn
            turns.append((event.tick, turn.impression.persona_id, turn.reaction.verbatim,
                          turn.impression.impression_id))
        elif event.payload.kind == "turn":
            waves += 1
    return turns, waves


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 999999), survey_every=st.integers(1, 6), horizon=st.integers(2, 6))
def test_channel_turns_are_identical_with_and_without_waves(seed, survey_every, horizon):
    with_waves, wave_count = _channel_turns(seed, survey_every, horizon, True)
    without_waves, _ = _channel_turns(seed, survey_every, horizon, False)
    assert with_waves, "no channel turns to compare"
    assert wave_count, "no survey turns ran, so the comparison is vacuous"
    assert with_waves == without_waves
