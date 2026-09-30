"""Phase 10: word of mouth.

The graph channel. After a reaction, `wants_to_talk` gates on sentiment
strength and tie strength, and a delivery creates a next-tick exposure with
`reason=wom` whose view records the tie strength between the two personas. A
cap per persona per tick keeps one strongly-felt reaction from crossing a
dense community in a single tick.
"""

from simcore.schemas import Channel
from simcore.world import WorldConfig, select_targets, sentiment_strength, wants_to_talk
from tests.study_builders import PERSONA_IDS

from .helpers import answer_turn, felt_turn, make_population, make_world, on_channel

FEED = WorldConfig(channels={"social_feed", "wom"}, exposure_budget=6)


def feed_only(delta):
    """This suite's subject is feed and word of mouth: the wave rides along but is never what is asserted."""
    return [p for p in delta.presentations if p.impression.channel is not Channel.SURVEY_ROOM]


def drive_talk(config=FEED):
    """A feed world where p-000001 feels strongly at tick 1; returns the world,
    the tick-1 subject, and the tick-1 and tick-2 deltas."""
    population = make_population()
    world = make_world(config=config, population=population)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in feed_only(first)}
    subject = by_persona["p-000001"].impression.exposures[0].stimulus_id
    turns = [felt_turn(by_persona["p-000001"], 1)]
    turns += [
        answer_turn(by_persona[pid], 2 + n, action="ignore")
        for n, pid in enumerate(sorted(by_persona))
        if pid != "p-000001"
    ]
    second = world.step(2, turns)
    return world, subject, first, second


def wom_for(delta, persona):
    """That persona's wom-channel presentations in a delta."""
    return [p for p in delta.presentations if p.impression.persona_id == persona and p.impression.channel is Channel.WOM]


def test_word_of_mouth_delivers_as_a_next_tick_exposure_never_within_tick():
    world, subject, first, second = drive_talk()
    assert not [p for p in first.presentations if p.impression.channel is Channel.WOM]
    told = wom_for(second, "p-000002")
    assert len(told) == 1
    assert [e.stimulus_id for e in told[0].impression.exposures] == [subject]
    assert all(e.reason.value == "wom" for e in told[0].impression.exposures)
    assert wom_for(second, "p-000003") == []
    assert wom_for(second, "p-000004") == []


def test_the_delivered_view_records_the_tie_between_the_two_personas():
    _, subject, _, second = drive_talk()
    (told,) = wom_for(second, "p-000002")
    context = told.view.contexts[subject]
    assert context.tie_strength == 0.8
    assert context.shared_community is True


def test_both_gates_are_configurable_with_documented_defaults():
    from simcore.world import DEFAULT_SENTIMENT_THRESHOLD, DEFAULT_TIE_THRESHOLD

    assert (DEFAULT_SENTIMENT_THRESHOLD, DEFAULT_TIE_THRESHOLD) == (0.6, 0.3)
    _, _, _, gated = drive_talk(config=WorldConfig(channels={"social_feed", "wom"}, exposure_budget=6, wom_sentiment_threshold=0.95))
    assert gated.presentations and not [p for p in gated.presentations if p.impression.channel is Channel.WOM]
    _, _, _, tied = drive_talk(config=WorldConfig(channels={"social_feed", "wom"}, exposure_budget=6, wom_tie_threshold=0.9))
    assert tied.presentations and not [p for p in tied.presentations if p.impression.channel is Channel.WOM]


def test_the_per_tick_cap_holds_and_targets_come_from_a_derived_seed():
    ties = {f"p-{n:06d}": 0.9 for n in range(10, 20)}
    first = select_targets("p-000001", ties, 0.9, world_seed=4021, tick=2)
    assert len(first) == 2
    assert select_targets("p-000001", ties, 0.9, world_seed=4021, tick=2) == first
    assert select_targets("p-000001", ties, 0.2, world_seed=4021, tick=2) == []
    assert select_targets("p-000001", {"p-000010": 0.1}, 0.9, world_seed=4021, tick=2) == []
    population = make_population()
    world = make_world(config=FEED, population=population)
    world.reset()
    first_delta = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in feed_only(first_delta)}
    second = world.step(2, [felt_turn(by_persona[pid], n) for n, pid in enumerate(sorted(by_persona))])
    delivered = sum(
        len(p.impression.exposures)
        for p in second.presentations
        if p.impression.channel is Channel.WOM
    )
    assert delivered <= 2 * len(PERSONA_IDS)


def test_a_persona_with_no_ties_produces_no_deliveries_and_no_error():
    world = make_world(config=FEED)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in feed_only(first)}
    second = world.step(2, [felt_turn(by_persona[pid], n) for n, pid in enumerate(sorted(by_persona))])
    assert second.presentations
    assert not [p for p in second.presentations if p.impression.channel is Channel.WOM]


def test_the_survey_room_neither_delivers_nor_sparks_word_of_mouth():
    population = make_population()
    world = make_world(population=population)
    world.reset()
    first = world.step(1, [])
    assert sentiment_strength(felt_turn(first.presentations[0], 1).reaction) >= 0.6
    assert wants_to_talk(felt_turn(first.presentations[0], 1).reaction, 0.8) is True
    second = world.step(2, [felt_turn(first.presentations[0], 1)])
    assert not [p for p in second.presentations if p.impression.channel is Channel.WOM]


def test_word_of_mouth_replays_exactly_like_everything_else():
    from simcore.schemas import canonical_json
    from simcore.world import check_replay

    from .helpers import make_header

    population = make_population()
    world = make_world(config=FEED, population=population)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in feed_only(first)}
    strong = [felt_turn(by_persona[pid], n) for n, pid in enumerate(sorted(by_persona))]
    second = world.step(2, strong)
    assert any(p.impression.channel is Channel.WOM for p in second.presentations)
    fresh = make_world(config=FEED, population=make_population())
    deltas = [fresh.reset(), fresh.step(1, [])]
    deltas.append(fresh.step(2, strong))
    assert [canonical_json(d) for d in deltas[1:]] == [canonical_json(first), canonical_json(second)]
    # The trailing key bounds the replay; its turns would feed the step after the last recorded delta.
    check_replay(deltas, make_header(), {1: strong, 2: []}, population=make_population(), config=FEED)


def test_two_tellers_about_the_same_stimulus_deliver_one_exposure():
    """Two personas telling the same peer about the same post is one thing heard, not two.

    In a dense community this is the ordinary case, and it built an impression holding the
    same stimulus twice, which the contract refuses — the world raised mid-run.
    """
    world, subject, first, _ = drive_talk()
    told_twice = {"p-000003": [(subject, "p-000001", 0.9), (subject, "p-000002", 0.4)]}
    presentations, dropped = world._wom_presentations(2, told_twice)
    assert presentations, "nobody was told anything, so there is nothing to deduplicate"
    for presentation in presentations:
        heard = [exposure.stimulus_id for exposure in presentation.impression.exposures]
        assert len(heard) == len(set(heard)), f"{presentation.impression.persona_id} heard the same post twice"
    context = presentations[0].view.contexts[subject]
    assert context.tie_strength == 0.9, "the view records the closest teller, not the last one"
    assert not dropped, "one thing heard twice is not a budget drop"
