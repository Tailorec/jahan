"""Phase 7: `reddit_hot` and the global forum.

The hot score is copied verbatim from upstream — its value is fidelity, not
our improvement of it. The `reddit_global` preset lets any persona reach any
thread, ranked by that score, with create_post, reply and vote.
"""

from simcore.schemas import Channel
from simcore.world import Forum, RecsysMode, WorldConfig, exposure_concentration, hot_score
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import act_turn, answer_turn, make_population, make_world, on_channel, targeted_turn

FORUM = WorldConfig(platform="forum")
WIDE = scenario_payload(exposure_budget=6)


def forum_only(delta):
    """This suite's subject is the forum: the wave rides along but is never what is asserted."""
    return on_channel(delta.presentations, Channel.FORUM)


def test_the_hot_score_is_copied_verbatim():
    epoch = 1134028003
    assert hot_score(1, 0, epoch) == 0.0
    assert hot_score(10, 0, epoch + 45000) == 2.0
    assert hot_score(0, 10, epoch) == -1.0
    assert hot_score(100, 99, epoch) == hot_score(1, 0, epoch)
    assert hot_score(10, 0, epoch + 90000) == round(1.0 + 2.0, 7)


def test_the_global_forum_supports_create_post_reply_and_vote_on_open_threads():
    population = make_population()
    world = make_world(config=FORUM, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = world.step(
        2,
        [
            act_turn(by_persona["p-000001"], 1, "post", "thread opener: which flavour?"),
            answer_turn(by_persona["p-000002"], 2, action="ignore"),
            answer_turn(by_persona["p-000003"], 3, action="ignore"),
            answer_turn(by_persona["p-000004"], 4, action="ignore"),
        ],
    )
    assert [s.kind.value for s in second.published] == ["peer_post"]
    post_id = second.published[0].stimulus_id
    by_second = {p.impression.persona_id: p for p in second.presentations}
    assert post_id not in {s for p in second.presentations for s in p.impression.stimulus_ids}
    third = world.step(3, [answer_turn(p, 10 + n, action="ignore") for n, p in enumerate(second.presentations)])
    by_third = {p.impression.persona_id: p for p in forum_only(third)}
    assert all(post_id in p.impression.stimulus_ids for p in forum_only(third))
    fourth = world.step(
        4,
        [
            answer_turn(by_third["p-000001"], 20, action="ignore"),
            act_turn(by_third["p-000002"], 21, "reply", "vanilla, easily", subject_id=post_id),
            act_turn(by_third["p-000003"], 22, "upvote", subject_id=post_id),
            act_turn(by_third["p-000004"], 23, "downvote", subject_id=post_id),
        ],
    )
    assert [s.kind.value for s in fourth.published] == ["peer_reply"]
    assert fourth.published[0].in_reply_to == post_id
    dump = world.state_dump()
    assert "upvote" in dump and "downvote" in dump
    fifth = world.step(5, [])
    shown_sets = [set(p.impression.stimulus_ids) for p in forum_only(fifth)]
    assert shown_sets[0] == shown_sets[1] == shown_sets[2] == shown_sets[3]
    for presentation in forum_only(fifth):
        assert presentation.impression.channel is Channel.FORUM
        assert all(e.reason.value == "forum" for e in presentation.impression.exposures)


def test_votes_affect_ranking_only_through_the_upstream_score():
    population = make_population()
    world = make_world(config=FORUM, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = world.step(
        2,
        [
            act_turn(by_persona["p-000001"], 1, "post", "first thread"),
            act_turn(by_persona["p-000002"], 2, "post", "second thread"),
            answer_turn(by_persona["p-000003"], 3, action="ignore"),
            answer_turn(by_persona["p-000004"], 4, action="ignore"),
        ],
    )
    assert len(second.published) == 2
    older, newer = second.published[0].stimulus_id, second.published[1].stimulus_id
    world.step(
        3,
        [
            targeted_turn("p-000003", 2, older, 20, "upvote", channel="forum"),
            targeted_turn("p-000004", 2, older, 21, "upvote", channel="forum"),
        ],
    )
    fourth = world.step(4, [])
    for presentation in forum_only(fourth):
        shown = [e.stimulus_id for e in presentation.impression.exposures]
        assert shown.index(older) < shown.index(newer)
    assert hot_score(2, 0, 3600) > hot_score(0, 0, 3600)


def test_ranking_ties_break_from_a_derived_seed_reproducibly():
    population = make_population()
    first = make_world(config=FORUM, population=population, scenario=WIDE)
    second = make_world(config=FORUM, population=population, scenario=WIDE)
    first.reset()
    second.reset()
    assert [p.impression for p in first.step(1, []).presentations] == [
        p.impression for p in second.step(1, []).presentations
    ]


def test_reddit_hot_concentrates_exposure_against_random_on_the_same_fixture():
    hourly = scenario_payload(tick_unit="hour", exposure_budget=1)
    random_world = make_world(
        config=WorldConfig(platform="social_feed", feed_recsys_mode="random", involvement_default=100.0),
        population=make_population(),
        scenario=hourly,
    )
    hot_world = make_world(
        config=WorldConfig(platform="social_feed", feed_recsys_mode="reddit_hot", involvement_default=100.0),
        population=make_population(),
        scenario=dict(hourly),
    )
    for world in (random_world, hot_world):
        world.reset()
        first = world.step(1, [])
        feed_first = on_channel(first.presentations, Channel.SOCIAL_FEED)
        actors = sorted(p.impression.persona_id for p in feed_first)
        by_persona = {p.impression.persona_id: p for p in feed_first}
        poster = next(pid for pid in PERSONA_IDS if pid in by_persona)
        second = world.step(
            2,
            [act_turn(by_persona[poster], 1, "post", "early post, one like")]
            + [answer_turn(by_persona[pid], 2 + n, action="ignore") for n, pid in enumerate(actors) if pid != poster],
        )
        early = next(s for s in second.published if s.kind.value == "peer_post")
        feed_second = on_channel(second.presentations, Channel.SOCIAL_FEED)
        by_second = {p.impression.persona_id: p for p in feed_second}
        actors2 = sorted(by_second)
        late_poster = next(pid for pid in PERSONA_IDS if pid in by_second and pid != poster)
        third = world.step(
            3,
            [act_turn(by_second[late_poster], 10, "post", "late post, four likes")]
            + [answer_turn(by_second[pid], 12 + n, action="ignore") for n, pid in enumerate(actors2) if pid != late_poster]
            + [targeted_turn(poster, 2, early.stimulus_id, 11, "like")],
        )
        late = next(s for s in third.published if s.kind.value == "peer_post")
        world.step(
            4,
            [targeted_turn(pid, 3, late.stimulus_id, 20 + n, "like") for n, pid in enumerate(PERSONA_IDS)],
        )
        world._late_post = late.stimulus_id
    random_fifth = random_world.step(5, [])
    hot_fifth = hot_world.step(5, [])
    hot_feed = hot_fifth.model_copy(update={"presentations": tuple(on_channel(hot_fifth.presentations, Channel.SOCIAL_FEED))})
    random_feed = random_fifth.model_copy(update={"presentations": tuple(on_channel(random_fifth.presentations, Channel.SOCIAL_FEED))})
    assert exposure_concentration([hot_feed]) == 1.0
    assert {e.stimulus_id for p in hot_feed.presentations for e in p.impression.exposures} == {
        hot_world._late_post
    }
    assert exposure_concentration([random_feed]) < exposure_concentration([hot_feed])
    assert isinstance(Forum("reddit_global"), Forum)


def test_the_hot_score_ranks_the_newer_post_first():
    """Reddit's formula scores a post by *when it was published*, so a newer post outranks an
    older one. Feeding it the post's age instead inverts that: the herding arm herded toward
    the oldest thing in the world, and ten upvotes could not outweigh a day of age.
    """
    from simcore.world.recsys import UNIT_SECONDS, hot_order, hot_score

    day = UNIT_SECONDS["day"]
    assert hot_score(0, 0, 5 * day) > hot_score(0, 0, 0), "a later post must score above an earlier one"
    # The ranking reads publication ticks; passing ages here is the defect, so the keyword
    # is named for what the formula needs and the old signature cannot be called this way.
    order = hot_order(["st-old", "st-new"], {}, {}, published_ticks={"st-old": 0, "st-new": 5},
                      world_seed=7, tick=6, unit_seconds=day)
    assert order == ["st-new", "st-old"]
    # and votes still count: published together, the upvoted post leads
    same_age = hot_order(["st-quiet", "st-loud"], {"st-loud": 10}, {}, published_ticks={"st-quiet": 3, "st-loud": 3},
                         world_seed=7, tick=6, unit_seconds=day)
    assert same_age == ["st-loud", "st-quiet"]


def test_a_fresh_upvoted_post_outranks_an_old_silent_one_in_a_world():
    """The same property through the interface, on the global forum."""
    population = make_population()
    world = make_world(config=FORUM, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    # p-000001 opens a thread at tick 1; the study's own stimuli are older by two ticks
    second = world.step(2, [act_turn(by_persona["p-000001"], 1, "post", "brand new thread about flavour")]
                        + [answer_turn(by_persona[pid], 5 + n, action="ignore")
                           for n, pid in enumerate(sorted(by_persona)) if pid != "p-000001"])
    fresh = second.published[0].stimulus_id
    third = world.step(3, [answer_turn(p, 10 + n, action="ignore") for n, p in enumerate(forum_only(second))])
    for presentation in forum_only(third):
        shown = [exposure.stimulus_id for exposure in presentation.impression.exposures]
        assert shown[0] == fresh, f"the oldest stimulus led the ranking instead of the newest: {shown[0]}"


def test_a_forum_study_orders_threads_by_hot_score_matching_upstream_on_the_same_numbers():
    """The forum ranks like Reddit: the world's order equals the ported `rec_sys_reddit`
    formula run on the same votes and publication ticks — a newer thread with equal votes
    outranks an older one, and a heavily upvoted older one outranks a new one."""
    from simcore.world import recsys as _recsys

    hourly = scenario_payload(tick_unit="hour", exposure_budget=6)
    population = make_population()
    world = make_world(
        config=WorldConfig(platform="forum", involvement_default=100.0),
        population=population,
        scenario=hourly,
    )
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = world.step(2, [act_turn(by_persona["p-000001"], 1, "post", "older thread, loved")])
    older = next(s.stimulus_id for s in second.published if s.kind.value == "peer_post")
    third = world.step(
        3,
        [act_turn(by_persona["p-000003"], 10, "post", "newer thread, silent")]
        + [targeted_turn(pid, 2, older, 11 + n, "upvote", channel="forum") for n, pid in enumerate(PERSONA_IDS)],
    )
    newer = next(s.stimulus_id for s in third.published if s.kind.value == "peer_post")
    fourth = world.step(4, [])
    counts = world._store.counts_visible_at(4)
    rows = world._store.stimuli_published_before(4)
    ups = {row["stimulus_id"]: counts.get(row["stimulus_id"], {}).get("upvotes", 0) for row in rows}
    downs = {row["stimulus_id"]: counts.get(row["stimulus_id"], {}).get("downvotes", 0) for row in rows}
    published = {row["stimulus_id"]: row["tick"] for row in rows}
    ids = [row["stimulus_id"] for row in rows]
    expected = _recsys.hot_order(
        ids, ups, downs, published, world.world_seed, 4, _recsys.UNIT_SECONDS["hour"]
    )
    for presentation in forum_only(fourth):
        shown = [exposure.stimulus_id for exposure in presentation.impression.exposures]
        assert shown == expected[: len(shown)], f"the forum did not rank hot: {shown} vs {expected}"
    assert expected.index(older) < expected.index(newer), "four upvotes should outweigh one hour"


def test_random_stays_the_forum_control_arm():
    """`random` ranks the forum without reference to votes: the same fixture under hot herds,
    under random it does not — and the trace says which mode ranked each exposure."""
    from simcore.world import WorldConfig as _Config

    control = make_world(
        config=_Config(platform="forum", forum_recsys_mode="random"),
        population=make_population(),
        scenario=WIDE,
    )
    control.reset()
    first = control.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = control.step(2, [act_turn(by_persona["p-000001"], 1, "post", "loved thread")])
    loved = next(s.stimulus_id for s in second.published if s.kind.value == "peer_post")
    control.step(
        3, [targeted_turn(pid, 2, loved, 11 + n, "upvote", channel="forum") for n, pid in enumerate(PERSONA_IDS)]
    )
    fourth = control.step(4, [])
    reasons = {e.reason.value for p in forum_only(fourth) for e in p.impression.exposures}
    assert reasons == {"random"}



def test_feed_and_forum_modes_are_recorded_separately_in_exposure_reasons():
    """In a world with both platforms, feed exposures carry the feed mode's reason and forum
    exposures the forum's — the two rankings never collapse into one field."""
    world = make_world(
        config=WorldConfig(channels=frozenset({"social_feed", "forum"})),
        population=make_population(),
    )
    world.reset()
    delta = world.step(1, [])
    feed_reasons = {e.reason.value for p in on_channel(delta.presentations, Channel.SOCIAL_FEED) for e in p.impression.exposures}
    forum_reasons = {e.reason.value for p in forum_only(delta) for e in p.impression.exposures}
    assert feed_reasons == {"random"} and forum_reasons == {"forum"}
