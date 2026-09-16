"""The paper's SSR computation, ported with attribution.

Reference: `pymc-labs/semantic-similarity-rating` (Apache-2.0), the implementation published by the
authors of arXiv 2510.08338 ("Semantic Similarity Rating: A Collaborative Approach for AI-Assisted
Survey Rating"). Licensed under the Apache License, Version 2.0 — see http://www.apache.org/licenses/LICENSE-2.0.

The port covers the scoring arithmetic from `compute.py` only: similarity `gamma = (1 + cosine) / 2`
over normalised vectors; per anchor set, subtract the least similar anchor's similarity and
normalise, `p_i = (gamma_i - gamma_min + eps * [i is the least similar]) / (sum(gamma) - 5 * gamma_min + eps)`;
average the per-set distributions across sets; then apply temperature once, `p ** (1 / T)`,
renormalised, one-hot at the maximum when T = 0. The reference package's embedding runner
(`response_rater.py`, via `sentence-transformers`) is deliberately not ported: embeddings arrive
through the single pinned endpoint (ADR 0021). No dependency on the reference package.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def similarities(response: Sequence[float], anchors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Per-anchor similarity `gamma = (1 + cosine) / 2` over normalised vectors, one value per anchor."""
    normed_response = _normalised(response)
    return tuple((1.0 + _cosine(normed_response, _normalised(anchor))) / 2.0 for anchor in anchors)


def per_set_distribution(gammas: Sequence[float], epsilon: float = 0.0) -> tuple[float, ...]:
    """One set's distribution: subtract the least similar anchor's similarity, normalise with epsilon.

    With epsilon = 0 the least similar anchor receives exactly zero; epsilon adds to the least
    similar anchor and to the denominator exactly as the reference does.
    """
    values = tuple(float(gamma) for gamma in gammas)
    if len(values) != 5:
        raise ValueError(f"an anchor set holds five statements, got {len(values)} similarities")
    if epsilon < 0.0:
        raise ValueError(f"epsilon must be non-negative, got {epsilon}")
    least = min(range(5), key=lambda index: values[index])
    gamma_min = values[least]
    denominator = sum(values) - 5.0 * gamma_min + epsilon
    if denominator <= 0.0:
        return (0.2, 0.2, 0.2, 0.2, 0.2)
    return tuple(
        ((value - gamma_min + (epsilon if index == least else 0.0)) / denominator) for index, value in enumerate(values)
    )


def aggregate(distributions: Sequence[Sequence[float]], temperature: float = 1.0) -> tuple[float, ...]:
    """Headline distribution: the mean across sets, then temperature applied once afterwards.

    Zero temperature gives a one-hot at the most likely point; a uniform mean passes through unchanged.
    """
    sets = tuple(tuple(float(value) for value in mass) for mass in distributions)
    if not sets:
        raise ValueError("at least one anchor set is needed to aggregate")
    mean = [sum(mass[point] for mass in sets) / len(sets) for point in range(5)]
    if temperature == 0.0:
        if all(value == mean[0] for value in mean):
            return (0.2, 0.2, 0.2, 0.2, 0.2)
        top = max(range(5), key=lambda point: mean[point])
        return tuple(1.0 if point == top else 0.0 for point in range(5))
    if temperature < 0.0:
        raise ValueError(f"temperature must be non-negative, got {temperature}")
    if temperature == 1.0:
        return (mean[0], mean[1], mean[2], mean[3], mean[4])
    shaped = [value ** (1.0 / temperature) if value > 0 else 0.0 for value in mean]
    total = sum(shaped)
    if total <= 0.0:
        return (0.2, 0.2, 0.2, 0.2, 0.2)
    return (shaped[0] / total, shaped[1] / total, shaped[2] / total, shaped[3] / total, shaped[4] / total)


def _normalised(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if norm == 0.0:
        return tuple(0.0 for _ in vector)
    return tuple(float(value) / norm for value in vector)


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != len(second):
        raise ValueError(f"cosine needs equal-length vectors, got {len(first)} and {len(second)}")
    value = sum(a * b for a, b in zip(first, second))
    return max(-1.0, min(1.0, value))
