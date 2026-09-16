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

_FRACTION = re.compile(r"\d\s*/\s*\d")
_OUT_OF = re.compile(r"\d\s+out\s+of\s+\d", re.IGNORECASE)
_PERCENT = re.compile(r"\d\s*%")
_UNICODE_STARS = re.compile(r"[★☆⭑✦✧]")
_STAR_WORDS = re.compile(r"\b\d\s*stars?\b", re.IGNORECASE)
_RATING_WORDS = re.compile(
    r"\b(rat(?:ing|ed|e)|score(?:d|s)?|stars?)\b[^.\n]{0,24}\d|\b\d[^.\n]{0,12}\b(ratings?|scores?|stars?)\b",
    re.IGNORECASE,
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
    """Whether a response carries a rating-like number: a fraction, an out-of, a percentage,
    a star count, or a digit tied to a rating word. Plain mentions — a price, a pack size,
    a year — are not ratings and score normally."""
    return bool(
        _FRACTION.search(text)
        or _OUT_OF.search(text)
        or _PERCENT.search(text)
        or _UNICODE_STARS.search(text)
        or _STAR_WORDS.search(text)
        or _RATING_WORDS.search(text)
    )
