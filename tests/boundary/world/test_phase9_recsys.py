"""Phase 9: `twitter` and `twhin` recsys.

Both read signals computed elsewhere: `twitter` ranks by interest match
against profile embeddings carried in the population manifest, `twhin` is
graph-aware, using degree centralities from the generated graph. Neither
recomputes its signal per tick.
"""

import pytest

from simcore.schemas import Channel
from simcore.world import RecsysMode, WorldConfig, exposure_concentration
from tests.study_builders import PERSONA_IDS, scenario_payload

from .helpers import act_turn, answer_turn, make_population, make_world, on_channel, targeted_turn

HOURLY_ONE = scenario_payload(tick_unit="hour", exposure_budget=1)
PROFILES = (
    ("p-000001", (1.0, 0.0)),
    ("p-000002", (1.0, 0.0)),
    ("p-000003", (0.0, 1.0)),
    ("p-000004", (0.0, 1.0)),
)


class FakeEmbedder:
    """Deterministic vectors by keyword: hub texts match hub personas, periph matches periph."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        return [
            [1.0, 0.0] if "hub" in text else ([0.0, 1.0] if "periph" in text else [1.0, 1.0])
            for text in texts
        ]


def drive_modes():
    """One hub post by p-000002, one periph post by p-000004, four likes hammering
    the periph post — then the tick-4 delta under every mode."""
    embed = FakeEmbedder()
    worlds = {}
    for mode in ("random", "reddit_hot", "twitter", "twhin"):
        config = WorldConfig(
            platform="social_feed",
            recsys_mode=mode,
            involvement_default=100.0,
            profile_vectors=PROFILES,
            embed_texts=embed,
        )
        worlds[mode] = make_world(config=config, population=make_population(), scenario=dict(HOURLY_ONE))
    for mode, world in worlds.items():
        world.reset()
        first = world.step(1, [])
        by_persona = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.SOCIAL_FEED)}
        second = world.step(
            2,
            [
                answer_turn(by_persona["p-000001"], 1, action="ignore"),
                act_turn(by_persona["p-000002"], 2, "post", "hub post about training"),
                answer_turn(by_persona["p-000003"], 3, action="ignore"),
                act_turn(by_persona["p-000004"], 4, "post", "periph post about training"),
            ],
        )
        posts = {s.author: s.stimulus_id for s in second.published if s.kind.value == "peer_post"}
        world.step(
            3,
            [targeted_turn(pid, 2, posts["p-000004"], 10 + n, "like") for n, pid in enumerate(PERSONA_IDS)],
        )
        worlds[mode] = (world, world.step(4, []), posts)
    return worlds, embed


def test_twitter_ranks_by_interest_match_with_no_embedding_call_at_step_time():
    worlds, embed = drive_modes()
    world, fourth, posts = worlds["twitter"]
    hub, periph = posts["p-000002"], posts["p-000004"]
    feed = on_channel(fourth.presentations, Channel.SOCIAL_FEED)
    shown = {p.impression.persona_id: p.impression.exposures[0].stimulus_id for p in feed}
    assert shown["p-000001"] == hub and shown["p-000002"] == hub
    assert shown["p-000003"] == periph and shown["p-000004"] == periph
    embedded = [text for call in embed.calls for text in call]
    assert len(set(embedded)) == len(embedded) == world.vectorized_stimuli()
    calls_before = len(embed.calls)
    world.step(5, [])
    world.step(6, [])
    assert len(embed.calls) == calls_before, "ranking reads cached vectors and never embeds"


def test_twhin_uses_degree_centralities_computed_once():
    worlds, _ = drive_modes()
    world, fourth, posts = worlds["twhin"]
    assert world.degree_centrality("p-000002") == pytest.approx(2 / 3)
    assert world.degree_centrality("p-000001") == pytest.approx(1 / 3)
    hub = posts["p-000002"]
    assert {e.stimulus_id for p in on_channel(fourth.presentations, Channel.SOCIAL_FEED) for e in p.impression.exposures} == {hub}


def test_all_four_modes_are_selectable_and_differ_on_one_fixture():
    worlds, _ = drive_modes()

    def feed_delta(fourth):
        return fourth.model_copy(update={"presentations": tuple(on_channel(fourth.presentations, Channel.SOCIAL_FEED))})

    concentrations = {mode: exposure_concentration([feed_delta(fourth)]) for mode, (_, fourth, _) in worlds.items()}
    assert concentrations["reddit_hot"] == 1.0
    assert concentrations["twhin"] == 1.0
    assert concentrations["twitter"] == 0.5
    assert concentrations["random"] < 1.0
    assignments = {
        mode: tuple(
            (p.impression.persona_id, p.impression.exposures[0].stimulus_id)
            for p in on_channel(fourth.presentations, Channel.SOCIAL_FEED)
        )
        for mode, (_, fourth, _) in worlds.items()
    }
    assert len(set(assignments.values())) == 4
    hot_shown = {e.stimulus_id for p in on_channel(worlds["reddit_hot"][1].presentations, Channel.SOCIAL_FEED) for e in p.impression.exposures}
    assert hot_shown == {worlds["reddit_hot"][2]["p-000004"]}


def test_a_mode_whose_signal_is_missing_fails_at_reset_not_mid_run():
    twitter = make_world(config=WorldConfig(platform="social_feed", recsys_mode="twitter"))
    with pytest.raises(ValueError, match="profile embeddings"):
        twitter.reset()
    twhin = make_world(config=WorldConfig(platform="social_feed", recsys_mode="twhin"))
    with pytest.raises(ValueError, match="degree centralities"):
        twhin.reset()


def test_every_mode_remains_deterministic_under_a_fixed_seed():
    worlds, _ = drive_modes()
    for mode in ("random", "reddit_hot", "twitter", "twhin"):
        config = WorldConfig(
            platform="social_feed",
            recsys_mode=mode,
            involvement_default=100.0,
            profile_vectors=PROFILES,
            embed_texts=FakeEmbedder(),
        )
        rerun = make_world(config=config, population=make_population(), scenario=dict(HOURLY_ONE))
        rerun.reset()
        first = rerun.step(1, [])
        by_persona = {p.impression.persona_id: p for p in on_channel(first.presentations, Channel.SOCIAL_FEED)}
        second = rerun.step(
            2,
            [
                answer_turn(by_persona["p-000001"], 1, action="ignore"),
                act_turn(by_persona["p-000002"], 2, "post", "hub post about training"),
                answer_turn(by_persona["p-000003"], 3, action="ignore"),
                act_turn(by_persona["p-000004"], 4, "post", "periph post about training"),
            ],
        )
        posts = {s.author: s.stimulus_id for s in second.published if s.kind.value == "peer_post"}
        rerun.step(
            3,
            [targeted_turn(pid, 2, posts["p-000004"], 10 + n, "like") for n, pid in enumerate(PERSONA_IDS)],
        )
        assert [p.impression for p in rerun.step(4, []).presentations] == [
            p.impression for p in worlds[mode][1].presentations
        ]
