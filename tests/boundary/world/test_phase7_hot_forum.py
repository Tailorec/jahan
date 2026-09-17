"""Phase 7: `reddit_hot` and the global forum.

The hot score is copied verbatim from upstream — its value is fidelity, not
our improvement of it. The `reddit_global` preset lets any persona reach any
thread, ranked by that score, with create_post, reply and vote.
"""

from simcore.schemas import Channel
from simcore.world import Forum, RecsysMode, WorldConfig, exposure_concentration, hot_score
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import act_turn, answer_turn, make_population, make_world, targeted_turn

FORUM = WorldConfig(platform="forum")
WIDE = scenario_payload(exposure_budget=6)


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
    by_persona = {p.impression.persona_id: p for p in first.presentations}
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
    by_third = {p.impression.persona_id: p for p in third.presentations}
    assert all(post_id in p.impression.stimulus_ids for p in third.presentations)
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
    shown_sets = [set(p.impression.stimulus_ids) for p in fifth.presentations]
    assert shown_sets[0] == shown_sets[1] == shown_sets[2] == shown_sets[3]
    for presentation in fifth.presentations:
        assert presentation.impression.channel is Channel.FORUM
        assert all(e.reason.value == "forum" for e in presentation.impression.exposures)


def test_votes_affect_ranking_only_through_the_upstream_score():
    population = make_population()
    world = make_world(config=FORUM, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in first.presentations}
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
    for presentation in fourth.presentations:
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
        config=WorldConfig(platform="social_feed", recsys_mode="random", involvement_default=100.0),
        population=make_population(),
        scenario=hourly,
    )
    hot_world = make_world(
        config=WorldConfig(platform="social_feed", recsys_mode="reddit_hot", involvement_default=100.0),
        population=make_population(),
        scenario=dict(hourly),
    )
    for world in (random_world, hot_world):
        world.reset()
        first = world.step(1, [])
        actors = sorted(p.impression.persona_id for p in first.presentations)
        by_persona = {p.impression.persona_id: p for p in first.presentations}
        poster = next(pid for pid in PERSONA_IDS if pid in by_persona)
        second = world.step(
            2,
            [act_turn(by_persona[poster], 1, "post", "early post, one like")]
            + [answer_turn(by_persona[pid], 2 + n, action="ignore") for n, pid in enumerate(actors) if pid != poster],
        )
        early = next(s for s in second.published if s.kind.value == "peer_post")
        by_second = {p.impression.persona_id: p for p in second.presentations}
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
    assert exposure_concentration([hot_fifth]) == 1.0
    assert {e.stimulus_id for p in hot_fifth.presentations for e in p.impression.exposures} == {
        hot_world._late_post
    }
    assert exposure_concentration([random_fifth]) < exposure_concentration([hot_fifth])
    assert isinstance(Forum("reddit_global"), Forum)
