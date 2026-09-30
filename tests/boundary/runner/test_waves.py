"""Survey waves read, never write: state, ordering, thinning and pausing."""

from __future__ import annotations

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, LadderConfig, run
from simcore.runner._resume import rebuild_persona_states
from simcore.schemas import (
    BriefPack,
    CompletedTurn,
    CostRecorded,
    Population,
    Reaction,
    RunConfig,
    Turn,
    TurnJob,
    canonical_hash,
    wave_ticks,
)
from simcore.world import World, WorldConfig
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


def _config(horizon=5, survey_every=1, max_cost=20.0, **overrides):
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[], survey_every=survey_every)
    payload = run_config_payload(scenarios=[scenario], seeds=[4021])
    payload["budget"] = {"max_cost": max_cost, "currency": "USD"}
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


class WaveWorld:
    """A world presenting forum turns to the active and survey turns to everyone, on schedule."""

    def __init__(self, header, survey=True):
        from simcore.schemas import Stimulus

        self._header = header
        self._survey = survey
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})
        self.seen: list[tuple[int, str]] = []
        self._nth = 0

    def _impression(self, pid, tick, channel):
        from simcore.schemas import Impression

        self._nth += 1
        return Impression.model_validate(
            {"impression_id": f"im-{ulid(600 + tick * 1000 + self._nth)}",
             "persona_id": pid, "channel": channel, "tick": tick,
             "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})

    def _presentations(self, tick):
        from simcore.schemas import Presentation, View, WorldDelta  # noqa

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

        self.seen.extend((tick, turn.impression.channel.value) for turn in turns)
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": self._presentations(tick)})


def _completed(job: TurnJob, n: int, amount: float | None = None) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + n + impression.tick * 50)}",
                                        "subject_stimulus_id": subject, "action": "answer",
                                        "verbatim": "I would try it", "belief_change": {"dimensions": {"value": 0.05}}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    costs = [] if amount is None else [CostRecorded.model_validate(
        {"kind": "cost", "role": "tier_b", "model_id": "fake/chat", "served_model_id": "fake/chat",
         "cost_source": "gateway", "route": "primary", "input_tokens": 5, "output_tokens": 5, "cost": amount}
    ).model_dump(mode="json")]
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32,
                                         "belief_change": {"dimensions": {"value": 0.05}}, "costs": costs})


def _run_waves(survey=True, survey_every=1, horizon=5, max_cost=20.0, amount=None, ladder=None):
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=horizon, survey_every=survey_every, max_cost=max_cost), pack, population)
    carried: dict = {}
    worlds: list[WaveWorld] = []

    def agent_fn(jobs):
        for job in jobs:
            carried[(job.presentation.impression.tick, job.persona.persona_id)] = job.state.model_copy(deep=True)
        return tuple(_completed(j, i, amount) for i, j in enumerate(jobs))

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: worlds.append(WaveWorld(header, survey=survey)) or worlds[-1],
                 agent_fn=agent_fn, ladder=ladder or LadderConfig())
    return result, trace, worlds, carried, population


def test_a_survey_turn_changes_nothing_rebuild_agrees():
    """The persona's state after a tick with a wave equals its state after the same tick
    without one, field by field — and the record rebuilds to the carried state."""
    _, trace, _, carried, _ = _run_waves(survey=True)
    _, _, _, plain, _ = _run_waves(survey=False)
    assert set(carried) == set(plain)
    for key in carried:
        assert carried[key] == plain[key], f"a wave moved the state carried into {key}"
    world_id = next(iter({e.world_id for e in trace.all_events()}))
    max_tick = max(tick for tick, _ in carried)
    trimmed = tuple(e for e in trace.events_for(world_id) if e.tick < max_tick)
    rebuilt = rebuild_persona_states(_population(), trimmed)
    for pid, state in rebuilt.items():
        assert state == carried[(max_tick, pid)]


def test_the_world_never_ingests_a_survey_turn():
    _, _, worlds, _, _ = _run_waves(survey=True)
    assert worlds[0].seen, "the world was never stepped"
    assert {channel for _, channel in worlds[0].seen} == {"forum"}


def test_a_wave_comes_after_its_channels_turns_by_sequence():
    _, trace, _, _, _ = _run_waves(survey=True, horizon=3)
    seq: dict[tuple[int, str, str], int] = {}
    for event in trace.all_events():
        if event.payload.kind == "turn":
            turn = event.payload.turn
            seq[(event.tick, turn.impression.persona_id, turn.impression.channel.value)] = event.seq
    assert seq
    for (tick, pid, channel), number in seq.items():
        if channel == "survey_room":
            assert seq[(tick, pid, "forum")] < number


def test_thinning_thins_channels_and_never_waves():
    """At the thin rung activation falls but every wave stays whole: all four personas answer."""
    from tests.study_builders import population_payload

    thin = LadderConfig(warn_at=0.0, freeze_at=0.0, subsample_at=0.0, pause_at=10.0, subsample_rate=0.25)
    pack = _pack()
    population = Population.model_validate(population_payload())
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(horizon=5, survey_every=2), pack, population)

    def agent_fn(jobs):
        return tuple(_completed(j, i) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: World(header, population=population, config=WorldConfig(platform="social_feed")),
        agent_fn=agent_fn, ladder=thin)
    per_tick: dict[int, dict[str, int]] = {}
    for event in trace.all_events():
        if event.payload.kind == "turn":
            bucket = per_tick.setdefault(event.tick, {})
            channel = event.payload.turn.impression.channel.value
            bucket[channel] = bucket.get(channel, 0) + 1
    assert per_tick
    assert any(bucket.get("social_feed", 4) < 4 for bucket in per_tick.values()), "activation never fell"
    for tick, bucket in per_tick.items():
        if tick in wave_ticks(2, 5):
            assert bucket.get("survey_room") == 4, f"tick {tick} thinned its wave: {bucket}"


def test_a_wave_the_budget_cannot_cover_pauses_before_it_wholly():
    """A budget short of one wave pauses before the tick: wave_unaffordable is recorded and no
    partial wave — no turn at all — exists in the trace past the last closed tick."""
    result, trace, _, _, _ = _run_waves(survey=True, survey_every=1, horizon=5, max_cost=5.0, amount=10.0)
    assert result.outcomes[0].status.value == "partial"
    assert "wave_unaffordable" in result.outcomes[0].rungs
    kinds = [(e.tick, e.payload.kind) for e in trace.all_events()]
    degraded = [e for e in trace.all_events() if e.payload.kind == "degraded"]
    assert degraded and degraded[-1].payload.rung.value == "wave_unaffordable"
    paused_at = degraded[-1].tick
    assert [kind for tick, kind in kinds if tick == paused_at] == ["degraded", "lifecycle"]
    assert not [kind for tick, kind in kinds if tick > paused_at]
