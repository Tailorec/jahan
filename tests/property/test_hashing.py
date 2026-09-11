import json
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from hypothesis import given
from hypothesis import strategies as st

import simcore.schemas.base as base_module
from simcore.schemas import FrozenDict, NonEmptyStr, SimBaseModel, canonical_hash, canonical_payload
from tests.demo_contracts import DemoBrief, DemoRunConfig, make_brief_payload, make_run_config_payload

REPO_ROOT = Path(__file__).resolve().parents[2]


class DemoStudy(SimBaseModel):
    briefs: tuple[DemoBrief, ...]
    by_audience: FrozenDict[str, DemoBrief]


def hash_in_subprocess(code: str, *args: str, hash_seed: str | None = None) -> str:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    if hash_seed is not None:
        env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, cwd=REPO_ROOT, env=env
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


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


@given(mix=st.dictionaries(st.from_regex(r"[a-z]{1,8}", fullmatch=True), st.floats(0.0, 1.0), min_size=1))
def test_hash_is_invariant_to_mapping_insertion_order(mix):
    forward = DemoBrief.model_validate(make_brief_payload(audience_mix=mix))
    backward = DemoBrief.model_validate(make_brief_payload(audience_mix=dict(reversed(list(mix.items())))))
    assert canonical_hash(forward) == canonical_hash(backward)


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


def test_excluded_field_nested_in_a_model_does_not_move_hash():
    first = DemoRunConfig.model_validate(
        make_run_config_payload(brief=make_brief_payload(fetched_at="2026-01-01T00:00:00Z"))
    )
    second = DemoRunConfig.model_validate(
        make_run_config_payload(brief=make_brief_payload(fetched_at="2030-06-30T12:00:00Z"))
    )
    assert first.brief.fetched_at != second.brief.fetched_at
    assert canonical_hash(first) == canonical_hash(second)


def test_excluded_field_nested_in_sequences_and_mappings_does_not_move_hash():
    def study(fetched_at: str) -> DemoStudy:
        brief = DemoBrief.model_validate(make_brief_payload(fetched_at=fetched_at))
        return DemoStudy(briefs=(brief, brief), by_audience={"gym_regulars": brief})

    assert canonical_hash(study("2026-01-01")) == canonical_hash(study("2030-06-30"))


def test_nested_exclusion_still_detects_real_changes():
    brief = DemoBrief.model_validate(make_brief_payload())
    renamed = DemoBrief.model_validate(make_brief_payload(title="Sparkling water"))
    assert canonical_hash(DemoStudy(briefs=(brief,), by_audience={})) != canonical_hash(
        DemoStudy(briefs=(renamed,), by_audience={})
    )


def test_observed_cost_does_not_move_run_hash():
    first = DemoRunConfig.model_validate(make_run_config_payload(observed_cost=0.0))
    second = DemoRunConfig.model_validate(make_run_config_payload(observed_cost=999.0))
    assert canonical_hash(first) == canonical_hash(second)


def test_negative_zero_hashes_like_zero():
    zero = DemoBrief.model_validate(make_brief_payload(audience_mix={"gym_regulars": 0.0}))
    negative = DemoBrief.model_validate(make_brief_payload(audience_mix={"gym_regulars": -0.0}))
    assert zero == negative
    assert canonical_hash(zero) == canonical_hash(negative)


def test_schema_version_folds_into_run_hash_and_absent_from_brief_hash(monkeypatch):
    run = DemoRunConfig.model_validate(make_run_config_payload())
    brief = DemoBrief.model_validate(make_brief_payload())
    run_before = canonical_hash(run)
    brief_before = canonical_hash(brief)

    monkeypatch.setattr(base_module, "SCHEMA_VERSION", "9.9.9")

    assert canonical_hash(run) != run_before
    assert canonical_hash(brief) == brief_before


def test_version_folded_under_reserved_key_only_for_run_config():
    assert "_schema_version" not in canonical_payload(DemoBrief.model_validate(make_brief_payload()))
    run_payload = canonical_payload(DemoRunConfig.model_validate(make_run_config_payload()))
    assert run_payload["_schema_version"] == base_module.SCHEMA_VERSION


def test_field_named_schema_version_cannot_displace_the_folded_version(monkeypatch):
    class Versioned(SimBaseModel):
        _hash_version_: ClassVar[bool] = True
        schema_version: NonEmptyStr

    model = Versioned(schema_version="0.0.1")
    before = canonical_hash(model)
    assert canonical_payload(model)["schema_version"] == "0.0.1"

    monkeypatch.setattr(base_module, "SCHEMA_VERSION", "9.9.9")

    assert canonical_hash(model) != before


def test_hash_identical_across_processes():
    payload = make_run_config_payload()
    code = (
        "import json, sys;"
        "from simcore.schemas import canonical_hash;"
        "from tests.demo_contracts import DemoRunConfig;"
        "print(canonical_hash(DemoRunConfig.model_validate(json.loads(sys.argv[1]))))"
    )
    own = canonical_hash(DemoRunConfig.model_validate(payload))
    assert hash_in_subprocess(code, json.dumps(payload)) == own


def test_set_field_hash_independent_of_process_hash_seed():
    code = (
        "from simcore.schemas import canonical_hash;"
        "from tests.demo_contracts import DemoPolicy;"
        "print(canonical_hash(DemoPolicy(completable=frozenset("
        "['economics', 'media', 'decision_rules', 'budget', 'loyalty', 'substitutes']))))"
    )
    hashes = {hash_in_subprocess(code, hash_seed=seed) for seed in ("0", "1", "2", "3", "4")}
    assert len(hashes) == 1
