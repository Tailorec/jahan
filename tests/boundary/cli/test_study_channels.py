"""A study ticks any combination of feed, forum and word of mouth — or none, the concept test.

Channels, survey waves and launch reach are scenario content (ADR 0048): two studies over one
population and seed that differ only in their channels are different worlds, and the survey
room is a wave's internal channel, never a choice.
"""

import pytest

import json
from pathlib import Path

from simcore.schemas import Channel, Scenario, canonical_hash, derive_world_id, wave_ticks
from tests.boundary.cli.support import fake_args, run_command, run_id_from
from tests.study_builders import scenario_payload

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_the_survey_room_is_internal_and_never_a_study_choice():
    assert Channel.SURVEY_ROOM in set(Channel)
    assert {c.value for c in Channel} == {"survey_room", "social_feed", "forum", "wom"}
    text = (FRONTEND / "lib" / "study.ts").read_text()
    line = next(line for line in text.splitlines() if line.startswith("export const CHANNELS"))
    assert "survey_room" not in line


def test_channels_hash_with_the_scenario_but_share_the_seed():
    plain = Scenario.model_validate(scenario_payload())
    fed = Scenario.model_validate(scenario_payload(channels=["social_feed"]))
    assert canonical_hash(plain) != canonical_hash(fed)
    assert derive_world_id(plain, 4021, "ab12" * 16) != derive_world_id(fed, 4021, "ab12" * 16)
    from simcore.schemas import derive_world_seed

    assert derive_world_seed(4021, "v1baseline") == derive_world_seed(4021, "v1baseline")


def test_launch_reach_is_only_for_word_of_mouth_alone():
    Scenario.model_validate(scenario_payload(channels=["wom"], launch_reach=0.2))
    with pytest.raises(ValueError, match="launch_reach"):
        Scenario.model_validate(scenario_payload(channels=["social_feed"], launch_reach=0.2))
    with pytest.raises(ValueError, match="launch_reach"):
        Scenario.model_validate(scenario_payload(channels=[], launch_reach=0.2))


def test_wave_ticks_always_open_and_close_a_study():
    assert wave_ticks(2, 7) == (0, 2, 4, 6)
    assert wave_ticks(3, 5) == (0, 3, 4)
    assert wave_ticks(9, 5) == (0, 4)
    assert wave_ticks(1, 1) == (0,)


def test_an_unknown_channel_is_refused_before_it_draws_anything(tmp_path):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "88", channels="carrier_pigeon"))
    assert code != 0
    assert "social_feed" in output and "forum" in output and "wom" in output
    assert not out.exists() or not any(out.iterdir()), "a refused channel left a run behind"


def test_the_interface_offers_exactly_the_channels_a_study_can_tick():
    import json

    text = (FRONTEND / "lib" / "study.ts").read_text()
    line = next(line for line in text.splitlines() if line.startswith("export const CHANNELS"))
    offered = json.loads(line[line.index("["): line.index("]") + 1])
    assert offered == ["social_feed", "forum", "wom"]


@pytest.mark.parametrize(
    "channels",
    ["", "social_feed", "forum", "wom", "social_feed,forum", "social_feed,wom", "forum,wom",
     "social_feed,forum,wom"],
)
def test_every_channel_combination_runs_a_fake_study(tmp_path, channels):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "89", horizon=2, channels=channels))
    assert code == 0, output[-1500:]
    run_id = run_id_from(output)
    # The trace summary joins the run's whole record: writing it validates every world it read.
    assert json.loads((out / run_id / "trace-summary.json").read_text())["run_id"] == run_id


def test_a_feed_study_without_its_ranking_model_is_refused_naming_the_pin():
    from simcore.schemas import RunConfig
    from tests.study_builders import run_config_payload

    payload = run_config_payload()
    payload["pins"] = {key: value for key, value in payload["pins"].items() if key != "recsys_embed"}
    payload["scenarios"] = [scenario_payload(channels=["social_feed"])]
    with pytest.raises(ValueError, match="recsys_embed"):
        RunConfig.model_validate(payload)
    payload["scenarios"] = [scenario_payload(channels=["forum", "wom"])]
    RunConfig.model_validate(payload)  # no feed, no ranking model needed


def test_the_report_states_the_channels_waves_and_both_embedding_models(tmp_path):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "91", horizon=3, channels="social_feed,wom", survey_every=1))
    assert code == 0, output[-1500:]
    run_dir = out / run_id_from(output)
    markdown = (run_dir / "report.md").read_text()
    data = json.loads((run_dir / "report.json").read_text())
    assert "channels social_feed, wom; a survey wave every 1 ticks" in markdown
    assert "- recsys_embed: fake/recsys-embed-1" in markdown and "- embed: fake/embed-1" in markdown
    assert "no 4,000-post pre-filter" in markdown
    assert "Channels: social_feed" in markdown
    assert data["method"]["scenarios"][0]["channels"] == ["social_feed", "wom"]
    assert data["method"]["departures"]


def test_a_concept_test_report_says_it_is_one(tmp_path):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "92", horizon=1, channels=""))
    assert code == 0, output[-1500:]
    markdown = (out / run_id_from(output) / "report.md").read_text()
    assert "channels none (a concept test" in markdown
    assert "no 4,000-post pre-filter" not in markdown and "one-shot survey" not in markdown
