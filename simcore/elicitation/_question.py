"""The elicitation question: a versioned, hashed template per construct (Q7).

Based on the paper's *"How likely are you to purchase the product?"*, with an instruction to
answer briefly in the persona's own words and without numbers or ratings. `agent` includes the
template verbatim. A response carrying a rating-like number is a recorded elicitation failure
with no distribution — no code path scores a model-emitted rating."""

from __future__ import annotations

import hashlib
import re

TEMPLATES: dict[str, dict[str, str]] = {
    "purchase_intent": {
        "version": "v1",
        "text": (
            "How likely are you to purchase the product? "
            "Answer briefly in your own words, as yourself. "
            "Do not use numbers, ratings, scores, percentages, fractions, or stars."
        ),
    },
    "satisfaction": {
        "version": "v1",
        "text": (
            "How satisfied are you with the product? "
            "Answer briefly in your own words, as yourself. "
            "Do not use numbers, ratings, scores, percentages, fractions, or stars."
        ),
    },
}

# A rating is a structure, not a number: a score over a rating scale, a star count, a number given as a verdict,
# a stated certainty. A number that describes the product — 20% more protein, 50% off, a 3/4 litre bottle, a pack
# of 6, open 24/7 — is not a rating, and refusing it would discard the very reactions to claims a study tests.
# The first detector matched numbers: it scored "I'd give it a 4" and "four stars from me" as prose and refused
# "It has 20% more protein". Numbers are matched as digits or as words, since a model forbidden digits writes words.
_WORD_NUMBERS = r"zero|one|two|three|four|five|six|seven|eight|nine|ten"
_NUM = rf"(?:\d+(?:\.\d+)?|{_WORD_NUMBERS})"
_SMALL = rf"(?:\d{{1,2}}(?:\.\d)?|{_WORD_NUMBERS})"
# A number that measures something is not a verdict.
_UNIT = (
    r"(?:%|percent|per\s*cent|packs?|oz|ounces?|ml|millilit(?:re|er)s?|l\b|lit(?:re|er)s?|grams?|g\b|kg|cans?|bottles?|"
    r"servings?|times?|minutes?|mins?|hours?|days?|weeks?|months?|years?|dollars?|bucks|cents|euros?|pounds?|calories|"
    r"kcal|pieces?|items?|flavou?rs?|people|kids|scoops?|shakes?|-)"
)
_RATING_PATTERNS = (
    # a score over a rating scale: 4/5, 8 out of 10, eight out of ten, 10/10, 4.5/5 — not 3/4, 1/2 or 24/7
    re.compile(rf"\b{_NUM}\s*(?:/|out\s+of|outta)\s*(?:5|10|100|five|ten|hundred)\b(?!\s*\d)", re.IGNORECASE),
    # a star count, in digits, words or symbols
    re.compile(rf"\b{_NUM}\s*-?\s*stars?\b", re.IGNORECASE),
    re.compile(r"[★☆⭐✦✧⭑]"),
    # a named scale: on a scale of one to five
    re.compile(rf"\bscale\s+(?:of|from)\s+{_NUM}\s*(?:to|-)\s*{_NUM}", re.IGNORECASE),
    # a number given as a verdict: rate it 4, rated 4, give it a 4, score it an 8, my score is 5, Rating: 3
    re.compile(
        rf"\b(?:rate|rated|rating|grade|graded|score|scored|give|giving|gave)\s*[:=]?\s+(?:it|this|them|the\s+product)?\s*"
        rf"(?:(?:is|was|would\s+be|of)\s+)?(?:an?\s+)?(?:solid|strong|firm|good|decent|weak|low|high|generous|clear)?\s*"
        rf"{_SMALL}\b(?!\s*{_UNIT})",
        re.IGNORECASE,
    ),
    # a bare verdict: a 7 for me, a 3 at best, definitely a five.
    re.compile(
        rf"\ban?\s+(?:solid|strong|firm|good|decent|weak|low|high|generous|clear)?\s*{_SMALL}\b(?!\s*{_UNIT})"
        rf"(?=\s*(?:for\s+me|from\s+me|at\s+best|at\s+most|overall|tops|max|[.!?,;]|$))",
        re.IGNORECASE,
    ),
    # a stated certainty: 80 percent sure, 90% likely, a 70% chance
    re.compile(rf"\b\d{{1,3}}\s*(?:%|percent|per\s*cent)\s+(?:sure|likely|certain|confident|chance|probability)\b", re.IGNORECASE),
    re.compile(r"\b(?:chance|probability|likelihood|odds)\s+(?:of\s+|is\s+|are\s+)?(?:about\s+|around\s+|maybe\s+)?\d{1,3}\s*(?:%|percent)", re.IGNORECASE),
    # an answer that is nothing but a percentage
    re.compile(r"^\W*\d{1,3}\s*(?:%|percent)\W*$", re.IGNORECASE),
)


def question_text(construct: str) -> str:
    try:
        return TEMPLATES[construct]["text"]
    except KeyError:
        raise ValueError(f"no elicitation question for construct {construct!r}") from None


def question_version(construct: str) -> str:
    try:
        return TEMPLATES[construct]["version"]
    except KeyError:
        raise ValueError(f"no elicitation question for construct {construct!r}") from None


def question_hash(construct: str) -> str:
    """A template's identity: the sha256 of its text."""
    return hashlib.sha256(question_text(construct).encode("utf-8")).hexdigest()


def is_numeric_answer(text: str) -> bool:
    """Whether a response gives a rating — a score over a scale, a star count, a number offered as a verdict or a
    stated certainty — rather than prose that merely mentions a number. A price, a pack size, a year, a percentage
    describing the product and a fraction of a bottle are not ratings and score normally."""
    return any(pattern.search(text) for pattern in _RATING_PATTERNS)
