"""Distribution gates: chi-squared on categorical marginals, KS similarity on ordinal bands.

A gate compares what the sample drew against the source population it was drawn from, so a sample
skewed by the conditioning filter or by a relaxation is visible as a verdict rather than a hidden
property. `scipy` supplies the chi-squared survival function; hand-rolling a tail approximation in
the part of the engine that exists to catch silent error is not a saving."""

from collections.abc import Sequence

import numpy as np
from scipy import stats

from simcore.schemas import AttributeValue


def _counts(values: Sequence[AttributeValue], vocabulary: Sequence[AttributeValue]) -> np.ndarray:
    index = {value: position for position, value in enumerate(vocabulary)}
    counts = np.zeros(len(vocabulary), dtype=float)
    for value in values:
        position = index.get(value)
        if position is not None:
            counts[position] += 1.0
    return counts


def chi_squared(sample: Sequence[AttributeValue], population: Sequence[AttributeValue], vocabulary: Sequence[AttributeValue]):
    """The chi-squared statistic, its degrees of freedom and its p-value, or nothing when a category
    has no expected count or fewer than two categories carry the attribute."""
    observed = _counts(sample, vocabulary)
    expected = _counts(population, vocabulary)
    if observed.sum() == 0 or expected.sum() == 0:
        return None
    scaled = expected / expected.sum() * observed.sum()
    keep = scaled > 0
    observed, scaled = observed[keep], scaled[keep]
    if len(observed) < 2:
        return None
    result = stats.chisquare(observed, scaled)
    return float(result.statistic), int(len(observed) - 1), float(result.pvalue)


def ordinal_similarity(sample: Sequence[AttributeValue], population: Sequence[AttributeValue], vocabulary: Sequence[AttributeValue]):
    """The two-sample KS statistic over the declared band order and its similarity, or nothing."""
    observed = _counts(sample, vocabulary)
    expected = _counts(population, vocabulary)
    if observed.sum() == 0 or expected.sum() == 0:
        return None
    sample_cdf = np.cumsum(observed) / observed.sum()
    population_cdf = np.cumsum(expected) / expected.sum()
    statistic = float(np.max(np.abs(sample_cdf - population_cdf)))
    return statistic, 1.0 - statistic
