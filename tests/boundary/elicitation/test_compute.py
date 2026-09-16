"""Phase 3: the paper's formula as pure arithmetic, proven before anything layers on it."""

import math

import pytest

from simcore.elicitation import aggregate, per_set_distribution, similarities


def test_similarity_is_one_plus_cosine_over_two_on_normalised_vectors():
    assert similarities((2.0, 0.0), [(2.0, 0.0)]) == pytest.approx((1.0,))
    assert similarities((1.0, 0.0), [(-1.0, 0.0)]) == pytest.approx((0.0,))
    assert similarities((1.0, 0.0), [(0.0, 1.0)]) == pytest.approx((0.5,))
    # Scale carries no information: a longer vector scores like its unit version.
    assert similarities((10.0, 0.0), [(1.0, 0.0)]) == pytest.approx((1.0,))


def test_the_least_similar_anchor_gets_exactly_zero_and_each_set_sums_to_one():
    mass = per_set_distribution((0.9, 0.7, 0.8, 0.6, 0.75), epsilon=0.0)
    assert mass[3] == 0.0
    assert sum(mass) == pytest.approx(1.0)
    assert all(value >= 0.0 for value in mass)


def test_epsilon_adds_to_the_least_similar_anchor_and_the_denominator_as_the_reference():
    gammas = (0.9, 0.7, 0.8, 0.6, 0.75)
    least, total = min(gammas), sum(gammas)
    epsilon = 0.5
    expected = tuple(
        (gamma - least + (epsilon if gamma == least else 0.0)) / (total - 5 * least + epsilon) for gamma in gammas
    )
    assert per_set_distribution(gammas, epsilon=epsilon) == pytest.approx(expected)
    assert sum(per_set_distribution(gammas, epsilon=epsilon)) == pytest.approx(1.0)


def test_temperature_applies_once_after_the_mean_zero_is_one_hot_uniform_passes_through():
    first = (0.0, 0.0, 0.0, 0.0, 1.0)
    second = (0.0, 0.0, 0.0, 0.2, 0.8)
    assert aggregate([first, second], temperature=1.0) == pytest.approx((0.0, 0.0, 0.0, 0.1, 0.9))
    assert aggregate([first, second], temperature=0.0) == pytest.approx((0.0, 0.0, 0.0, 0.0, 1.0))
    uniform = (0.2, 0.2, 0.2, 0.2, 0.2)
    assert aggregate([uniform, uniform], temperature=2.0) == pytest.approx(uniform)
    assert aggregate([uniform, uniform], temperature=0.0) == pytest.approx(uniform)
    # Temperature widens monotonically: a cooler headline concentrates on the leader.
    cool = aggregate([first, second], temperature=0.5)
    assert cool[4] > 0.9 > aggregate([first, second], temperature=2.0)[4]


def test_the_port_reproduces_the_reference_implementation_known_answers():
    # Hand-worked through the reference formula: gammas (0.8, 0.6, 0.7, 0.5, 0.9), epsilon 0.
    # Least is 0.5; denominator 3.5 - 2.5 = 1.0; distribution (0.3, 0.1, 0.2, 0.0, 0.4).
    assert per_set_distribution((0.8, 0.6, 0.7, 0.5, 0.9)) == pytest.approx((0.3, 0.1, 0.2, 0.0, 0.4))
    # Two identical sets aggregate to themselves at temperature 1.
    assert aggregate([(0.3, 0.1, 0.2, 0.0, 0.4)] * 2) == pytest.approx((0.3, 0.1, 0.2, 0.0, 0.4))
    # Cosine hand-check: 45 degrees gives (1 + sqrt(2)/2) / 2.
    assert similarities((1.0, 0.0), [(1.0, 1.0)])[0] == pytest.approx((1.0 + math.sqrt(2) / 2) / 2)


def test_the_source_carries_the_reference_attribution_and_licence_notice():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "simcore" / "elicitation" / "_compute.py").read_text()
    assert "pymc-labs/semantic-similarity-rating" in source
    assert "Apache License" in source
    assert "sentence-transformers" in source
