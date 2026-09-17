"""Phase 6: exposure budget and the control arm.

A budget caps stimuli per persona per tick; everything dropped is recorded
with the persona it was dropped for and a reason. The `random` recsys mode is
the control arm: it selects without reference to engagement, deterministically
under a seed, and its exposure concentration is the baseline later modes are
compared against.
"""

from simcore.schemas import Channel
from simcore.world import WorldConfig, exposure_concentration
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import act_turn, answer_turn, drive, make_population, make_world

FEED = WorldConfig(platform="social_feed")


def busy_feed(budget_scenario=None, likes=False):
    """A feed world where every persona posts at tick 1: 8 candidates by tick 3."""
    population = make_population()
    scenario = budget_scenario or scenario_payload()
    world = make_world(config=FEED, population=population, scenario=scenario)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in first.presentations}
    turns = []
    for n, pid in enumerate(sorted(by_persona)):
        if likes:
            turns.append(act_turn(by_persona[pid], n, "like"))
        else:
            turns.append(act_turn(by_persona[pid], n, "post", f"post from {pid} after training"))
    second = world.step(2, turns)
    third = world.step(3, [])
    return world, first, second, third


def test_the_exposure_budget_is_never_exceeded():
    world, first, second, third = busy_feed()
    assert world._budget() == 3
    for delta in (first, second, third):
        for presentation in delta.presentations:
            assert len(presentation.impression.exposures) <= 3


def test_every_drop_records_the_persona_it_was_dropped_for_and_its_reason():
    _, _, _, third = busy_feed()
    assert third.dropped, "eight candidates at a budget of three must drop some"
    for dropped in third.dropped:
        assert dropped.persona_id in PERSONA_IDS
        assert dropped.drop.reason.value == "budget_exhausted"
        assert dropped.drop.channel is Channel.SOCIAL_FEED
    dropped_for = {d.persona_id for d in third.dropped}
    assert dropped_for == set(PERSONA_IDS)


def test_the_budget_default_is_3_and_is_configurable_per_scenario():
    from simcore.schemas import Scenario

    assert Scenario.model_validate(scenario_payload()).exposure_budget == 3
    _, _, _, third = busy_feed(budget_scenario=scenario_payload(exposure_budget=2))
    for presentation in third.presentations:
        assert len(presentation.impression.exposures) <= 2


def test_random_selects_without_reference_to_engagement_deterministically():
    _, _, _, plain_third = busy_feed()
    _, _, _, rerun_third = busy_feed()
    # The same seed deals the same exposures twice.
    assert [p.impression for p in plain_third.presentations] == [
        p.impression for p in rerun_third.presentations
    ]
    # Engagement cannot move the control arm: identical posts, likes hammering different targets.
    first_a = make_world(config=FEED, population=make_population())
    first_b = make_world(config=FEED, population=make_population())
    first_a.reset()
    first_b.reset()
    shown_a = first_a.step(1, [])
    shown_b = first_b.step(1, [])
    assert [p.impression for p in shown_a.presentations] == [p.impression for p in shown_b.presentations]
    by_a = {p.impression.persona_id: p for p in shown_a.presentations}
    by_b = {p.impression.persona_id: p for p in shown_b.presentations}
    target_a = by_a["p-000002"].impression.exposures[0].stimulus_id
    target_b = by_a["p-000003"].impression.exposures[1].stimulus_id
    assert target_a != target_b
    first_a.step(
        2,
        [
            act_turn(by_a["p-000001"], 1, "post", "the same post in both worlds"),
            act_turn(by_a["p-000002"], 2, "like", subject_id=target_a),
            act_turn(by_a["p-000003"], 3, "like", subject_id=target_a),
            answer_turn(by_a["p-000004"], 4, action="ignore"),
        ],
    )
    first_b.step(
        2,
        [
            act_turn(by_b["p-000001"], 1, "post", "the same post in both worlds"),
            act_turn(by_b["p-000002"], 2, "like", subject_id=target_b),
            act_turn(by_b["p-000003"], 3, "like", subject_id=target_b),
            answer_turn(by_b["p-000004"], 4, action="ignore"),
        ],
    )
    third_a = first_a.step(3, [])
    third_b = first_b.step(3, [])
    assert third_a.presentations[0].view.contexts[target_a].likes == 2
    assert third_b.presentations[0].view.contexts[target_a].likes == 0
    assert [p.impression for p in third_a.presentations] == [p.impression for p in third_b.presentations]


def test_exposure_concentration_under_random_is_measurable_on_a_fixture():
    _, first, second, third = busy_feed()
    baseline = exposure_concentration([first, second, third])
    assert 0.0 < baseline <= 1.0
    again_world, again_first, again_second, again_third = busy_feed()
    assert exposure_concentration([again_first, again_second, again_third]) == baseline


def test_exposures_keep_their_attention_reason_and_seen_flag():
    _, first, _, _ = busy_feed()
    for presentation in first.presentations:
        for exposure in presentation.impression.exposures:
            assert exposure.attention == 1.0
            assert exposure.reason.value == "random"
            assert exposure.seen is True
    # What the agent is given round-trips untouched into its turn.
    for n, presentation in enumerate(first.presentations):
        turn = answer_turn(presentation, n)
        assert turn.impression.exposures == presentation.impression.exposures
