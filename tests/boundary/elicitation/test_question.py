"""Phase 6: the question and numeric answers."""

import ast
from pathlib import Path

import pytest

from simcore.elicitation import (
    clear_anchor_cache,
    is_numeric_answer,
    question_hash,
    question_text,
    score,
)
from simcore.ports.fake import FakeEmbed
from simcore.schemas import ElicitationFailure
from tests.boundary.elicitation.test_scoring import ANCHORS_DIR, BASE, PINNED


def test_each_construct_has_a_versioned_question_identified_by_its_hash():
    for construct in ("purchase_intent", "satisfaction"):
        text = question_text(construct)
        assert text.strip()
        assert question_hash(construct) == __import__("hashlib").sha256(text.encode()).hexdigest()
    with pytest.raises(ValueError, match="no elicitation question"):
        question_text("brand_trust")


def test_the_purchase_intent_template_is_the_paper_question_without_numbers_or_ratings():
    text = question_text("purchase_intent").lower()
    assert "how likely are you to purchase the product" in text
    assert "own words" in text
    assert "number" in text and "rating" in text


@pytest.mark.parametrize(
    "rating",
    ["4/5", "I give it 4/5 stars", "8 out of 10", "9 out of 10 stars", "90%", "★★★★", "☆☆☆☆", "rated 4", "my score is 5", "3 stars"],
)
def test_rating_like_responses_are_numeric_answer_failures(rating):
    assert is_numeric_answer(rating) is True
    clear_anchor_cache()
    (outcome,) = score([rating], **BASE, embed=FakeEmbed(dim=8))
    assert isinstance(outcome, ElicitationFailure) and outcome.kind.value == "numeric_answer"
    assert not hasattr(outcome, "pmf")


@pytest.mark.parametrize(
    "prose",
    [
        "It costs around twenty dollars and comes in a pack.",
        "I bought the 500g pack in 2024 after training.",
        "Twenty grams of protein with zero sugar sounds good.",
        "I would definitely buy this after my workout.",
    ],
)
def test_numbers_in_passing_are_scored(prose):
    assert is_numeric_answer(prose) is False
    clear_anchor_cache()
    (outcome,) = score([prose], **BASE, embed=FakeEmbed(dim=8))
    assert hasattr(outcome, "pmf")


def test_no_code_path_in_the_module_accepts_a_model_stated_rating():
    root = Path(__file__).resolve().parents[3] / "simcore" / "elicitation"
    gate_found = False
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text())
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        if "is_numeric_answer" in {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}:
            gate_found = True
        if "SsrResult" in names or any(
            isinstance(node, ast.Name) and node.id == "SsrResult" for node in ast.walk(tree)
        ):
            assert "is_numeric_answer" in path.read_text(), f"{path.name} builds results without the numeric gate"
    assert gate_found
    clear_anchor_cache()
    outcomes = score(["4/5", "plain prose answer here"], **BASE, embed=FakeEmbed(dim=8))
    assert isinstance(outcomes[0], ElicitationFailure) and hasattr(outcomes[1], "pmf")
