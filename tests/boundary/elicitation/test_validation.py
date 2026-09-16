"""Phase 8: the mapping validation on human reviews, deterministic in CI on the fake."""

from collections import Counter
from pathlib import Path

import pytest

from simcore.elicitation import (
    anchor_hash,
    load_anchor_version,
    synthetic_reviews,
    validate_mapping,
)
from simcore.ports.fake import FakeEmbed
from tests.boundary.elicitation.staging import FAKE_MODEL, stage_passing

ANCHORS_DIR = Path(__file__).resolve().parents[3] / "anchors"
SATISFACTION_HASH = anchor_hash(load_anchor_version(ANCHORS_DIR / "satisfaction" / "v1.json"))


@pytest.fixture()
def base(tmp_path: Path) -> dict:
    staged = stage_passing(tmp_path)
    return dict(anchors_dir=staged, anchor_set_id="satisfaction-v1", anchor_version="v1", anchor_hash_pinned=SATISFACTION_HASH)


def test_about_five_hundred_reviews_balanced_from_a_seed_and_none_committed(tmp_path):
    before = {path for path in ANCHORS_DIR.rglob("*")}
    sample = synthetic_reviews(500, seed=7)
    assert len(sample.texts) == 500
    assert Counter(sample.stars) == {1: 100, 2: 100, 3: 100, 4: 100, 5: 100}
    again = synthetic_reviews(500, seed=7)
    assert again.texts == sample.texts
    assert {path for path in ANCHORS_DIR.rglob("*")} == before
    assert (tmp_path / "reviews.jsonl").exists() is False


def test_ssr_metrics_reported_beside_a_text_blind_baseline(base):
    report = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8, model_id=FAKE_MODEL), seed=7, **base)
    assert set(report["metrics"]) == {"log_loss", "brier", "expected_rating_spearman"}
    assert set(report["baseline"]) - {"name"} == {"log_loss", "brier", "expected_rating_spearman"}
    assert report["baseline"]["name"] == "uniform text-blind"
    # The fake carries no sentiment signal, so SSR scores about level with the baseline here;
    # beating it is the real model's job in the evaluation, not the fake's.
    assert abs(report["metrics"]["log_loss"] - report["baseline"]["log_loss"]) < 0.15


def test_the_satisfaction_anchors_are_a_pinned_version_and_the_report_names_everything(base):
    report = validate_mapping(
        synthetic_reviews(50, seed=7), FakeEmbed(dim=8, model_id=FAKE_MODEL), seed=7,
        epsilon=0.5, temperature=2.0, **base,
    )
    assert (report["anchor_set_id"], report["anchor_version"], report["anchor_hash"]) == (
        "satisfaction-v1", "v1", SATISFACTION_HASH,
    )
    assert report["served_embedding_model"] == [FAKE_MODEL]
    assert (report["epsilon"], report["temperature"]) == (0.5, 2.0)
    assert (report["sample_size"], report["seed"]) == (50, 7)
    assert report["dataset"]["location"] and report["dataset"]["terms"]
    with pytest.raises(ValueError, match="altered since pinning"):
        validate_mapping(synthetic_reviews(10, seed=1), FakeEmbed(dim=8, model_id=FAKE_MODEL), **{**base, "anchor_hash_pinned": "00" * 32})


def test_a_fake_scoring_identical_text_identically_is_deterministic_in_ci(base):
    first = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8, model_id=FAKE_MODEL), seed=7, **base)
    second = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8, model_id=FAKE_MODEL), seed=7, **base)
    assert first["metrics"] == second["metrics"]


def test_the_gateway_guide_serves_titan_embeddings_through_litellm():
    guide = (Path(__file__).resolve().parents[3] / "docs" / "inference.md").read_text()
    assert "titan-embed-text-v2" in guide.lower() or "titan text embeddings v2" in guide.lower()
    assert "litellm" in guide.lower()


def test_the_satisfaction_version_that_failed_its_check_is_never_validated():
    """validate_mapping pinned whatever file it loaded, and the command computed its pin from that same file, so the
    satisfaction v1 that failed on Titan once produced a full report."""
    with pytest.raises(ValueError, match="failed its check"):
        validate_mapping(synthetic_reviews(20, seed=1), FakeEmbed(dim=8, model_id=FAKE_MODEL), anchors_dir=ANCHORS_DIR,
                         anchor_set_id="satisfaction-v1", anchor_version="v1", anchor_hash_pinned=SATISFACTION_HASH)
    with pytest.raises(TypeError):
        validate_mapping(synthetic_reviews(20, seed=1), FakeEmbed(dim=8, model_id=FAKE_MODEL), anchors_dir=ANCHORS_DIR)  # a pin is required


def test_the_command_refuses_a_failed_version_before_any_client_exists(tmp_path, monkeypatch):
    import sys

    from simcore.elicitation import __main__ as command

    def no_client(*args, **kwargs):
        raise AssertionError("a client was created for a version that cannot be validated")

    monkeypatch.setattr(command, "InferenceClient", no_client)
    monkeypatch.setattr(sys, "argv", ["elicitation", "--synthetic", "10", "--anchors-dir", str(ANCHORS_DIR), "--out", str(tmp_path / "r.json")])
    with pytest.raises(SystemExit, match="failed its check"):
        command.main()
