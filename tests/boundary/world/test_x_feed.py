"""M15 phase 5: the feed ranks like X — in-network first, then interest × recency.

Ported from OASIS's `rec_sys_personalized_twh` and `refresh`: posts by ties and follows come
first, most liked first; every other post is ordered by `cosine(profile, post) ×
log((271.8 − age) / 100)`. Vectors come from the feed's own embedder, once per profile update
and once per post, so ranking never embeds.
"""

from math import log

import pytest

from simcore.schemas import Channel, ExposureReason
from simcore.world import World, WorldConfig
from simcore.world.recsys import recency_score, x_order
from tests.study_builders import scenario_payload

from .helpers import act_turn, answer_turn, make_header, make_population, make_world, on_channel, targeted_turn

FEED = {"social_feed"}
HOURLY_ONE = scenario_payload(tick_unit="hour", exposure_budget=1, channels=["social_feed"])


class KeywordEmbedder:
    """Deterministic vectors: 'hub' texts point one way, 'periph' the other, profiles in between."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        return [[1.0, 0.0] if "hub" in t else ([0.0, 1.0] if "periph" in t else [1.0, 1.0]) for t in texts]

    @property
    def texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


def x_world(embed=None, **config) -> World:
    config = {"channels": FEED, "feed_recsys_mode": "twitter", "involvement_default": 100.0, **config}
    return make_world(
        config=WorldConfig(embed_texts=embed or KeywordEmbedder(), **config),
        population=make_population(),
        scenario=dict(HOURLY_ONE),
    )


def post_from(world: World, delta, author: str, text: str, n: int):
    feed = {p.impression.persona_id: p for p in on_channel(delta.presentations, Channel.SOCIAL_FEED)}
    return act_turn(feed[author], n, "post", text)


def test_recency_is_upstreams_log_and_ends_where_upstream_says_it_ends():
    assert recency_score(0) == pytest.approx(log(2.718))
    assert recency_score(100) == pytest.approx(log(1.718))
    assert recency_score(272) == float("-inf")


def test_ties_come_first_most_liked_then_interest_times_recency_on_upstreams_numbers():
    vectors = {"c": (0.9, (1 - 0.81) ** 0.5), "d": (0.9, (1 - 0.81) ** 0.5), "e": (0.1, (1 - 0.01) ** 0.5)}
    order = x_order(
        ["e", "d", "c", "a", "b"],
        frozenset({"a", "b"}),
        {"a": 1, "b": 5, "e": 50},
        (1.0, 0.0),
        vectors,
        {"a": 0, "b": 3, "c": 0, "d": 100, "e": 0},
        world_seed=7,
        tick=5,
        persona_id="p-000001",
    )
    # c: .9 × log(2.718) ≈ .90 · d: .9 × log(1.718) ≈ .49 · e: .1 × log(2.718) ≈ .10; likes never reach them.
    assert order == ["b", "a", "c", "d", "e"]


def test_a_post_from_a_tie_outranks_a_better_matched_stranger_and_carries_the_network_reason():
    # p-000001 is tied to p-000002 only. p-000002 posts off-interest, p-000004 on-interest.
    world = x_world(profile_vectors=(("p-000001", (1.0, 0.0)),))
    world.reset()
    first = world.step(1, [])
    second = world.step(2, [
        post_from(world, first, "p-000002", "periph post about training", 1),
        post_from(world, first, "p-000004", "hub post about training", 2),
    ])
    posts = {s.author: s.stimulus_id for s in second.published}
    (seen,) = [p for p in on_channel(world.step(3, []).presentations, Channel.SOCIAL_FEED) if p.impression.persona_id == "p-000001"]
    (exposure,) = seen.impression.exposures
    assert exposure.stimulus_id == posts["p-000002"]
    assert exposure.reason is ExposureReason.NETWORK


def test_following_a_stranger_brings_their_posts_in_network():
    world = x_world(profile_vectors=(("p-000001", (0.0, 1.0)),))
    world.reset()
    first = world.step(1, [])
    second = world.step(2, [
        post_from(world, first, "p-000002", "periph post one", 1),
        post_from(world, first, "p-000004", "hub post one", 2),
    ])
    posts = {s.author: s.stimulus_id for s in second.published}
    world.step(3, [targeted_turn("p-000001", 2, posts["p-000004"], 1, "follow")])
    fourth = world.step(4, [targeted_turn("p-000003", 3, posts["p-000004"], 2, "like")])
    (seen,) = [p for p in on_channel(fourth.presentations, Channel.SOCIAL_FEED) if p.impression.persona_id == "p-000001"]
    # Both authors are now in network; the followed stranger's post has the like, so it leads.
    assert seen.impression.exposures[0].stimulus_id == posts["p-000004"]
    assert seen.impression.exposures[0].reason is ExposureReason.NETWORK


def test_embeddings_are_one_per_profile_update_and_one_per_post_and_ranking_never_embeds():
    embed = KeywordEmbedder()
    world = x_world(embed)
    opening = world.reset()
    personas = 4
    assert len(embed.texts) == personas + len(opening.published)
    first = world.step(1, [])
    world.step(2, [
        post_from(world, first, "p-000002", "hub post", 1),
        post_from(world, first, "p-000003", "periph post", 2),
    ])
    # Two posts, and two profiles refreshed with their author's latest post.
    assert len(embed.texts) == personas + len(opening.published) + 2 + 2
    assert sum("# Recent post:hub post" in text for text in embed.texts) == 1
    before = len(embed.calls)
    world.step(3, [])
    world.step(4, [])
    assert len(embed.calls) == before, "ranking reads cached vectors and never embeds"


def test_forum_posts_are_never_embedded_for_the_feed():
    embed = KeywordEmbedder()
    world = make_world(
        config=WorldConfig(channels={"social_feed", "forum"}, feed_recsys_mode="twitter", involvement_default=100.0, embed_texts=embed),
        population=make_population(),
        scenario=scenario_payload(tick_unit="hour", exposure_budget=1, channels=["social_feed", "forum"]),
    )
    world.reset()
    first = world.step(1, [])
    forum = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.FORUM)}
    before = len(embed.texts)
    world.step(2, [act_turn(forum["p-000001"], 1, "post", "a forum thread")])
    assert len(embed.texts) == before


def test_a_restored_feed_ranks_exactly_as_the_uninterrupted_one():
    def run_to(world, stop):
        world.reset()
        first = world.step(1, [])
        world.step(2, [
            post_from(world, first, "p-000002", "hub post", 1),
            post_from(world, first, "p-000004", "periph post", 2),
        ])
        return world

    uninterrupted = run_to(x_world(), 2)
    restored = World.restore(
        make_header(scenario=dict(HOURLY_ONE)),
        uninterrupted.checkpoint(),
        population=make_population(),
        config=WorldConfig(channels=FEED, feed_recsys_mode="twitter", involvement_default=100.0, embed_texts=KeywordEmbedder()),
    )
    assert [p.impression for p in restored.step(3, []).presentations] == [
        p.impression for p in uninterrupted.step(3, []).presentations
    ]


def test_the_x_feed_refuses_to_open_without_its_embedder():
    world = make_world(
        config=WorldConfig(channels=FEED, feed_recsys_mode="twitter"),
        population=make_population(),
        scenario=dict(HOURLY_ONE),
    )
    with pytest.raises(ValueError, match="recsys_embed"):
        world.reset()


def test_a_world_without_the_feed_needs_no_embedder_whatever_its_feed_mode():
    world = make_world(config=WorldConfig(channels={"forum"}, feed_recsys_mode="twitter"), population=make_population())
    world.reset()
    assert answer_turn  # the forum world opened without a ranking model


def test_ranking_vectors_are_float32_and_rank_exactly_as_float_tuples_did():
    from array import array

    import numpy as np

    rng = np.random.default_rng(3)
    ids = [f"s{i}" for i in range(40)]
    sent = {sid: rng.standard_normal(768).astype(np.float32).tolist() for sid in ids}
    profile = rng.standard_normal(768).astype(np.float32).tolist()
    ages = {sid: i % 5 for i, sid in enumerate(ids)}
    as_tuples = x_order(ids, frozenset(), {}, tuple(profile), {k: tuple(v) for k, v in sent.items()}, ages, 7, 3, "p")
    as_arrays = x_order(ids, frozenset(), {}, array("f", profile), {k: array("f", v) for k, v in sent.items()}, ages, 7, 3, "p")
    assert as_tuples == as_arrays

    world = x_world()
    world.reset()
    assert all(isinstance(v, array) and v.typecode == "f" for v in world._profile_vectors.values())
    assert world._stimulus_vectors and all(isinstance(v, array) for v in world._stimulus_vectors.values())
