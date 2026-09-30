"""Survey waves: every persona answers the concept on wave ticks, apart from channels.

A wave only reads: answering changes nothing about the persona, sparks no word of mouth,
and writes no engagement. Channel presentations come first in a tick's delta, then word
of mouth, then the wave last — so a wave tick's answers reflect everything up to and
including their own tick.
"""

from simcore.schemas import Channel
from simcore.world import WorldConfig
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import answer_turn, felt_turn, make_population, make_world, on_channel

EVERY_OTHER = scenario_payload(survey_every=2, horizon_ticks=5)


def test_a_wave_surveys_every_persona_on_wave_ticks_and_none_otherwise():
    world = make_world(population=make_population(), scenario=EVERY_OTHER)
    world.reset()
    for tick in range(1, 5):
        delta = world.step(tick, [])
        survey = on_channel(delta.presentations, Channel.SURVEY_ROOM)
        if tick in (2, 4):
            assert [p.impression.persona_id for p in survey] == sorted(world._personas)
            for presentation in survey:
                assert len(presentation.impression.exposures) == 1
                assert presentation.impression.exposures[0].stimulus_id == world.concept_id()
        else:
            assert survey == []


def test_the_wave_comes_after_the_channels_turns_in_its_tick():
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}), population=make_population())
    world.reset()
    delta = world.step(1, [])
    positions: dict[tuple[str, Channel], int] = {}
    for position, presentation in enumerate(delta.presentations):
        positions.setdefault(
            (presentation.impression.persona_id, presentation.impression.channel), position
        )
    for persona in PERSONA_IDS:
        assert positions[(persona, Channel.SOCIAL_FEED)] < positions[(persona, Channel.SURVEY_ROOM)]


def test_a_survey_answer_sparks_no_word_of_mouth_and_writes_no_engagement():
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}), population=make_population())
    world.reset()
    first = world.step(1, [])
    survey_turns = [
        felt_turn(presentation, 100 + n)
        for n, presentation in enumerate(on_channel(first.presentations, Channel.SURVEY_ROOM))
    ]
    assert survey_turns, "the wave has nothing to answer"
    second = world.step(2, survey_turns)
    assert not [p for p in second.presentations if p.impression.channel is Channel.WOM]
    assert "engagement:" not in world.state_dump()


def test_a_wave_only_reads_even_where_a_channel_would_write():
    world = make_world(population=make_population())
    world.reset()
    first = world.step(1, [])
    before = world.state_dump()
    world.step(2, [answer_turn(p, n) for n, p in enumerate(first.presentations)])
    assert world.state_dump() == before
    assert world.rejected_actions() == ()
