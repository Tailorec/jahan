import json
from pathlib import Path

from simcore.schemas import canonical_hash
from tests.demo_contracts import DemoBrief, DemoRunConfig

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "hash_stability.json"


def test_committed_fixture_pins_brief_hash():
    entry = json.loads(FIXTURE_PATH.read_text())["demo_brief"]
    assert canonical_hash(DemoBrief.model_validate(entry["payload"])) == entry["hash"]


def test_committed_fixture_pins_run_config_hash():
    entry = json.loads(FIXTURE_PATH.read_text())["demo_run_config"]
    assert canonical_hash(DemoRunConfig.model_validate(entry["payload"])) == entry["hash"]


def test_fixture_payloads_round_trip_through_json_text():
    data = json.loads(FIXTURE_PATH.read_text())
    brief_entry = data["demo_brief"]
    assert DemoBrief.model_validate_json(json.dumps(brief_entry["payload"])) == DemoBrief.model_validate(
        brief_entry["payload"]
    )
