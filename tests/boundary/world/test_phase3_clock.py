"""Phase 3: the clock.

A scenario declares its `tick_unit` and `horizon_ticks`, and the unit travels
with the world so a report can label an axis truthfully. Activation is a
seeded Bernoulli draw per persona per tick from involvement × a rhythm curve
keyed to the tick unit. Interventions are expressed in ticks and compose
rather than overwrite.
"""

from simcore.schemas import Channel
from simcore.world import (
    DAY_RHYTHM,
    HOUR_RHYTHM,
    WorldConfig,
    activation_probability,
    rhythm_at,
    straggler_tick,
)
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import drive, make_world, on_channel

# Activation gates channel turns: these worlds tick the feed, so the wave (which surveys
# everyone, never gated) is filtered out of what counts as activation.
CLOCK = WorldConfig(platform="social_feed")


def presented_ids(world, tick, previous=()):
    return [
        p.impression.persona_id
        for p in on_channel(world.step(tick, previous).presentations, Channel.SOCIAL_FEED)
    ]


def test_tick_unit_and_horizon_travel_with_the_world():
    world = make_world()
    assert world.tick_unit == "day"
    assert world.horizon_ticks == 30
    hourly = make_world(scenario=scenario_payload(tick_unit="hour"))
    assert hourly.tick_unit == "hour"


def test_activation_comes_from_involvement_times_rhythm_with_defaults_overridable():
    excluded = make_world(config=WorldConfig(platform="social_feed", involvement=(("p-000001", 0.0),)))
    excluded.reset()
    assert presented_ids(excluded, 1) == sorted(p for p in PERSONA_IDS if p != "p-000001")
    assert activation_probability(0.5, "day", 1) == 0.5 * DAY_RHYTHM[1]
    assert activation_probability(2.0, "day", 1) == 1.0
    boosted = make_world(config=WorldConfig(rhythm=(("day", 0.25),), involvement_default=1.0))
    assert rhythm_at("day", 3, {"day": 0.25}) == 0.25


def test_hour_and_day_scenarios_use_different_rhythm_curves():
    assert HOUR_RHYTHM != DAY_RHYTHM
    assert len(HOUR_RHYTHM) == 24 and len(DAY_RHYTHM) == 7
    assert any(rhythm_at("hour", tick) != rhythm_at("day", tick) for tick in range(24))
    hourly = make_world(config=WorldConfig(platform="social_feed", involvement_default=0.5), scenario=scenario_payload(tick_unit="hour"))
    daily = make_world(config=WorldConfig(platform="social_feed", involvement_default=0.5), scenario=scenario_payload(tick_unit="day"))
    hourly.reset()
    daily.reset()
    hourly_sets = [presented_ids(hourly, tick) for tick in range(1, 13)]
    daily_sets = [presented_ids(daily, tick) for tick in range(1, 13)]
    assert hourly_sets != daily_sets


def test_a_rerun_under_the_same_seed_activates_the_same_personas():
    first = make_world(config=WorldConfig(platform="social_feed", involvement_default=0.5))
    second = make_world(config=WorldConfig(platform="social_feed", involvement_default=0.5))
    first.reset()
    second.reset()
    for tick in range(1, 11):
        assert presented_ids(first, tick) == presented_ids(second, tick)
    partial = make_world(config=WorldConfig(platform="social_feed", involvement_default=0.5))
    _, turns = drive(partial, range(1, 13))
    total_presented = sum(
        1 for tick in turns for turn in turns[tick] if turn.impression.channel is not Channel.SURVEY_ROOM
    )
    assert 0 < total_presented < 12 * len(PERSONA_IDS)


def test_two_interventions_on_one_tick_apply_additively():
    scenario = scenario_payload(
        interventions=[{"tick": 3, "kind": "launch"}, {"tick": 3, "kind": "promotion"}]
    )
    world = make_world(scenario=scenario)
    world.reset()
    world.step(1, [])
    world.step(2, [])
    delta = world.step(3, [])
    assert tuple(i.value for i in delta.interventions) == ("launch", "promotion")


def test_interventions_are_expressed_in_ticks_against_the_declared_horizon():
    scenario = scenario_payload(
        horizon_ticks=6,
        interventions=[{"tick": 3, "kind": "launch"}, {"tick": 5, "kind": "teaser"}],
    )
    world = make_world(scenario=scenario)
    world.reset()
    seen = {}
    for tick in range(1, 6):
        seen[tick] = [i.value for i in world.step(tick, []).interventions]
    assert seen == {1: [], 2: [], 3: ["launch"], 4: [], 5: ["teaser"]}


def test_the_straggler_case_is_the_lowest_tick_among_live_worlds():
    assert straggler_tick([4, 2, 3]) == 2
    assert straggler_tick([7]) == 7
