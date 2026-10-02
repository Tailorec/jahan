"""The anchor check: the gate a version must pass before it can be pinned (ADR 0027).

Needs no human data. A frozen ladder of graded responses must score in strictly increasing
expected rating; rank order must be stable across the six sets (Spearman above 0.8); varied
responses must not collapse to one distribution. The check runs against the embedding model the
version will be used with and records its result beside the version; pinning refuses a version
without a passing result. The ladder is frozen, and nothing here can adjust an anchor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._anchors import anchor_hash, load_anchor_version
from ._compute import aggregate, per_set_distribution, similarities

MIN_SPEARMAN = 0.8
MIN_COLLAPSE_DISTANCE = 0.1

# Frozen ladders, one per construct: graded responses from the bottom of the scale to the top.
# Frozen means frozen — a revision is a code change reviewed as one, never an adjustment to make a
# version pass. Each ladder is worded in its own construct: scoring buy-intent prose on satisfaction
# anchors cannot order by construction, so one ladder for every construct is a broken instrument.
LADDER: tuple[str, ...] = (
    "I would never buy this, no chance at all.",
    "I probably would not buy this.",
    "I might or might not buy this, still deciding.",
    "I lean a little toward buying this.",
    "I probably would buy this.",
    "I will very likely buy this.",
    "I would definitely buy this, certainly.",
)

SATISFACTION_LADDER: tuple[str, ...] = (
    "I am very dissatisfied with it, completely unhappy.",
    "I am somewhat dissatisfied with it.",
    "I feel neutral about it, neither good nor bad.",
    "It was acceptable, meeting my expectations on the whole.",
    "I am somewhat satisfied with it.",
    "I am very pleased with it.",
    "I am completely satisfied, it exceeded everything.",
)

LADDERS: dict[str, tuple[str, ...]] = {
    "purchase_intent": LADDER,
    "satisfaction": SATISFACTION_LADDER,
}

# Varied responses for the non-collapse check: different ratings, lengths and angles.
VARIED: tuple[str, ...] = (
    "I would never buy this.",
    "Not for me, I will pass.",
    "I might try it if a friend recommends it first.",
    "I probably would buy this after payday.",
    "I would definitely buy this, twice over, and tell everyone.",
)

SATISFACTION_VARIED: tuple[str, ...] = (
    "I am very dissatisfied with it.",
    "Not for me, a complete waste.",
    "It was fine, nothing special either way.",
    "I am quite pleased with it overall.",
    "I am thrilled with it and tell everyone.",
)

VARIED_SETS: dict[str, tuple[str, ...]] = {
    "purchase_intent": VARIED,
    "satisfaction": SATISFACTION_VARIED,
}


def ladder_for(construct: str) -> tuple[str, ...]:
    """The frozen ladder grading the construct under check; an unknown construct is refused."""
    try:
        return LADDERS[construct]
    except KeyError:
        raise ValueError(f"the anchor check has no frozen ladder for construct {construct!r}") from None


def varied_for(construct: str) -> tuple[str, ...]:
    try:
        return VARIED_SETS[construct]
    except KeyError:
        raise ValueError(f"the anchor check has no varied set for construct {construct!r}") from None


class AnchorCheckResult(BaseModel):
    """What the check found, recorded beside the anchor version it judged."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    anchor_set_id: str
    construct_id: str = Field(alias="construct")
    version: str
    anchor_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    embed_model_id: str
    # What the endpoint reported serving. Absent on records written before it was kept.
    served_model_id: str | None = None
    passed: bool
    expected_ratings: tuple[float, ...]
    spearman_min: float
    collapse_distance: float
    detail: str = ""

    @property
    def construct(self) -> str:
        return self.construct_id


def expected_rating(mass: Any) -> float:
    return sum((point + 1) * float(value) for point, value in enumerate(mass))


def spearman(first: Any, second: Any) -> float:
    """Rank correlation with tie-averaged ranks, no scipy needed."""
    rank_first, rank_second = _ranks(list(first)), _ranks(list(second))
    n = len(rank_first)
    if n < 2:
        return 1.0
    mean_first = sum(rank_first) / n
    mean_second = sum(rank_second) / n
    numerator = sum((a - mean_first) * (b - mean_second) for a, b in zip(rank_first, rank_second))
    denominator = (sum((a - mean_first) ** 2 for a in rank_first) * sum((b - mean_second) ** 2 for b in rank_second)) ** 0.5
    if denominator == 0.0:
        return 1.0 if numerator == 0.0 else 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    rank = 0
    while rank < len(order):
        tied = rank
        while tied + 1 < len(order) and values[order[tied + 1]] == values[order[rank]]:
            tied += 1
        average = (rank + tied) / 2.0 + 1.0
        for position in range(rank, tied + 1):
            ranks[order[position]] = average
        rank = tied + 1
    return ranks


def check_record_path(anchors_dir: str | Path, construct: str, version: str) -> Path:
    return Path(anchors_dir) / construct / f"{version}.check.json"


def check_anchors(
    anchor_set_id: str,
    construct: str,
    version: str,
    embed,
    anchors_dir: str | Path = "anchors",
    *,
    epsilon: float = 0.0,
    temperature: float = 1.0,
    write_record: bool = True,
) -> AnchorCheckResult:
    """Run the gate over one frozen version against the model it will be used with."""
    parsed = load_anchor_version(Path(anchors_dir) / construct / f"{version}.json")
    digest = anchor_hash(parsed)
    model_id = require_provider_model(embed.model_id)
    ladder = ladder_for(construct)
    varied = varied_for(construct)

    flat = [statement for anchor_set in parsed.sets for statement in anchor_set]
    anchor_result = embed.embed(flat)
    served_model_id = getattr(anchor_result, "served_model_id", None)
    anchor_vectors = np.asarray(anchor_result.vectors, dtype=np.float32).reshape(len(parsed.sets), 5, -1)
    ladder_vectors = np.asarray(embed.embed(list(ladder)).vectors, dtype=np.float32)
    varied_vectors = np.asarray(embed.embed(list(varied)).vectors, dtype=np.float32)

    per_set_expected: list[list[float]] = [[] for _ in parsed.sets]
    headline_expected: list[float] = []
    for row in range(len(ladder)):
        gammas = [tuple(similarities(ladder_vectors[row], anchor_vectors[set_index])) for set_index in range(len(parsed.sets))]
        per_set = [per_set_distribution(gamma, epsilon=epsilon) for gamma in gammas]
        for set_index, mass in enumerate(per_set):
            per_set_expected[set_index].append(expected_rating(mass))
        headline_expected.append(expected_rating(aggregate(per_set, temperature=temperature)))

    increasing = all(later > earlier for earlier, later in zip(headline_expected, headline_expected[1:]))
    correlations = [
        spearman(per_set_expected[first], per_set_expected[second])
        for first in range(len(parsed.sets))
        for second in range(first + 1, len(parsed.sets))
    ]
    spearman_min = min(correlations) if correlations else 1.0

    varied_headlines = []
    for row in range(len(varied)):
        gammas = [tuple(similarities(varied_vectors[row], anchor_vectors[set_index])) for set_index in range(len(parsed.sets))]
        per_set = [per_set_distribution(gamma, epsilon=epsilon) for gamma in gammas]
        varied_headlines.append(aggregate(per_set, temperature=temperature))
    collapse_distance = 0.0
    for first in range(len(varied_headlines)):
        for second in range(first + 1, len(varied_headlines)):
            distance = sum(abs(a - b) for a, b in zip(varied_headlines[first], varied_headlines[second])) / 2.0
            collapse_distance = max(collapse_distance, distance)

    reasons = []
    if not increasing:
        reasons.append("the ladder does not score in strictly increasing expected rating")
    if spearman_min <= MIN_SPEARMAN:
        reasons.append(f"rank stability {spearman_min:.3f} is not above {MIN_SPEARMAN}")
    if collapse_distance <= MIN_COLLAPSE_DISTANCE:
        reasons.append(f"varied responses collapse (max distance {collapse_distance:.3f})")
    result = AnchorCheckResult(
        anchor_set_id=anchor_set_id,
        construct=construct,
        version=version,
        anchor_hash=digest,
        embed_model_id=model_id,
        served_model_id=served_model_id,
        passed=not reasons,
        expected_ratings=tuple(headline_expected),
        spearman_min=spearman_min,
        collapse_distance=collapse_distance,
        detail="; ".join(reasons) if reasons else "ladder increasing, ranks stable, no collapse",
    )
    if write_record:
        check_record_path(anchors_dir, construct, version).write_text(result.model_dump_json(indent=2) + "\n")
    return result


def _tagged(model_id: str) -> bool:
    """`name:tag` with both parts present: Ollama's own id, the tag naming one build of the model."""
    name, sep, tag = model_id.partition(":")
    return bool(sep and name and tag)


def require_provider_model(model_id: str) -> str:
    """Refuse an embedding model named only by a gateway alias.

    A check result is evidence about one model. Titan's records once named the model `embed` — the name a LiteLLM
    proxy was given — so nothing in them said which model passed or failed, and pointing that alias at another
    model would have let the new model inherit the result. A provider's own identifier carries a `.` or a `/`
    (`amazon.titan-embed-text-v2:0`, `openai/text-embedding-3-small`), or a model and its build tag as Ollama
    names them (`qwen3-embedding:4b`); a bare name does not. This refuses the alias that happened; it cannot
    catch a qualified name deliberately pointed at another model."""
    if "." not in model_id and "/" not in model_id and not _tagged(model_id):
        raise ValueError(
            f"embedding model {model_id!r} names no provider, so a check result cannot say which model it judged; "
            "serve and pin the provider's own model id (e.g. amazon.titan-embed-text-v2:0) rather than a gateway alias"
        )
    return model_id


def read_check_record(anchors_dir: str | Path, construct: str, version: str) -> AnchorCheckResult | None:
    path = check_record_path(anchors_dir, construct, version)
    if not path.exists():
        return None
    try:
        return AnchorCheckResult.model_validate_json(path.read_text())
    except ValueError:
        return None


def assert_pinnable(
    anchor_set_id: str,
    construct: str,
    version: str,
    anchors_dir: str | Path = "anchors",
    *,
    embed_model_id: str | None = None,
) -> AnchorCheckResult:
    """Refuse pinning a version without a passing check result beside it."""
    record = read_check_record(anchors_dir, construct, version)
    if record is None:
        raise ValueError(f"anchor version {construct}/{version} has no check result: it cannot be pinned")
    if not record.passed:
        raise ValueError(f"anchor version {construct}/{version} failed its check ({record.detail}): it cannot be pinned")
    current = anchor_hash(load_anchor_version(Path(anchors_dir) / construct / f"{version}.json"))
    if record.anchor_hash != current:
        raise ValueError("the anchor file changed since its check passed: a changed statement is a new version")
    if record.anchor_set_id != anchor_set_id:
        raise ValueError(f"the check passed for {record.anchor_set_id!r}, not {anchor_set_id!r}: it cannot be pinned")
    require_provider_model(record.embed_model_id)
    if embed_model_id is not None and record.embed_model_id != require_provider_model(embed_model_id):
        raise ValueError(
            f"the check passed against {record.embed_model_id!r}, not {embed_model_id!r}: re-check on the new model"
        )
    return record
