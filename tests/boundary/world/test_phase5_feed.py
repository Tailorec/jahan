"""Phase 5: the social feed.

Posts, comments, likes, reposts and quotes, with visible social-proof
counters. Everything a persona sees on the feed in one tick arrives as one
impression — grouped, not flattened — and its view carries only public
context: counts from earlier ticks, reply ancestry, tie strength and shared
community with each author.
"""

import json

from simcore.schemas import Channel
from simcore.world import WorldConfig
from tests.study_builders import scenario_payload

from .helpers import act_turn, answer_turn, make_population, make_world

FEED = WorldConfig(platform="social_feed")
WIDE = scenario_payload(exposure_budget=6)

PLAN = {
    "p-000001": ("post", "tried it after the gym, genuinely smooth"),
    "p-000002": ("comment", "how was the taste?"),
    "p-000003": ("like", None),
    "p-000004": ("ignore", None),
}


def drive_feed(plan=None):
    """A feed world over the representative population, run three ticks.

    Tick 1 presents the study stimuli; the plan's turns publish peer content
    at tick 2; tick 3 is the first delta that can show it. Returns the world
    and the deltas for ticks 1, 2 and 3.
    """
    population = make_population()
    world = make_world(config=FEED, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in first.presentations}
    turns = []
    for n, (persona, (action, verbatim)) in enumerate((plan or PLAN).items()):
        if action == "ignore":
            turns.append(answer_turn(by_persona[persona], n, action="ignore"))
        else:
            turns.append(act_turn(by_persona[persona], n, action, verbatim))
    second = world.step(2, turns)
    third = world.step(3, [])
    return world, first, second, third


def test_the_feed_supports_post_comment_like_repost_quote_and_follow():
    world, first, second, _ = drive_feed()
    kinds = sorted(s.kind.value for s in second.published)
    assert kinds == ["peer_post", "peer_reply"]
    post = next(s for s in second.published if s.kind.value == "peer_post")
    reply = next(s for s in second.published if s.kind.value == "peer_reply")
    commented = next(
        p.impression.exposures[0].stimulus_id for p in first.presentations if p.impression.persona_id == "p-000002"
    )
    assert post.author == "p-000001" and post.text == "tried it after the gym, genuinely smooth"
    assert reply.author == "p-000002" and reply.in_reply_to == commented
    assert "engagement:" in world.state_dump()

    population = make_population()
    world2 = make_world(config=FEED, population=population, scenario=WIDE)
    world2.reset()
    tick1 = world2.step(1, [])
    by_persona = {p.impression.persona_id: p for p in tick1.presentations}
    tick2 = world2.step(
        2,
        [
            act_turn(by_persona["p-000001"], 1, "repost"),
            act_turn(by_persona["p-000002"], 2, "quote", "quoting this for the group chat"),
            act_turn(by_persona["p-000003"], 3, "follow"),
        ],
    )
    assert [s.kind.value for s in tick2.published] == ["peer_post"]
    dump = world2.state_dump()
    assert "repost" in dump and "quote" in dump


def test_everything_seen_on_one_channel_in_one_tick_is_one_impression():
    _, first, _, _ = drive_feed()
    assert len(first.presentations) == 4
    for presentation in first.presentations:
        assert presentation.impression.channel is Channel.SOCIAL_FEED
        assert len(presentation.impression.exposures) > 1
        assert set(presentation.view.contexts) == set(presentation.impression.stimulus_ids)


def test_a_view_carries_counts_ancestry_tie_and_community_and_nothing_else():
    world, first, _, third = drive_feed()
    shown_at = {
        p.impression.persona_id: p.impression.exposures[0].stimulus_id for p in first.presentations
    }
    liked, commented = shown_at["p-000003"], shown_at["p-000002"]
    rows = world._store.stimuli_published_before(4)
    post_id = next(s["stimulus_id"] for s in rows if s["kind"] == "peer_post")
    reply_id = next(s["stimulus_id"] for s in rows if s["kind"] == "peer_reply")
    for presentation in third.presentations:
        viewer = presentation.impression.persona_id
        assert presentation.view.contexts[liked].likes == 1
        assert presentation.view.contexts[commented].replies == 1
        # Both targets are study stimuli, so no author relationship travels with them.
        assert presentation.view.contexts[commented].tie_strength is None
        assert presentation.view.contexts[commented].shared_community is None
        peer_view = presentation.view.contexts[post_id]
        assert peer_view.ancestry == ()
        if viewer == "p-000001":
            assert peer_view.tie_strength is None and peer_view.shared_community is None
        elif viewer == "p-000002":
            assert peer_view.tie_strength == 0.8 and peer_view.shared_community is True
        else:
            assert peer_view.tie_strength == 0.0 and peer_view.shared_community is False
        reply_view = presentation.view.contexts[reply_id]
        assert reply_view.ancestry == (commented,)


def test_no_view_carries_private_state_or_aggregate_outcomes():
    population = make_population()
    private_values = {
        str(value)
        for persona in population.personas
        for value in (list(persona.conditioning.values()) + list(persona.attributes.values()))
    }
    assert private_values
    _, _, _, third = drive_feed()
    forbidden_keys = {
        "conditioning",
        "attributes",
        "beliefs",
        "baseline_beliefs",
        "origins",
        "memories",
        "adoption",
        "pmf",
        "intent",
        "polarization",
    }

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in forbidden_keys, f"private state at {key}"
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    payload = json.loads(third.model_dump_json())
    walk(payload)
    text = json.dumps(payload)
    for secret in sorted(private_values):
        assert secret not in text, f"private value {secret!r} reaches a presentation"


def test_engagement_counts_include_only_engagement_from_earlier_ticks():
    population = make_population()
    world = make_world(config=FEED, population=population, scenario=WIDE)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in first.presentations}
    second = world.step(2, [act_turn(by_persona["p-000001"], 1, "post", "tried it after the gym")])
    post = next(s for s in second.published if s.kind.value == "peer_post")
    for presentation in second.presentations:
        assert post.stimulus_id not in presentation.view.contexts
    third = world.step(3, [])
    assert third.presentations[0].view.contexts[post.stimulus_id].likes == 0
    visible = [p for p in third.presentations if post.stimulus_id in p.impression.stimulus_ids]
    assert visible, "the peer post is shown from the tick after it is published"
    fourth = world.step(4, [act_turn(visible[0], 20, "like", subject_id=post.stimulus_id)])
    # Within-tick independence is structural: every presentation of one tick shares one count snapshot.
    def counts(presentation):
        context = presentation.view.contexts[post.stimulus_id]
        return (context.likes, context.reposts, context.replies, context.upvotes, context.downvotes)

    assert {counts(p) for p in fourth.presentations} == {counts(fourth.presentations[0])}
    assert fourth.presentations[0].view.contexts[post.stimulus_id].likes == 1
    fifth = world.step(5, [])
    assert fifth.presentations[0].view.contexts[post.stimulus_id].likes == 1
