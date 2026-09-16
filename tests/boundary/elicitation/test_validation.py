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

ANCHORS_DIR = Path(__file__).resolve().parents[3] / "anchors"
SATISFACTION_HASH = anchor_hash(load_anchor_version(ANCHORS_DIR / "satisfaction" / "v1.json"))
BASE = dict(anchors_dir=ANCHORS_DIR, anchor_set_id="satisfaction-v1", anchor_version="v1")


def test_about_five_hundred_reviews_balanced_from_a_seed_and_none_committed(tmp_path):
    before = {path for path in ANCHORS_DIR.rglob("*")}
    sample = synthetic_reviews(500, seed=7)
    assert len(sample.texts) == 500
    assert Counter(sample.stars) == {1: 100, 2: 100, 3: 100, 4: 100, 5: 100}
    again = synthetic_reviews(500, seed=7)
    assert again.texts == sample.texts
    assert {path for path in ANCHORS_DIR.rglob("*")} == before
    assert (tmp_path / "reviews.jsonl").exists() is False


def test_ssr_metrics_reported_beside_a_text_blind_baseline():
    report = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8), seed=7, **BASE)
    assert set(report["metrics"]) == {"log_loss", "brier", "expected_rating_spearman"}
    assert set(report["baseline"]) - {"name"} == {"log_loss", "brier", "expected_rating_spearman"}
    assert report["baseline"]["name"] == "uniform text-blind"
    # The fake carries no sentiment signal, so SSR scores about level with the baseline here;
    # beating it is the real model's job in the evaluation, not the fake's.
    assert abs(report["metrics"]["log_loss"] - report["baseline"]["log_loss"]) < 0.15


def test_the_satisfaction_anchors_are_a_pinned_version_and_the_report_names_everything():
    report = validate_mapping(
        synthetic_reviews(50, seed=7), FakeEmbed(dim=8), seed=7,
        epsilon=0.5, temperature=2.0, anchor_hash_pinned=SATISFACTION_HASH, **BASE,
    )
    assert (report["anchor_set_id"], report["anchor_version"], report["anchor_hash"]) == (
        "satisfaction-v1", "v1", SATISFACTION_HASH,
    )
    assert report["served_embedding_model"] == ["fake-embed"]
    assert (report["epsilon"], report["temperature"]) == (0.5, 2.0)
    assert (report["sample_size"], report["seed"]) == (50, 7)
    assert report["dataset"]["location"] and report["dataset"]["terms"]
    with pytest.raises(ValueError, match="changed since pinning"):
        validate_mapping(synthetic_reviews(10, seed=1), FakeEmbed(dim=8), anchor_hash_pinned="00" * 32, **BASE)


def test_a_fake_scoring_identical_text_identically_is_deterministic_in_ci():
    first = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8), seed=7, **BASE)
    second = validate_mapping(synthetic_reviews(100, seed=7), FakeEmbed(dim=8), seed=7, **BASE)
    assert first["metrics"] == second["metrics"]


def test_the_gateway_guide_serves_titan_embeddings_through_litellm():
    guide = (Path(__file__).resolve().parents[3] / "docs" / "inference.md").read_text()
    assert "titan-embed-text-v2" in guide.lower() or "titan text embeddings v2" in guide.lower()
    assert "litellm" in guide.lower()
