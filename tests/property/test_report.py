import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from simcore.schemas import (
    MIN_DISTRIBUTION_SIMILARITY,
    MIN_RANK_ATTAINMENT,
    Anomaly,
    AnomalyKind,
    CalibrationRef,
    Confidence,
    Finding,
    FindingKind,
    ObjectionCluster,
    OutcomeDigest,
    Report,
    Scenario,
    TrustLevel,
    TrustStatement,
    canonical_hash,
    ensure_same_tick_unit,
)
from tests.study_builders import digest_payload, run_config_payload, scenario_payload, ulid

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = [f"ev-{ulid(1)}", f"ev-{ulid(2)}"]
NOW = datetime(2026, 9, 11, tzinfo=UTC)
BASELINE = scenario_payload()
PREMIUM = scenario_payload(variant={"variant_id": "v2premium", "name": "Premium", "description": "At a higher price"}, price={"amount": 2.99, "currency": "USD"})


def scenario_hash(scenario: dict) -> str:
    return canonical_hash(Scenario.model_validate(scenario))


def finding_payload(**overrides):
    payload = {
        "finding_id": "f-objection-01",
        "kind": "objection",
        "statement": "aftertaste is the recurring objection among gym regulars",
        "evidence_trace_ids": EVIDENCE,
        "disconfirming_test": "run 20 blind taste tests; if fewer than 30% mention aftertaste, the finding is wrong",
        "confidence": "medium",
    }
    payload.update(overrides)
    return payload


def ref_payload(**overrides):
    payload = {
        "benchmark_report_hash": "aa" * 32,
        "human_study_hash": "bb" * 32,
        "category": "beverage_protein",
        "distribution_similarity": 0.86,
        "rank_attainment": 0.83,
        "checked_at": NOW.isoformat(),
    }
    payload.update(overrides)
    return payload


def report_payload(**overrides):
    payload = {
        "config": run_config_payload(scenarios=[BASELINE, PREMIUM]),
        "trust": {"level": "uncalibrated", "caveats": ["engine has never been benchmarked"]},
        "findings": [
            finding_payload(),
            finding_payload(finding_id="f-ranking-01", kind="ranking", statement="baseline outperforms premium on adoption",
                            ranked_scenarios=[scenario_hash(BASELINE), scenario_hash(PREMIUM)]),
        ],
        "anomalies": [{"kind": "herding", "scenario_hash": scenario_hash(BASELINE), "tick": 12, "evidence_trace_ids": EVIDENCE[:1]}],
        "objection_clusters": [{"label": "aftertaste", "verbatim_trace_ids": EVIDENCE, "size": 14}],
        "digests": [digest_payload(BASELINE), digest_payload(PREMIUM)],
    }
    payload.update(overrides)
    return payload


# --- findings ---------------------------------------------------------------------------------


def test_finding_needs_supporting_records_and_a_disconfirming_test():
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(evidence_trace_ids=[]))
    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            Finding.model_validate(finding_payload(disconfirming_test=blank))


def test_finding_carries_only_what_varies_per_finding():
    assert not {"trust", "trust_level", "trust_tier", "provenance"} & set(Finding.model_fields)
    assert Finding.model_validate(finding_payload()).confidence is Confidence.MEDIUM
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(confidence=0.7))


def test_finding_kinds_include_rankings_and_risks():
    assert {k.value for k in FindingKind} == {"ranking", "risk", "objection", "belief_shift", "wom_path", "recommendation"}


def test_ranking_orders_at_least_two_distinct_scenarios_and_nothing_else_orders_any():
    ranked = [scenario_hash(BASELINE), scenario_hash(PREMIUM)]
    assert Finding.model_validate(finding_payload(kind="ranking", ranked_scenarios=ranked)).ranked_scenarios == tuple(ranked)
    for bad in ([ranked[0]], [ranked[0], ranked[0]], []):
        with pytest.raises(ValidationError, match="at least two distinct"):
            Finding.model_validate(finding_payload(kind="ranking", ranked_scenarios=bad))
    with pytest.raises(ValidationError, match="orders no scenarios"):
        Finding.model_validate(finding_payload(kind="risk", ranked_scenarios=ranked))


def test_finding_cites_each_record_once():
    with pytest.raises(ValidationError, match="more than once"):
        Finding.model_validate(finding_payload(evidence_trace_ids=[EVIDENCE[0], EVIDENCE[0]]))


# --- trust ------------------------------------------------------------------------------------


def test_uncalibrated_needs_no_reference_and_may_cite_a_benchmark_that_fell_short():
    assert TrustStatement(level=TrustLevel.UNCALIBRATED).calibration_ref is None
    short = TrustStatement.model_validate({"level": "uncalibrated", "calibration_ref": ref_payload(rank_attainment=0.4)})
    assert short.calibration_ref.meets_floors is False


def test_calibrated_levels_without_a_reference_refused():
    for level in ("category_benchmarked", "prospectively_validated"):
        with pytest.raises(ValidationError, match="requires a calibration reference"):
            TrustStatement.model_validate({"level": level})


@pytest.mark.parametrize("measurement", [{"distribution_similarity": 0.79}, {"rank_attainment": 0.5}], ids=["similarity", "attainment"])
def test_calibrated_levels_need_evidence_that_meets_the_floors(measurement):
    with pytest.raises(ValidationError, match="requires distribution similarity"):
        TrustStatement.model_validate({"level": "category_benchmarked", "calibration_ref": ref_payload(**measurement)})
    assert (MIN_DISTRIBUTION_SIMILARITY, MIN_RANK_ATTAINMENT) == (0.80, 0.80)


def test_a_bare_label_is_no_longer_enough_to_claim_calibration():
    with pytest.raises(ValidationError):
        CalibrationRef.model_validate({"benchmark": "made_up", "study_id": "none", "checked_at": NOW.isoformat()})
    assert {"benchmark_report_hash", "human_study_hash", "distribution_similarity", "rank_attainment"} <= set(CalibrationRef.model_fields)


def test_category_benchmark_meeting_the_floors_validates():
    trust = TrustStatement.model_validate({"level": "category_benchmarked", "calibration_ref": ref_payload()})
    assert trust.calibration_ref.meets_floors is True
    assert TrustStatement.model_validate_json(trust.model_dump_json()) == trust


def test_prospective_validation_needs_a_prediction_registered_before_its_outcome():
    with pytest.raises(ValidationError, match="registered before"):
        TrustStatement.model_validate({"level": "prospectively_validated", "calibration_ref": ref_payload()})
    prospective = ref_payload(prediction_registered_at=(NOW - timedelta(days=60)).isoformat(), outcome_observed_at=(NOW - timedelta(days=5)).isoformat())
    assert TrustStatement.model_validate({"level": "prospectively_validated", "calibration_ref": prospective}).calibration_ref.prospective
    backwards = ref_payload(prediction_registered_at=(NOW - timedelta(days=5)).isoformat(), outcome_observed_at=(NOW - timedelta(days=60)).isoformat())
    with pytest.raises(ValidationError, match="registered before its outcome"):
        CalibrationRef.model_validate(backwards)
    with pytest.raises(ValidationError, match="both"):
        CalibrationRef.model_validate(ref_payload(prediction_registered_at=(NOW - timedelta(days=60)).isoformat()))


def test_stated_floor_verdict_contradicting_the_measurements_refused():
    with pytest.raises(ValidationError, match="computed"):
        CalibrationRef.model_validate({**ref_payload(rank_attainment=0.4), "meets_floors": True})


def test_nothing_in_the_repository_produces_a_calibration_reference():
    producers = re.compile(r"(?<!class )\bCalibrationRef\s*(\(|\.model_validate|\.model_construct|\.model_copy)")
    offenders = [str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "simcore").rglob("*.py") if producers.search(path.read_text())]
    assert offenders == []


# --- anomalies, clusters, digests -------------------------------------------------------------


def test_anomaly_kinds_are_closed_and_evidence_is_required_once_each():
    assert {k.value for k in AnomalyKind} == {"herding", "backlash", "flop"}
    anomaly = {"kind": "herding", "scenario_hash": scenario_hash(BASELINE), "tick": 12, "evidence_trace_ids": EVIDENCE[:1]}
    assert Anomaly.model_validate(anomaly).kind is AnomalyKind.HERDING
    with pytest.raises(ValidationError):
        Anomaly.model_validate({**anomaly, "evidence_trace_ids": []})
    with pytest.raises(ValidationError, match="more than once"):
        Anomaly.model_validate({**anomaly, "evidence_trace_ids": [EVIDENCE[0], EVIDENCE[0]]})


def test_objection_cluster_is_at_least_as_large_as_the_distinct_sample_it_cites():
    assert ObjectionCluster(label="aftertaste", verbatim_trace_ids=EVIDENCE, size=14).size == 14
    with pytest.raises(ValidationError, match="cannot cite"):
        ObjectionCluster(label="aftertaste", verbatim_trace_ids=EVIDENCE, size=1)
    with pytest.raises(ValidationError, match="more than once"):
        ObjectionCluster(label="aftertaste", verbatim_trace_ids=[EVIDENCE[0], EVIDENCE[0]], size=5)


def test_digest_carries_both_distributions_with_their_weights():
    digest = OutcomeDigest.model_validate(digest_payload())
    assert set(digest.audience_pmfs) == set(digest.audience_shares) == {"gym_regulars", "protein_dieters"}
    assert set(digest.community_pmfs) == set(digest.community_sizes) == {"community-1", "community-2"}
    for overrides, match in (({"audience_shares": {"gym_regulars": 1.0}}, "needs a share"),
                             ({"community_sizes": {"community-1": 120}}, "needs a size"),
                             ({"audience_shares": {"gym_regulars": 0.5, "protein_dieters": 0.4}}, "sum to one"),
                             ({"audience_pmfs": {}, "audience_shares": {}, "community_pmfs": {},
                                "community_sizes": {}}, "not measurable, with the reason")):
        with pytest.raises(ValidationError, match=match):
            OutcomeDigest.model_validate(digest_payload(**overrides))


def test_a_digest_with_no_communities_is_valid_and_reports_polarization_as_not_measurable():
    digest = OutcomeDigest.model_validate(digest_payload(community_pmfs={}, community_sizes={}))
    assert digest.polarization is None
    assert digest.model_dump(mode="json")["polarization"] is None


def test_adoption_is_share_weighted_top_two_box_purchase_intent():
    digest = OutcomeDigest.model_validate(digest_payload())
    assert digest.adoption == pytest.approx(0.6 * (0.30 + 0.35) + 0.4 * (0.25 + 0.15))


def test_polarization_is_computed_over_communities_and_divergence_over_audiences():
    same = (0.05, 0.10, 0.20, 0.30, 0.35)
    calm = OutcomeDigest.model_validate(digest_payload(community_pmfs={"community-1": same, "community-2": same}))
    assert calm.polarization == pytest.approx(0.0, abs=1e-12)
    opposite = OutcomeDigest.model_validate(digest_payload(community_pmfs={"community-1": (0.9, 0.025, 0.025, 0.025, 0.025),
                                                                          "community-2": (0.025, 0.025, 0.025, 0.025, 0.9)}))
    assert opposite.polarization > 0.5 > calm.polarization
    single = OutcomeDigest.model_validate(digest_payload(community_pmfs={"community-1": same}, community_sizes={"community-1": 200}))
    assert single.polarization is None
    assert 0.0 <= opposite.audience_divergence <= 1.0
    assert not {"adoption", "polarization", "audience_divergence"} & set(OutcomeDigest.model_fields)


def test_stated_digest_numbers_contradicting_the_masses_refused():
    for field, value in (("polarization", 0.0), ("adoption", 0.99)):
        stated = {**digest_payload(community_pmfs={"community-1": (0.9, 0.025, 0.025, 0.025, 0.025), "community-2": (0.025, 0.025, 0.025, 0.025, 0.9)}), field: value}
        with pytest.raises(ValidationError, match="computed"):
            OutcomeDigest.model_validate(stated)


def test_a_stated_polarization_for_no_communities_is_refused():
    impossible = digest_payload(community_pmfs={}, community_sizes={}, polarization=0.0)
    with pytest.raises(ValidationError, match="computed"):
        OutcomeDigest.model_validate(impossible)


def test_digest_numbers_and_hash_do_not_depend_on_insertion_order():
    forward = OutcomeDigest.model_validate(digest_payload())
    reordered = digest_payload()
    for key in ("audience_pmfs", "audience_shares", "community_pmfs", "community_sizes"):
        reordered[key] = dict(reversed(list(reordered[key].items())))
    backward = OutcomeDigest.model_validate(reordered)
    assert (forward.adoption, forward.polarization, forward.audience_divergence) == (backward.adoption, backward.polarization, backward.audience_divergence)
    assert canonical_hash(forward) == canonical_hash(backward)


def test_digests_of_differing_tick_units_refuse_comparison():
    daily = OutcomeDigest.model_validate(digest_payload())
    weekly = OutcomeDigest.model_validate(digest_payload(tick_unit="week"))
    ensure_same_tick_unit(daily, daily)
    with pytest.raises(ValueError, match="not comparable"):
        ensure_same_tick_unit(daily, weekly)


# --- report -----------------------------------------------------------------------------------


def test_report_validates_states_trust_once_and_discloses_its_method():
    report = Report.model_validate(report_payload())
    assert report.trust.level is TrustLevel.UNCALIBRATED
    assert report.config.template_hashes and report.config.pins and report.config.seeds
    assert Report.model_validate_json(report.model_dump_json()) == report


def test_report_needs_at_least_one_digest():
    with pytest.raises(ValidationError):
        Report.model_validate(report_payload(digests=[]))


@pytest.mark.parametrize(
    ("digests", "match"),
    [
        ([digest_payload(scenario_payload(horizon_ticks=60))], "does not configure"),
        ([digest_payload(BASELINE, tick_unit="week")], "week ticks"),
            ([digest_payload(BASELINE, audience_pmfs={"strangers": (0.05, 0.10, 0.20, 0.30, 0.35)}, audience_shares={"strangers": 1.0})], "differ from the scenario"),
        ([digest_payload(BASELINE), digest_payload(BASELINE)], "more than once"),
    ],
    ids=["foreign-scenario", "wrong-tick-unit", "wrong-audiences", "digested-twice"],
)
def test_every_digest_describes_one_scenario_of_this_run(digests, match):
    with pytest.raises(ValidationError, match=match):
        Report.model_validate(report_payload(digests=digests, findings=[finding_payload()]))


def test_report_refuses_repeated_finding_ids_and_rankings_of_undigested_scenarios():
    with pytest.raises(ValidationError, match="finding ids repeated"):
        Report.model_validate(report_payload(findings=[finding_payload(), finding_payload()]))
    with pytest.raises(ValidationError, match="does not digest"):
        Report.model_validate(report_payload(digests=[digest_payload(BASELINE)]))


@pytest.mark.parametrize(
    ("anomaly", "match"),
    [({"scenario_hash": "ff" * 32, "tick": 3}, "does not configure"), ({"scenario_hash": scenario_hash(BASELINE), "tick": 30}, "beyond its scenario")],
    ids=["foreign-scenario", "beyond-horizon"],
)
def test_anomalies_belong_to_a_scenario_of_this_run(anomaly, match):
    with pytest.raises(ValidationError, match=match):
        Report.model_validate(report_payload(anomalies=[{"kind": "backlash", "evidence_trace_ids": EVIDENCE[:1], **anomaly}]))
