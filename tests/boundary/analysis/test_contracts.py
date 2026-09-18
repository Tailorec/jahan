"""Phase 1 contracts: a digest with no intent is valid and unmeasured, with its reason."""

import pytest
from pydantic import ValidationError

from simcore.schemas import OutcomeDigest, ScenarioSummary, ScenarioWorldEntry, canonical_hash
from simcore.schemas import Scenario as ScenarioModel
from tests.study_builders import digest_payload, scenario_payload, ulid, world_id_for


def _unmeasured(**overrides):
    base = digest_payload(
        audience_pmfs={},
        audience_shares={},
        community_pmfs={},
        community_sizes={},
        unmeasured_reason="no anchor version is pinned, so no turn was scored",
        unscored_turns=3,
        turn_count=3,
        action_mix={"comment": 2, "like": 1},
        belief_movement_mean={"value": 0.05, "fit": -0.02, "trust": 0.0},
        belief_movement_abs={"value": 0.08, "fit": 0.04, "trust": 0.01},
        wom_deliveries=2,
        wom_reach=2,
    )
    base.update(overrides)
    return base


def test_digest_validates_with_no_masses_and_reports_unmeasured():
    digest = OutcomeDigest.model_validate(_unmeasured())
    assert digest.adoption is None
    assert digest.polarization is None
    assert digest.audience_divergence is None
    assert digest.unscored_turns == 3


def test_digest_with_masses_computes_adoption_and_refuses_a_contradiction():
    digest = OutcomeDigest.model_validate(digest_payload())
    assert digest.adoption == pytest.approx(0.6 * (0.30 + 0.35) + 0.4 * (0.25 + 0.15))
    with pytest.raises(ValidationError, match="computed"):
        OutcomeDigest.model_validate({**digest_payload(), "adoption": 0.99})


def test_unmeasured_adoption_without_a_reason_refused_and_measured_with_one_refused():
    bad = _unmeasured()
    del bad["unmeasured_reason"]
    with pytest.raises(ValidationError, match="not measurable, with the reason"):
        OutcomeDigest.model_validate(bad)
    with pytest.raises(ValidationError, match="names no unmeasured reason"):
        OutcomeDigest.model_validate(digest_payload(unmeasured_reason="extra"))


def test_digest_carries_action_mix_belief_movement_and_wom_reach():
    digest = OutcomeDigest.model_validate(_unmeasured())
    assert digest.turn_count == 3
    assert sum(dict(digest.action_mix).values()) == 3
    assert set(digest.belief_movement_mean) == {"value", "fit", "trust"}
    assert digest.wom_deliveries == 2
    assert digest.wom_reach == 2
    with pytest.raises(ValidationError, match="counts"):
        OutcomeDigest.model_validate(_unmeasured(turn_count=5))


def _summary_payload():
    scenario = scenario_payload()
    digest_a = digest_payload()
    digest_b = digest_payload()
    return scenario, digest_a, digest_b


def test_scenario_summary_holds_one_entry_per_seed_with_spread():
    scenario = scenario_payload()
    scenario_hash = canonical_hash(ScenarioModel.model_validate(scenario))
    digest_a = OutcomeDigest.model_validate(digest_payload())
    digest_b = OutcomeDigest.model_validate(
        digest_payload(audience_pmfs={"gym_regulars": (0.9, 0.025, 0.025, 0.025, 0.025),
                                      "protein_dieters": (0.9, 0.025, 0.025, 0.025, 0.025)})
    )
    summary = ScenarioSummary.model_validate({
        "scenario_hash": scenario_hash,
        "tick_unit": "day",
        "entries": [
            {"seed": 4021, "world_id": world_id_for(scenario, 4021), "digest": digest_a.model_dump(mode="json")},
            {"seed": 917731, "world_id": world_id_for(scenario, 917731), "digest": digest_b.model_dump(mode="json")},
        ],
    })
    assert len(summary.entries) == 2
    assert summary.adoption_spread is not None and summary.adoption_spread > 0
    assert summary.rung_mixed is False
    assert ScenarioSummary.model_validate_json(summary.model_dump_json()) == summary


def test_scenario_summary_refuses_worlds_from_different_scenarios():
    scenario = scenario_payload()
    other = scenario_payload(variant={"variant_id": "v2premium", "name": "Premium", "description": "At a higher price"})
    scenario_hash = canonical_hash(ScenarioModel.model_validate(scenario))
    digest_other = OutcomeDigest.model_validate(digest_payload(other))
    with pytest.raises(ValidationError, match="not"):
        ScenarioSummary.model_validate({
            "scenario_hash": scenario_hash,
            "tick_unit": "day",
            "entries": [
                {"seed": 4021, "world_id": world_id_for(scenario, 4021),
                 "digest": OutcomeDigest.model_validate(digest_payload()).model_dump(mode="json")},
                {"seed": 917731, "world_id": world_id_for(other, 917731),
                 "digest": digest_other.model_dump(mode="json")},
            ],
        })
