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
from tests.boundary.elicitation.staging import FAKE_MODEL
from simcore.schemas import ElicitationFailure
from tests.boundary.elicitation.test_scoring import base  # noqa: F401 - the staged, passing anchor fixture


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
    [
        "4/5", "I give it 4/5 stars", "8 out of 10", "9 out of 10 stars", "90%", "★★★★", "☆☆☆☆", "rated 4", "my score is 5", "3 stars",
        # ratings the first detector scored as prose: numbers as verdicts, as words, and as stated certainty
        "I'd give it a 4.", "Honestly, a solid eight out of ten.", "Four stars from me.", "Definitely a five.", "Maybe a 7 for me.",
        "I'm about 80 percent sure I'd buy it.", "It's a 3 at best.", "On a scale of one to five, four.", "10/10 would buy",
        "Nine out of ten, would recommend.", "I'd score this one a 6.", "Gonna give it three stars.", "Two stars, not for me.",
        "Probably a 4 overall.", "A strong 9!", "I'm like 70% sure I'd pick it up.", "Rating: 3", "7/10", "I'd give this 5 out of 5.",
        "It deserves a 2.", "There's maybe a 60% chance I'd buy it.",
    ],
)
def test_rating_like_responses_are_numeric_answer_failures(rating, base):
    assert is_numeric_answer(rating) is True
    clear_anchor_cache()
    (outcome,) = score([rating], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    assert isinstance(outcome, ElicitationFailure) and outcome.kind.value == "numeric_answer"
    assert not hasattr(outcome, "pmf")


@pytest.mark.parametrize(
    "prose",
    [
        "It costs around twenty dollars and comes in a pack.",
        "I bought the 500g pack in 2024 after training.",
        "Twenty grams of protein with zero sugar sounds good.",
        "I would definitely buy this after my workout.",
        # product facts the first detector refused as ratings: percentages, discounts, fractions, hours, units
        "It has 20% more protein, so I'd probably buy it.", "Only 5% sugar, nice, I'd try it.", "At 50% off I'd grab a few.",
        "A 3/4 litre bottle is too small for me.", "Half price? 1/2 off and I'm in.", "The shop is open 24/7 so it's easy to get.",
        "I'd buy a pack of 6 for $3.99.", "I drink it 2-3 times a week, so yes.", "The 12 oz can scores points with me, I'd buy it.",
        "With 30g of protein per bottle I'd buy it.", "A 2 litre pack is too heavy to carry home.", "If it were 25% cheaper I'd buy it weekly.",
        "I'd grab two of them for the gym.", "I rate protein drinks highly when they taste good, so yes.", "Give it a few weeks and I'd switch.",
        "It's 100% plant based, which I like.", "I'd buy a four pack on the weekend.", "I give my kids one of these after football.",
        "Only 1 in 5 of my friends drinks these, but I'd try it.", "It scored well in my gym group's taste test, I'd buy it.",
    ],
)
def test_numbers_in_passing_are_scored(prose, base):
    assert is_numeric_answer(prose) is False
    clear_anchor_cache()
    (outcome,) = score([prose], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    assert hasattr(outcome, "pmf")


def test_no_code_path_in_the_module_accepts_a_model_stated_rating(base):
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
    outcomes = score(["4/5", "plain prose answer here"], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    assert isinstance(outcomes[0], ElicitationFailure) and hasattr(outcomes[1], "pmf")
