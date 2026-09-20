"""A study is run on an environment that presents a stimulus. `wom` is a channel a message is delivered on, beside
another environment's own presentation; asking for it as the environment used to fail on the first tick, after the
population had been drawn."""

import json
from pathlib import Path

import pytest

from simcore.schemas import STUDY_CHANNELS, Channel
from tests.boundary.cli.support import fake_args, run_command

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_wom_is_a_delivery_channel_and_not_an_environment_a_study_runs_on():
    assert Channel.WOM in set(Channel)
    assert [channel.value for channel in STUDY_CHANNELS] == ["survey_room", "social_feed", "forum"]


def test_the_command_refuses_wom_before_it_draws_anything(tmp_path):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "88", channel="wom"))
    assert code != 0
    assert "survey_room" in output and "social_feed" in output and "forum" in output
    assert not out.exists() or not any(out.iterdir()), "a refused channel left a run behind"


def test_the_interface_offers_exactly_the_environments_a_study_can_run_on():
    text = (FRONTEND / "lib" / "study.ts").read_text()
    line = next(line for line in text.splitlines() if line.startswith("export const CHANNELS"))
    offered = json.loads(line[line.index("["): line.index("]") + 1])
    assert offered == [channel.value for channel in STUDY_CHANNELS]


@pytest.mark.parametrize("channel", [c.value for c in STUDY_CHANNELS])
def test_every_environment_a_study_can_run_on_runs_a_fake_study(tmp_path, channel):
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, "run-" + "0" * 24 + "89", horizon=2, channel=channel))
    assert code == 0, output[-1500:]
