"""Phase 2: what every report carries — trust once, validation last, method disclosure."""

import pytest

from simcore.report import render
from simcore.schemas import TrustStatement
from tests.boundary.report.support import digests, finding_payload, pack
from tests.study_builders import run_config_payload


def test_every_report_carries_the_runs_trust_statement_exactly_once():
    report = render([finding_payload()], digests(), pack())
    assert report.markdown.count("uncalibrated") == 1
    assert report.markdown.count("## Trust") == 1
    assert "the engine has never been benchmarked against human purchase intent" in report.markdown
    assert report.data["trust"] == {
        "level": "uncalibrated",
        "caveats": ["the engine has never been benchmarked against human purchase intent"],
    }


def test_a_calibrated_trust_statement_also_renders_exactly_once():
    trust = TrustStatement.model_validate({
        "level": "category_benchmarked",
        "calibration_ref": {
            "benchmark_report_hash": "aa" * 32,
            "human_study_hash": "bb" * 32,
            "category": "beverage_protein",
            "distribution_similarity": 0.86,
            "rank_attainment": 0.83,
            "checked_at": "2026-09-11T00:00:00Z",
        },
    })
    report = render([finding_payload()], digests(), pack(trust=trust))
    assert report.markdown.count("category_benchmarked") == 1
    assert report.data["trust"]["level"] == "category_benchmarked"


def test_every_report_ends_with_its_recommended_real_world_validation():
    validation = "run a blind taste test with 200 category buyers before launch"
    report = render([finding_payload()], digests(), pack(validation=validation))
    assert report.markdown.rstrip().endswith(validation)
    assert list(report.data)[-1] == "validation"
    assert report.data["validation"] == validation


def test_the_method_disclosure_names_pins_seeds_templates_and_engine_commit():
    report = render([finding_payload()], digests(), pack())
    config = run_config_payload()
    for pin in (config["pins"]["tier_a"], config["pins"]["tier_b"], config["pins"]["embed"]):
        assert pin in report.markdown
    for seed in config["seeds"]:
        assert repr(seed) in report.markdown
    for name, template_hash in config["template_hashes"].items():
        assert name in report.markdown and template_hash in report.markdown
    assert "0a35555" in report.markdown
    method = report.data["method"]
    assert {entry["role"] for entry in method["pins"]} >= {"tier_a", "tier_b", "embed"}
    assert method["seeds"] == list(config["seeds"])
    assert report.data["engine_commit"] == "0a35555"


def test_a_run_forced_across_engine_versions_says_so():
    report = render([finding_payload()], digests(), pack(forced_from=("0000001", "0000002"), engine_commit="0000003"))
    assert "forced across engine versions" in report.markdown
    assert "0000001" in report.markdown and "0000002" in report.markdown
    assert report.data["forced_from"] == ["0000001", "0000002"]
    plain = render([finding_payload()], digests(), pack())
    assert "forced across engine versions" not in plain.markdown
    assert plain.data["forced_from"] == []


@pytest.mark.parametrize(
    "removal",
    [{"trust": None}, {"validation": "   "}, {"engine_commit": ""}, {"config": None}],
    ids=["no-trust", "no-validation", "no-engine-commit", "no-config"],
)
def test_neither_format_renders_without_all_three_parts(removal):
    with pytest.raises(ValueError):
        pack(**removal)
