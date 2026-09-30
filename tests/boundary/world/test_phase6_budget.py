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

from .helpers import act_turn, answer_turn, drive, make_population, make_world, on_channel

FEED = WorldConfig(channels={"social_feed", "wom"})


def feed_only(delta):
    """This suite's subject is the feed: the wave rides along but is never what is asserted."""
    return on_channel(delta.presentations, Channel.SOCIAL_FEED)


def busy_feed(budget_scenario=None, likes=False):
    """A feed world where every persona posts at tick 1: 8 candidates by tick 3."""
    population = make_population()
    scenario = budget_scenario or scenario_payload()
    world = make_world(config=FEED, population=population, scenario=scenario)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in feed_only(first)}
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
    assert [p.impression for p in feed_only(plain_third)] == [
        p.impression for p in feed_only(rerun_third)
    ]
    # Engagement cannot move the control arm: identical posts, likes hammering different targets.
    first_a = make_world(config=FEED, population=make_population())
    first_b = make_world(config=FEED, population=make_population())
    first_a.reset()
    first_b.reset()
    shown_a = first_a.step(1, [])
    shown_b = first_b.step(1, [])
    assert [p.impression for p in feed_only(shown_a)] == [p.impression for p in feed_only(shown_b)]
    by_a = {p.impression.persona_id: p for p in feed_only(shown_a)}
    by_b = {p.impression.persona_id: p for p in feed_only(shown_b)}
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
    assert feed_only(third_a)[0].view.contexts[target_a].likes == 2
    assert feed_only(third_b)[0].view.contexts[target_a].likes == 0
    assert [p.impression for p in feed_only(third_a)] == [p.impression for p in feed_only(third_b)]


def test_exposure_concentration_under_random_is_measurable_on_a_fixture():
    _, first, second, third = busy_feed()
    baseline = exposure_concentration([first, second, third])
    assert 0.0 < baseline <= 1.0
    again_world, again_first, again_second, again_third = busy_feed()
    assert exposure_concentration([again_first, again_second, again_third]) == baseline


def test_exposures_keep_their_attention_reason_and_seen_flag():
    _, first, _, _ = busy_feed()
    for presentation in feed_only(first):
        shown = presentation.impression.exposures
        for rank, exposure in enumerate(shown):
            # The first slot has the persona's full notice; the last has half of it.
            expected = 1.0 if len(shown) == 1 else 1.0 - 0.5 * rank / (len(shown) - 1)
            assert exposure.attention == round(expected, 4)
            assert exposure.reason.value == "random"
            assert exposure.seen is True
    # What the agent is given round-trips untouched into its turn.
    for n, presentation in enumerate(feed_only(first)):
        turn = answer_turn(presentation, n)
        assert turn.impression.exposures == presentation.impression.exposures


def test_a_drop_is_a_near_miss_not_the_whole_corpus():
    """Recording every unshown stimulus as a drop makes the trace grow with the corpus.

    A drop means a stimulus that would have reached this persona but for the budget, so the
    candidates are a bounded window around it. Without the window, a world with 20 stimuli
    and 4 personas wrote 52 drops in one tick, and a study with a thousand stimuli and ten
    thousand personas would write millions per tick, none of them read by anything.
    """
    population = make_population()
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}, candidate_window=6), population=population)
    world.reset()
    turns = []
    counts = []
    for tick in range(1, 6):
        delta = world.step(tick, turns)
        counts.append(len(delta.dropped))
        turns = [
            act_turn(presentation, index, "post", f"post {index} at tick {tick}")
            for index, presentation in enumerate(delta.presentations)
        ]
    published = len(world._store.stimuli_published_before(6))
    assert published > 12, "the corpus grew, which is the case under test"
    budget, window = world._budget(), 6
    awake = len(PERSONA_IDS)
    assert max(counts) <= (window - budget) * awake, f"{max(counts)} drops for {published} stimuli"


def test_the_candidate_window_defaults_to_a_multiple_of_the_budget_and_is_recorded():
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}), population=make_population())
    assert world._candidate_window() >= world._budget()
    narrow = make_world(config=WorldConfig(channels={"social_feed", "wom"}, candidate_window=3), population=make_population())
    assert narrow._candidate_window() == 3


def test_a_stimulus_outside_the_window_is_not_shown_and_not_recorded_as_dropped():
    """The window bounds what is recorded, never what the budget shows."""
    population = make_population()
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}, candidate_window=4), population=population)
    world.reset()
    first = world.step(1, [])
    shown = {
        presentation.impression.persona_id: {exposure.stimulus_id for exposure in presentation.impression.exposures}
        for presentation in feed_only(first)
    }
    dropped: dict[str, set[str]] = {}
    for entry in first.dropped:
        dropped.setdefault(entry.persona_id, set()).add(entry.drop.stimulus_id)
    for persona_id, seen in shown.items():
        assert seen & dropped.get(persona_id, set()) == set(), "a stimulus was shown to a persona and dropped for it too"
        assert len(seen) <= world._budget()


def test_attention_falls_down_the_impression_rather_than_being_flat():
    """`CONTEXT.md` defines noticing as drawing any attention at all, and an exposure keeps its
    own attention — but every exposure was built with attention 1.0, so position carried no
    information and nothing shown was ever unnoticed."""
    world, first, second, third = busy_feed()
    ranked = [
        [exposure.attention for exposure in presentation.impression.exposures]
        for presentation in third.presentations
        if len(presentation.impression.exposures) > 1
    ]
    assert ranked, "no persona was shown more than one stimulus, so there is nothing to rank"
    for attentions in ranked:
        assert attentions == sorted(attentions, reverse=True)
        assert len(set(attentions)) > 1, "attention is flat across the impression"
    assert all(exposure.seen for presentation in third.presentations for exposure in presentation.impression.exposures)


def test_a_study_may_declare_the_floor_below_which_a_shown_stimulus_goes_unnoticed():
    """A stimulus can be shown without being noticed; whether a study models that is its call,
    and the default leaves every shown stimulus noticed."""
    population = make_population()
    world = make_world(config=WorldConfig(channels={"social_feed", "wom"}, attention_floor=0.6), population=population)
    world.reset()
    world.step(1, [])
    first = world.step(2, [])
    exposures = [exposure for presentation in first.presentations for exposure in presentation.impression.exposures]
    assert exposures
    assert any(not exposure.seen for exposure in exposures), "the floor never left anything unnoticed"
    assert all(exposure.attention == 0.0 for exposure in exposures if not exposure.seen)
