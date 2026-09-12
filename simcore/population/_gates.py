"""Distribution gates: chi-squared on categorical marginals, KS similarity on ordinal bands.

A gate compares what the sample drew against what the study's own design implies — the share-weighted
mixture of each audience's eligible pool — not against the corpus. An audience exists to be
unrepresentative of the corpus, so gating against the corpus would reject every targeted study for
doing exactly what it was asked to do. What a pass does *not* mean is that the sample matches the
real world: that needs external category targets, which the engine does not yet have (§12).

`scipy` supplies the chi-squared survival function; hand-rolling a tail approximation in the part of
the engine that exists to catch silent error is not a saving."""

from collections.abc import Sequence

import numpy as np
from scipy import stats

from simcore.schemas import AttributeValue


def counts_of(values: Sequence[AttributeValue], vocabulary: Sequence[AttributeValue]) -> np.ndarray:
    index = {value: position for position, value in enumerate(vocabulary)}
    counts = np.zeros(len(vocabulary), dtype=float)
    for value in values:
        position = index.get(value)
        if position is not None:
            counts[position] += 1.0
    return counts


def chi_squared(sample: Sequence[AttributeValue], expected: np.ndarray, vocabulary: Sequence[AttributeValue]):
    """The chi-squared statistic, its degrees of freedom and its p-value, or nothing when the
    expectation carries no mass or fewer than two categories survive it."""
    observed = counts_of(sample, vocabulary)
    if observed.sum() == 0 or expected.sum() == 0:
        return None
    scaled = expected / expected.sum() * observed.sum()
    keep = scaled > 0
    observed, scaled = observed[keep], scaled[keep]
    if len(observed) < 2:
        return None
    result = stats.chisquare(observed, scaled)
    return float(result.statistic), int(len(observed) - 1), float(result.pvalue)


def ordinal_similarity(sample: Sequence[AttributeValue], expected: np.ndarray, vocabulary: Sequence[AttributeValue]):
    """The KS statistic between the drawn and expected distributions over the declared band order,
    and its similarity — named for direction, so a threshold on it reads the way it means."""
    observed = counts_of(sample, vocabulary)
    if observed.sum() == 0 or expected.sum() == 0:
        return None
    sample_cdf = np.cumsum(observed) / observed.sum()
    expected_cdf = np.cumsum(expected) / expected.sum()
    statistic = float(np.max(np.abs(sample_cdf - expected_cdf)))
    return statistic, 1.0 - statistic
