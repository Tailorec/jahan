"""Phase 8: the community-scoped forum.

The same forum class, the opposite dynamic: threads scoped to the
population's Leiden communities, ranked by recency and agreement with no hot
score, so consensus hardens slowly where the global preset herds quickly.
"""

from pathlib import Path

from simcore.schemas import Channel
from simcore.world import Forum, WorldConfig, exposure_concentration
from simcore.world import recsys
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import act_turn, answer_turn, make_population, make_world, on_channel, targeted_turn

SCOPED = WorldConfig(channels={"forum", "wom"}, forum_preset="community_scoped", involvement_default=100.0)
GLOBAL = WorldConfig(channels={"forum", "wom"}, forum_preset="reddit_global", involvement_default=100.0)
HOURLY_ONE = scenario_payload(tick_unit="hour", exposure_budget=1)


def forum_only(delta):
    """This suite's subject is the forum: the wave rides along but is never what is asserted."""
    return on_channel(delta.presentations, Channel.FORUM)


def drive_split(config):
    """Two communities posting against each other: p-000001 roots thread A in
    community 1, p-000003 roots thread B in community 2, and community 1 votes
    thread A up. Returns the world, its tick-3 delta, and the threads by author.
    """
    world = make_world(config=config, population=make_population(), scenario=dict(HOURLY_ONE))
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = world.step(
        2,
        [
            act_turn(by_persona["p-000001"], 1, "post", "thread A from community one"),
            answer_turn(by_persona["p-000002"], 2, action="ignore"),
            act_turn(by_persona["p-000003"], 3, "post", "thread B from community two"),
            answer_turn(by_persona["p-000004"], 4, action="ignore"),
        ],
    )
    posts = {s.author: s.stimulus_id for s in second.published if s.kind.value == "peer_post"}
    third = world.step(
        3,
        [
            targeted_turn("p-000001", 2, posts["p-000001"], 10, "upvote", channel="forum"),
            targeted_turn("p-000002", 2, posts["p-000001"], 11, "upvote", channel="forum"),
            answer_turn(by_persona["p-000003"], 12, action="ignore"),
            answer_turn(by_persona["p-000004"], 13, action="ignore"),
        ],
    )
    return world, third, posts


def own_community_share(world, delta, posts):
    """Share of peer exposures authored inside the viewer's own community."""
    community_of = world._community_of
    authors = {sid: author for author, sid in posts.items()}
    own, total = 0, 0
    for presentation in delta.presentations:
        viewer = presentation.impression.persona_id
        for exposure in presentation.impression.exposures:
            author = authors.get(exposure.stimulus_id)
            if author is None:
                continue
            total += 1
            if community_of.get(author) == community_of.get(viewer):
                own += 1
    return own / total if total else 1.0


def test_threads_are_scoped_to_communities_and_ranked_without_hot(monkeypatch):
    monkeypatch.setattr(recsys, "hot_score", lambda *args: (_ for _ in ()).throw(AssertionError("hot in scoped")))
    world, third, posts = drive_split(SCOPED)
    shown = {
        p.impression.persona_id: {e.stimulus_id for e in p.impression.exposures} for p in forum_only(third)
    }
    assert shown["p-000001"] == {posts["p-000001"]}
    assert shown["p-000002"] == {posts["p-000001"]}
    assert shown["p-000003"] == {posts["p-000003"]}
    assert shown["p-000004"] == {posts["p-000003"]}


def test_both_presets_are_the_same_class_with_different_configuration():
    assert type(Forum("reddit_global")) is type(Forum("community_scoped")) is Forum
    assert Forum("reddit_global").preset != Forum("community_scoped").preset
    sources = Path("simcore/world").glob("*.py")
    definitions = 0
    for path in sources:
        definitions += sum(
            1
            for line in path.read_text().splitlines()
            if line == "class Forum:" or line.startswith("class Forum(")
        )
    assert definitions == 1


def test_the_two_presets_produce_measurably_different_concentration_and_divergence():
    global_world, global_third, global_posts = drive_split(GLOBAL)
    scoped_world, scoped_third, scoped_posts = drive_split(SCOPED)
    assert global_posts.keys() == scoped_posts.keys() == {"p-000001", "p-000003"}
    global_concentration = exposure_concentration(
        [global_third.model_copy(update={"presentations": tuple(forum_only(global_third))})]
    )
    scoped_concentration = exposure_concentration(
        [scoped_third.model_copy(update={"presentations": tuple(forum_only(scoped_third))})]
    )
    assert global_concentration == 1.0
    assert scoped_concentration == 0.5
    assert global_concentration != scoped_concentration
    assert own_community_share(global_world, global_third, global_posts) == 0.5
    assert own_community_share(scoped_world, scoped_third, scoped_posts) == 1.0


def test_a_persona_with_no_community_keeps_study_and_own_posts():
    world = make_world(config=SCOPED)
    world.reset()
    first = world.step(1, [])
    by_persona = {p.impression.persona_id: p for p in forum_only(first)}
    second = world.step(
        2, [act_turn(by_persona[pid], n, "post", f"post from {pid}") for n, pid in enumerate(sorted(by_persona))]
    )
    assert len(second.published) == len(by_persona)
    authors = {row["stimulus_id"]: row["author"] for row in world._store.stimuli_published_before(3)}
    third = world.step(3, [])
    assert third.presentations, "an unassigned persona is never silently excluded"
    for presentation in third.presentations:
        viewer = presentation.impression.persona_id
        for exposure in presentation.impression.exposures:
            author = authors[exposure.stimulus_id]
            assert author is None or author == viewer
