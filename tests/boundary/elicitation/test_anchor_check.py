"""Phase 7: the anchor check gate a version must pass before it can be pinned."""

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from simcore.elicitation import (
    LADDER,
    VARIED,
    anchor_hash,
    assert_pinnable,
    check_anchors,
    load_anchor_version,
    read_check_record,
)

ANCHORS_DIR = Path(__file__).resolve().parents[3] / "anchors"

LADDER_LEVELS = [1.0, 1.8, 2.4, 3.0, 3.6, 4.2, 5.0]
VARIED_LEVELS = [1, 1, 3, 4, 5]

FROZEN_LADDER = (
    "I would never buy this, no chance at all.",
    "I probably would not buy this.",
    "I might or might not buy this, still deciding.",
    "I lean a little toward buying this.",
    "I probably would buy this.",
    "I will very likely buy this.",
    "I would definitely buy this, certainly.",
)


class LexiconEmbed:
    """Vectors by sentiment level: level k sits at angle (k-1)*0.25 on the unit circle."""

    def __init__(self, levels: dict[str, int], model_id: str = "lexicon/v1"):
        self.levels = levels
        self.model_id = model_id

    def embed(self, texts):
        from simcore.ports.embed import EmbedResult

        vectors = np.asarray([self._vector(text) for text in texts], dtype=np.float32)
        return EmbedResult(
            vectors=vectors, model_id=self.model_id, served_model_id=self.model_id,
            normalization="unit-circle", dim=2, costs=(),
        )

    def _vector(self, text: str) -> list[float]:
        level = self.levels[text]
        angle = (level - 1) * 0.25
        return [math.cos(angle), math.sin(angle)]


def _levels_for(anchors_dir: Path) -> dict[str, int]:
    parsed = load_anchor_version(anchors_dir / "purchase_intent" / "v1.json")
    levels = {}
    for anchor_set in parsed.sets:
        for position, statement in enumerate(anchor_set):
            levels[statement] = position + 1
    for text, level in zip(LADDER, LADDER_LEVELS):
        levels[text] = level
    for text, level in zip(VARIED, VARIED_LEVELS):
        levels[text] = level
    return levels


@pytest.fixture()
def staged(tmp_path: Path) -> Path:
    staged = tmp_path / "anchors"
    shutil.copytree(ANCHORS_DIR, staged)
    return staged


def test_the_ladder_is_frozen():
    assert tuple(LADDER) == FROZEN_LADDER


def test_each_construct_is_checked_on_a_ladder_worded_in_its_own_construct():
    from simcore.elicitation import ladder_for, varied_for

    purchase, satisfaction = ladder_for("purchase_intent"), ladder_for("satisfaction")
    assert tuple(purchase) == FROZEN_LADDER
    assert len(satisfaction) == len(purchase) == 7
    assert satisfaction != purchase
    assert any("satisf" in rung for rung in satisfaction)
    assert not any("buy" in rung for rung in satisfaction)
    assert len(varied_for("satisfaction")) == len(varied_for("purchase_intent")) == 5
    with pytest.raises(ValueError, match="no frozen ladder"):
        ladder_for("brand_trust")


def test_the_satisfaction_check_embeds_the_satisfaction_ladder_not_the_purchase_one(staged: Path):
    from simcore.elicitation import check_anchors, ladder_for

    seen: list[str] = []

    class SpyEmbed(LexiconEmbed):
        def embed(self, texts):
            seen.extend(list(texts))
            levels = dict(self.levels)
            for text in texts:
                levels.setdefault(text, 3)
            return LexiconEmbed(levels, self.model_id).embed(texts)

    levels = _levels_for(staged)
    for rung in ladder_for("satisfaction"):
        levels.setdefault(rung, 3)
    for text in VARIED:
        levels.setdefault(text, 3)
    from simcore.elicitation import VARIED as PURCHASE_VARIED

    for text in PURCHASE_VARIED:
        levels.setdefault(text, 3)
    check_anchors("satisfaction-v1", "satisfaction", "v1", SpyEmbed(levels), staged, write_record=False)
    for rung in ladder_for("satisfaction"):
        assert rung in seen
    for rung in LADDER:
        assert rung not in seen


def test_a_frozen_ladder_scores_in_strictly_increasing_expected_rating(staged: Path):
    result = check_anchors("purchase-intent-v1", "purchase_intent", "v1", LexiconEmbed(_levels_for(staged)), staged)
    assert result.passed
    assert all(later > earlier for earlier, later in zip(result.expected_ratings, result.expected_ratings[1:]))


def test_rank_order_is_stable_across_sets_and_varied_responses_do_not_collapse(staged: Path):
    result = check_anchors("purchase-intent-v1", "purchase_intent", "v1", LexiconEmbed(_levels_for(staged)), staged)
    assert result.spearman_min > 0.8
    assert result.collapse_distance > 0.1


def _break(staged: Path, mode: str) -> dict[str, int]:
    raw = json.loads((staged / "purchase_intent" / "v1.json").read_text())
    if mode == "reversed":
        raw["sets"] = [list(reversed(anchor_set)) for anchor_set in raw["sets"]]
    elif mode == "one_set_reversed":
        raw["sets"] = [list(reversed(raw["sets"][0])), *raw["sets"][1:]]
    elif mode == "duplicated":
        raw["sets"] = [[anchor_set[2]] * 5 for anchor_set in raw["sets"]]
    elif mode == "one_point":
        paraphrases = [
            "I would definitely buy this.",
            "Certainly I am buying it.",
            "Buying it for sure, no doubt.",
            "It is decided: I get this.",
            "Absolutely, this one is mine.",
        ]
        raw["sets"] = [list(paraphrases) for _ in raw["sets"]]
    else:
        raise AssertionError(mode)
    (staged / "purchase_intent" / "v1.json").write_text(json.dumps(raw, indent=2))
    levels: dict[str, int] = {}
    if mode in ("reversed", "one_set_reversed"):
        parsed_sets = raw["sets"]
        original = load_anchor_version(ANCHORS_DIR / "purchase_intent" / "v1.json")
        text_to_level = {}
        for anchor_set in original.sets:
            for position, statement in enumerate(anchor_set):
                text_to_level[statement] = position + 1
        for anchor_set in parsed_sets:
            for statement in anchor_set:
                levels[statement] = text_to_level[statement]
    elif mode == "duplicated":
        for anchor_set in raw["sets"]:
            for statement in anchor_set:
                levels[statement] = 3
    else:
        for anchor_set in raw["sets"]:
            for statement in anchor_set:
                levels[statement] = 5
    for text, level in zip(LADDER, LADDER_LEVELS):
        levels[text] = level
    for text, level in zip(VARIED, VARIED_LEVELS):
        levels[text] = level
    return levels


@pytest.mark.parametrize("mode", ["reversed", "duplicated", "one_point"])
def test_deliberately_broken_anchors_each_fail_the_check(staged: Path, mode: str):
    levels = _break(staged, mode)
    result = check_anchors(
        "purchase-intent-v1", "purchase_intent", "v1", LexiconEmbed(levels), staged, write_record=False
    )
    assert not result.passed, f"{mode} anchors passed: {result.detail}"


def test_the_result_records_version_hash_and_model_and_pin_refuses_without_it(staged: Path, tmp_path: Path):
    fresh = tmp_path / "bare"
    shutil.copytree(ANCHORS_DIR, fresh)
    for record in fresh.rglob("*.check.json"):
        record.unlink()  # a version never checked pins nothing, whatever the repo holds
    with pytest.raises(ValueError, match="no check result"):
        assert_pinnable("purchase-intent-v1", "purchase_intent", "v1", fresh)
    before = anchor_hash(load_anchor_version(staged / "purchase_intent" / "v1.json"))
    result = check_anchors("purchase-intent-v1", "purchase_intent", "v1", LexiconEmbed(_levels_for(staged)), staged)
    assert (result.anchor_set_id, result.version, result.anchor_hash) == ("purchase-intent-v1", "v1", before)
    assert result.embed_model_id == "lexicon/v1"
    assert read_check_record(staged, "purchase_intent", "v1") == result
    assert assert_pinnable("purchase-intent-v1", "purchase_intent", "v1", staged) == result
    # Nothing in the check adjusts an anchor: the file is byte-identical afterwards.
    assert anchor_hash(load_anchor_version(staged / "purchase_intent" / "v1.json")) == before
    with pytest.raises(ValueError, match="cannot be pinned"):
        assert_pinnable("someone-else-v9", "purchase_intent", "v1", staged)


def test_a_failing_check_record_still_refuses_pinning(staged: Path):
    from simcore.elicitation import AnchorCheckResult, check_record_path

    record = AnchorCheckResult(
        anchor_set_id="purchase-intent-v1",
        construct="purchase_intent",
        version="v1",
        anchor_hash=anchor_hash(load_anchor_version(staged / "purchase_intent" / "v1.json")),
        embed_model_id="lexicon/v1",
        passed=False,
        expected_ratings=(3.0,) * 7,
        spearman_min=0.0,
        collapse_distance=0.0,
        detail="flat everywhere",
    )
    check_record_path(staged, "purchase_intent", "v1").write_text(record.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="failed its check"):
        assert_pinnable("purchase-intent-v1", "purchase_intent", "v1", staged)


def test_one_set_that_disagrees_with_the_rest_fails_on_rank_stability_alone(staged: Path):
    """Deleting the rank-stability requirement once left every test passing: each broken case also failed on the ladder
    or on collapse. Here five sets order the ladder and one reverses it, so the mean still rises and nothing collapses —
    only the disagreement between sets is wrong, and it alone must fail the check."""
    levels = _break(staged, "one_set_reversed")
    result = check_anchors("purchase-intent-v1", "purchase_intent", "v1", LexiconEmbed(levels), staged, write_record=False)
    assert all(later > earlier for earlier, later in zip(result.expected_ratings, result.expected_ratings[1:]))
    assert result.collapse_distance > 0.1
    assert result.spearman_min <= 0.8
    assert not result.passed and result.detail.startswith("rank stability")
