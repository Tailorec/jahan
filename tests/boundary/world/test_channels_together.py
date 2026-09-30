"""Channels together: every ticked platform presents, posts stay on their platform,
word of mouth follows its checkbox, and word of mouth alone starts from a launch reach."""

from simcore.schemas import Channel, derive_world_id, derive_world_seed
from simcore.world import WorldConfig
from tests.study_builders import scenario_payload

from .helpers import act_turn, answer_turn, drive, make_population, make_world, on_channel


def test_an_active_persona_reacts_once_per_ticked_platform_per_tick():
    world = make_world(
        config=WorldConfig(channels=frozenset({"social_feed", "forum"})),
        population=make_population(),
    )
    world.reset()
    delta = world.step(1, [])
    by_channel: dict[str, list] = {}
    for presentation in delta.presentations:
        by_channel.setdefault(presentation.impression.channel.value, []).append(presentation)
    assert set(by_channel) == {"social_feed", "forum", "survey_room"}
    feed_ids = {p.impression.persona_id for p in by_channel["social_feed"]}
    forum_ids = {p.impression.persona_id for p in by_channel["forum"]}
    assert feed_ids == forum_ids and feed_ids
    for persona in feed_ids:
        assert sum(1 for p in by_channel["social_feed"] if p.impression.persona_id == persona) == 1
        assert sum(1 for p in by_channel["forum"] if p.impression.persona_id == persona) == 1


def test_a_single_ticked_platform_presents_nothing_on_the_other():
    feed = make_world(config=WorldConfig(channels=frozenset({"social_feed"})), population=make_population())
    feed.reset()
    assert on_channel(feed.step(1, []).presentations, Channel.FORUM) == []
    forum = make_world(config=WorldConfig(channels=frozenset({"forum"})), population=make_population())
    forum.reset()
    assert on_channel(forum.step(1, []).presentations, Channel.SOCIAL_FEED) == []


def test_a_post_authored_on_one_platform_never_appears_on_the_other():
    world = make_world(
        config=WorldConfig(channels=frozenset({"social_feed", "forum"})),
        population=make_population(),
    )
    world.reset()
    first = world.step(1, [])
    feed = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.SOCIAL_FEED)}
    forum = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.FORUM)}
    second = world.step(
        2,
        [
            act_turn(feed["p-000001"], 1, "post", "a feed post after training"),
            act_turn(forum["p-000002"], 2, "post", "a forum thread after training"),
        ],
    )
    feed_post = next(s for s in second.published if s.text == "a feed post after training")
    forum_post = next(s for s in second.published if s.text == "a forum thread after training")
    third = world.step(3, [])
    feed_shown = {e.stimulus_id for p in on_channel(third.presentations, Channel.SOCIAL_FEED) for e in p.impression.exposures}
    forum_shown = {e.stimulus_id for p in on_channel(third.presentations, Channel.FORUM) for e in p.impression.exposures}
    assert feed_post.stimulus_id in feed_shown and feed_post.stimulus_id not in forum_shown
    assert forum_post.stimulus_id in forum_shown and forum_post.stimulus_id not in feed_shown


def test_word_of_mouth_off_means_no_wom_impression_in_the_whole_run():
    world = make_world(
        config=WorldConfig(channels=frozenset({"social_feed"})),
        population=make_population(),
        scenario=scenario_payload(channels=["social_feed"], horizon_ticks=4),
    )
    deltas, turns = drive(world, range(1, 4), action="comment")
    assert deltas
    for tick, tick_turns in turns.items():
        assert tick_turns
    for delta in deltas[1:]:
        assert not [p for p in delta.presentations if p.impression.channel is Channel.WOM]


def test_a_world_reads_its_channels_from_the_scenario():
    """No channels in the config means the scenario's: the hashed truth drives the world (ADR 0048)."""
    from .helpers import felt_turn

    scenario = scenario_payload(channels=["social_feed", "wom"])
    legacy = make_world(config=WorldConfig(channels={"social_feed", "wom"}), population=make_population())
    explicit = make_world(population=make_population(), scenario=scenario)
    assert legacy._channels == explicit._channels == {Channel.SOCIAL_FEED, Channel.WOM}
    legacy.reset()
    explicit.reset()
    first = legacy.step(1, [])
    explicit.step(1, [])
    by_persona = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.SOCIAL_FEED)}
    turns = [felt_turn(by_persona["p-000001"], 1)] + [
        answer_turn(by_persona[pid], 2 + n, action="ignore")
        for n, pid in enumerate(sorted(by_persona))
        if pid != "p-000001"
    ]
    assert [p.impression for p in legacy.step(2, turns).presentations] == [
        p.impression for p in explicit.step(2, turns).presentations
    ]


def test_word_of_mouth_alone_starts_from_a_seeded_launch_reach():
    world = make_world(
        config=WorldConfig(channels=frozenset({"wom"})),
        population=make_population(),
        scenario=scenario_payload(channels=["wom"], launch_reach=0.5, horizon_ticks=4),
    )
    deltas, _ = drive(world, range(1, 4))
    opening = deltas[0]
    launch = on_channel(opening.presentations, Channel.WOM)
    assert len(launch) == round(0.5 * 4)
    assert all(e.reason.value == "launch" for p in launch for e in p.impression.exposures)
    # Telling starts at tick 1 and the run reaches its horizon without crashing.
    assert len(deltas) == 4


def test_launch_reach_is_drawn_from_the_world_seed():
    """One seed draws the same launch set twice; two seeds draw different sets."""

    def launch_set(world_seed: int):
        world = make_world(
            config=WorldConfig(channels=frozenset({"wom"})),
            population=make_population(),
            scenario=scenario_payload(channels=["wom"], launch_reach=0.5, horizon_ticks=4),
        )
        world._world_seed = world_seed
        return {p.impression.persona_id for p in on_channel(world.reset().presentations, Channel.WOM)}

    first = derive_world_seed(4021, "v1baseline")
    assert launch_set(first) == launch_set(first) != set()
    assert launch_set(first) != launch_set(derive_world_seed(917731, "v1baseline"))


def test_channels_change_identity_but_not_draws_or_people():
    from simcore.schemas import Scenario

    from tests.study_builders import population_manifest_payload

    base = Scenario.model_validate(scenario_payload())
    fed_scenario = Scenario.model_validate(scenario_payload(channels=["social_feed"]))
    assert derive_world_id(base, 4021, "ab12" * 16) != derive_world_id(fed_scenario, 4021, "ab12" * 16)
    plain = make_world(population=make_population())
    fed_world = make_world(
        config=WorldConfig(channels=frozenset({"social_feed"})),
        population=make_population(),
        scenario=scenario_payload(channels=["social_feed"]),
    )
    assert plain._world_seed == fed_world._world_seed == derive_world_seed(4021, "v1baseline")
    assert plain._activated(1) == fed_world._activated(1)
    assert population_manifest_payload()["population_hash"] == make_population().manifest.population_hash
