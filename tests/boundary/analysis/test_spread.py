"""Phase 3: a scenario's worlds gathered with the spread between them."""

import math

import pytest

from simcore.analysis import spread
from simcore.schemas import OutcomeDigest, Scenario, canonical_hash
from tests.study_builders import digest_payload, scenario_payload, world_id_for


def _digest(adoption: float, scenario: dict | None = None, **overrides):
    scenario = scenario or scenario_payload()
    low = round((1.0 - adoption) / 3, 4)
    pmf = (low, low, round(1.0 - adoption - 2 * low, 4), round(adoption / 2, 4), round(adoption / 2, 4))
    base = digest_payload(scenario, audience_pmfs={"gym_regulars": pmf, "protein_dieters": pmf},
                          audience_shares={"gym_regulars": 0.6, "protein_dieters": 0.4},
                          community_pmfs={}, community_sizes={})
    base.update(overrides)
    return OutcomeDigest.model_validate(base)


def test_scenario_digests_aggregate_with_each_seed_and_hand_worked_spread():
    scenario = scenario_payload()
    world_a, world_b = world_id_for(scenario, 4021), world_id_for(scenario, 917731)
    summary = spread([(4021, world_a, _digest(0.5, scenario)), (917731, world_b, _digest(0.7, scenario))])
    assert [entry.seed for entry in summary.entries] == [4021, 917731]
    assert [entry.digest.adoption for entry in summary.entries] == pytest.approx([0.5, 0.7])
    assert summary.adoption_spread == pytest.approx(math.sqrt(((0.5 - 0.6) ** 2 + (0.7 - 0.6) ** 2) / 2))
    # Between worlds, never within one: each digest's own divergence is untouched.
    assert summary.divergence_spread == pytest.approx(0.0)


def test_one_seed_yields_a_spread_of_zero_rather_than_omitted():
    scenario = scenario_payload()
    summary = spread([(4021, world_id_for(scenario, 4021), _digest(0.5, scenario))])
    assert summary.adoption_spread == 0.0
    assert summary.adoption_spread is not None


def test_digests_from_different_scenarios_or_tick_units_refused():
    scenario = scenario_payload()
    other = scenario_payload(variant={"variant_id": "v2premium", "name": "Premium", "description": "At a higher price"})
    with pytest.raises(ValueError, match="one scenario"):
        spread([(4021, world_id_for(scenario, 4021), _digest(0.5, scenario)),
                (917731, world_id_for(other, 917731), _digest(0.5, other))])
    weekly = OutcomeDigest.model_validate(digest_payload(scenario, tick_unit="week"))
    daily = _digest(0.5, scenario)
    with pytest.raises(ValueError, match="not comparable"):
        spread([(4021, world_id_for(scenario, 4021), daily),
                (917731, world_id_for(scenario, 917731), weekly)])


def test_cell_with_worlds_at_different_rungs_is_marked():
    scenario = scenario_payload()
    clean = _digest(0.5, scenario)
    degraded = _digest(0.5, scenario, rungs=["warn"])
    summary = spread([(4021, world_id_for(scenario, 4021), clean),
                      (917731, world_id_for(scenario, 917731), degraded)])
    assert summary.rung_mixed is True
    even = spread([(4021, world_id_for(scenario, 4021), clean),
                   (917731, world_id_for(scenario, 917731), _digest(0.5, scenario))])
    assert even.rung_mixed is False


def test_scenario_hash_is_the_scenario_digested():
    scenario = scenario_payload()
    summary = spread([(4021, world_id_for(scenario, 4021), _digest(0.5, scenario))])
    assert summary.scenario_hash == canonical_hash(Scenario.model_validate(scenario))
