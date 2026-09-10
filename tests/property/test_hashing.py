import json
import os
import subprocess
import sys
from pathlib import Path

import simcore.schemas.base as base_module
from simcore.schemas import canonical_hash, canonical_payload
from tests.demo_contracts import DemoBrief, DemoRunConfig, make_brief_payload, make_run_config_payload

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_hash_ignores_dict_insertion_order():
    first = DemoBrief.model_validate(
        make_brief_payload(
            target_filters={"a": "1", "b": "2"},
            audience_mix={"x": 0.5, "y": 0.5},
        )
    )
    second = DemoBrief.model_validate(
        make_brief_payload(
            target_filters={"b": "2", "a": "1"},
            audience_mix={"y": 0.5, "x": 0.5},
        )
    )
    assert canonical_hash(first) == canonical_hash(second)


def test_hash_ignores_nested_dict_insertion_order():
    first = DemoRunConfig.model_validate(make_run_config_payload())
    second = DemoRunConfig.model_validate(
        make_run_config_payload(
            brief=make_brief_payload(
                target_filters={"region": "urban", "age_band": "25_40"},
                audience_mix={"dieters": 0.4, "gym_regulars": 0.6},
            )
        )
    )
    assert canonical_hash(first) == canonical_hash(second)


def test_excluded_field_does_not_move_hash():
    first = DemoBrief.model_validate(make_brief_payload(fetched_at="2026-01-01T00:00:00Z"))
    second = DemoBrief.model_validate(make_brief_payload(fetched_at="2030-06-30T12:00:00Z"))
    assert first.fetched_at != second.fetched_at
    assert canonical_hash(first) == canonical_hash(second)


def test_observed_cost_does_not_move_run_hash():
    first = DemoRunConfig.model_validate(make_run_config_payload(observed_cost=0.0))
    second = DemoRunConfig.model_validate(make_run_config_payload(observed_cost=999.0))
    assert canonical_hash(first) == canonical_hash(second)


def test_schema_version_folds_into_run_hash_and_absent_from_brief_hash(monkeypatch):
    run = DemoRunConfig.model_validate(make_run_config_payload())
    brief = DemoBrief.model_validate(make_brief_payload())
    run_before = canonical_hash(run)
    brief_before = canonical_hash(brief)

    monkeypatch.setattr(base_module, "SCHEMA_VERSION", "9.9.9")

    assert canonical_hash(run) != run_before
    assert canonical_hash(brief) == brief_before


def test_version_key_present_only_for_run_config_payload():
    assert "schema_version" not in canonical_payload(DemoBrief.model_validate(make_brief_payload()))
    assert "schema_version" in canonical_payload(DemoRunConfig.model_validate(make_run_config_payload()))


def test_hash_identical_across_processes():
    payload = make_run_config_payload()
    own = canonical_hash(DemoRunConfig.model_validate(payload))
    code = (
        "import json, sys;"
        "from simcore.schemas import canonical_hash;"
        "from tests.demo_contracts import DemoRunConfig;"
        "print(canonical_hash(DemoRunConfig.model_validate(json.loads(sys.argv[1]))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(payload)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == own
