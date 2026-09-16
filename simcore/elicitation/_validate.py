"""The mapping validation: does SSR recover the rating a person gave from what they wrote.

A command draws a few hundred public human product reviews balanced across star ratings, embeds
them through the pinned model, scores SSR's distributions against the stars people gave — log
loss, Brier score and rank correlation of the expected rating — and reports them beside a
baseline that ignores the text. It uses the frozen satisfaction anchors, downloads the reviews
at run time and commits none (ADR 0028)."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._anchors import anchor_hash, load_anchor_version
from ._check import expected_rating, spearman
from ._score import clear_anchor_cache, score

SATISFACTION_CONSTRUCT = "satisfaction"

# Deterministic synthetic reviews for CI: templated wording per star, shuffled by seed. These are
# fixtures, not human data — a real run passes `--reviews` with downloaded human reviews.
_SYNTHETIC_TEMPLATES: dict[int, tuple[str, ...]] = {
    1: (
        "Terrible, broke within a day and support never answered.",
        "A complete waste, I regret buying it at all.",
        "Awful quality, fell apart on first use.",
        "Horrible, the worst purchase I made this year.",
        "Do not buy this, it never worked properly.",
    ),
    2: (
        "Disappointing, several flaws and poor finish.",
        "Below expectations, I would not buy it again.",
        "Mostly a letdown, only partly usable.",
        "Not great, the quality feels cheap throughout.",
        "Weak performance, I expected much better.",
    ),
    3: (
        "Acceptable, does the job without impressing.",
        "Average overall, fine for the price paid.",
        "Neither good nor bad, it simply works.",
        "Okay product, meets the basics and nothing more.",
        "Decent enough, with a few rough edges.",
    ),
    4: (
        "Quite pleased, works well and feels solid.",
        "Good quality, I would recommend it to friends.",
        "Happy with this, better than I expected.",
        "Reliable and pleasant to use every day.",
        "Strong performance with only minor quibbles.",
    ),
    5: (
        "Excellent, exceeded every expectation I had.",
        "Wonderful product, works flawlessly and fast.",
        "Absolutely love it, the best one I have owned.",
        "Perfect in every way, highly recommended.",
        "Outstanding quality, worth every penny spent.",
    ),
}


@dataclass(frozen=True)
class ReviewSample:
    texts: tuple[str, ...]
    stars: tuple[int, ...]
    location: str
    terms: str


def synthetic_reviews(sample_size: int, seed: int) -> ReviewSample:
    """A deterministic, star-balanced pseudo-sample for CI; never human ground truth."""
    rng = random.Random(seed)
    per_star, remainder = divmod(sample_size, 5)
    texts: list[str] = []
    stars: list[int] = []
    for star in (1, 2, 3, 4, 5):
        count = per_star + (1 if star <= remainder else 0)
        templates = _SYNTHETIC_TEMPLATES[star]
        for index in range(count):
            texts.append(f"{rng.choice(templates)} (variant {index % 7})")
            stars.append(star)
    order = list(range(len(texts)))
    rng.shuffle(order)
    return ReviewSample(
        texts=tuple(texts[index] for index in order),
        stars=tuple(stars[index] for index in order),
        location="synthetic",
        terms="generated fixtures for CI; no human data, measures plumbing not the mapping claim",
    )


def reviews_from_jsonl(path: str | Path, *, seed: int) -> ReviewSample:
    """Human reviews downloaded at run time and never committed: one JSON object per line with
    `text` and `stars` (1–5). Balanced across stars from the seed, so the report is reproducible."""
    rng = random.Random(seed)
    by_star: dict[int, list[str]] = {star: [] for star in (1, 2, 3, 4, 5)}
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            stars = int(record["stars"])
            text = str(record["text"])
            if stars not in by_star or not text.strip():
                raise ValueError(f"{path}:{line_number}: needs a non-empty text and stars 1–5")
            by_star[stars].append(text)
    quota = min(len(texts) for texts in by_star.values())
    if quota == 0:
        raise ValueError(f"{path}: no reviews for every star rating, cannot balance")
    texts, stars = [], []
    for star in (1, 2, 3, 4, 5):
        picked = rng.sample(by_star[star], quota)
        texts.extend(picked)
        stars.extend([star] * quota)
    order = list(range(len(texts)))
    rng.shuffle(order)
    return ReviewSample(
        texts=tuple(texts[index] for index in order),
        stars=tuple(stars[index] for index in order),
        location=str(path),
        terms="human reviews downloaded at run time; see the evaluation report for the dataset and its terms",
    )


def _log_loss(masses: list[tuple[float, ...]], stars: list[int]) -> float:
    return sum(-math.log(max(mass[star - 1], 1e-12)) for mass, star in zip(masses, stars)) / len(masses)


def _brier(masses: list[tuple[float, ...]], stars: list[int]) -> float:
    total = 0.0
    for mass, star in zip(masses, stars):
        total += sum((value - (1.0 if point == star - 1 else 0.0)) ** 2 for point, value in enumerate(mass))
    return total / len(masses)


def validate_mapping(
    sample: ReviewSample,
    embed,
    anchors_dir: str | Path = "anchors",
    *,
    anchor_set_id: str = "satisfaction-v1",
    anchor_version: str = "v1",
    anchor_hash_pinned: str | None = None,
    epsilon: float = 0.0,
    temperature: float = 1.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Score the sample through SSR and report SSR beside a text-blind uniform baseline."""
    parsed = load_anchor_version(Path(anchors_dir) / SATISFACTION_CONSTRUCT / f"{anchor_version}.json")
    digest = anchor_hash(parsed)
    if anchor_hash_pinned is not None and digest != anchor_hash_pinned:
        raise ValueError("the satisfaction anchors changed since pinning: refusing to validate")
    clear_anchor_cache()
    outcomes = score(
        list(sample.texts),
        SATISFACTION_CONSTRUCT,
        category="reviews",
        anchor_set_id=anchor_set_id,
        anchor_version=anchor_version,
        embed=embed,
        anchors_dir=anchors_dir,
        pinned_hashes={anchor_set_id: digest},
        temperature=temperature,
        epsilon=epsilon,
    )
    masses: list[tuple[float, ...]] = []
    served: set[str] = set()
    for outcome in outcomes:
        if not hasattr(outcome, "pmf"):
            raise ValueError(f"a review failed to score ({outcome.kind.value}): {outcome.detail}")
        masses.append(tuple(outcome.pmf))
        served.add(outcome.embed_model_id)
    stars = list(sample.stars)
    uniform = [(0.2, 0.2, 0.2, 0.2, 0.2)] * len(stars)
    report = {
        "anchor_set_id": anchor_set_id,
        "anchor_version": anchor_version,
        "anchor_hash": digest,
        "served_embedding_model": sorted(served),
        "epsilon": epsilon,
        "temperature": temperature,
        "sample_size": len(stars),
        "seed": seed,
        "dataset": {"location": sample.location, "terms": sample.terms},
        "metrics": {
            "log_loss": _log_loss(masses, stars),
            "brier": _brier(masses, stars),
            "expected_rating_spearman": spearman([expected_rating(mass) for mass in masses], [float(star) for star in stars]),
        },
        "baseline": {
            "name": "uniform text-blind",
            "log_loss": _log_loss(uniform, stars),
            "brier": _brier(uniform, stars),
            "expected_rating_spearman": 0.0,
        },
        "note": (
            "The mapping claim only: whether SSR recovers the rating a person gave from what they "
            "wrote. It says nothing about whether simulated personas answer like real ones — the "
            "simulation claim is owed, and the trust level stays uncalibrated."
        ),
    }
    return report
