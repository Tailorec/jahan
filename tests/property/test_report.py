import pytest
from pydantic import ValidationError

from simcore.schemas import (
    Anomaly,
    AnomalyKind,
    CalibrationRef,
    Confidence,
    Finding,
    FindingKind,
    ModelPins,
    ObjectionCluster,
    OutcomeDigest,
    Report,
    TickUnit,
    TrustLevel,
    TrustStatement,
    ensure_same_tick_unit,
)

EVENT_ID = "ev-01j7x9k2m3n4p5q6r7s8t9v0wx"


def finding_payload(**overrides):
    payload = {
        "finding_id": "f-objection-01",
        "kind": "objection",
        "statement": "the aftertaste is the recurring objection among gym regulars",
        "evidence_trace_ids": [EVENT_ID, "ev-01j7x9k2m3n4p5q6r7s8t9v0w0"],
        "disconfirming_test": "run 20 blind taste tests against the leading clear protein; if fewer than 30% mention aftertaste, the finding is wrong",
        "confidence": "medium",
    }
    payload.update(overrides)
    return payload


def test_finding_without_supporting_records_refused():
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(evidence_trace_ids=[]))


def test_finding_without_disconfirming_test_refused():
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(disconfirming_test=""))
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(disconfirming_test="   "))


def test_finding_carries_no_trust_level_and_no_provenance():
    assert "trust" not in Finding.model_fields
    assert "trust_level" not in Finding.model_fields
    assert "calibration" not in Finding.model_fields
    assert "provenance" not in Finding.model_fields


def test_finding_confidence_is_per_finding_and_closed():
    finding = Finding.model_validate(finding_payload())
    assert finding.confidence is Confidence.MEDIUM
    for value in ("low", "medium", "high"):
        assert Finding.model_validate(finding_payload(confidence=value)).confidence.value == value
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(confidence="certain"))


def test_finding_kinds_are_a_closed_set():
    assert {member.value for member in FindingKind} == {"objection", "belief_shift", "wom_path", "recommendation"}


def test_trust_statement_defaults_to_uncalibrated_without_a_reference():
    trust = TrustStatement(level=TrustLevel.UNCALIBRATED)
    assert trust.calibration_ref is None


def test_trust_above_uncalibrated_without_a_calibration_reference_refused():
    for level in (TrustLevel.CATEGORY_BENCHMARKED, TrustLevel.PROSPECTIVELY_VALIDATED):
        with pytest.raises(ValidationError, match="calibration reference"):
            TrustStatement(level=level)


def test_trust_above_uncalibrated_with_a_reference_validates():
    trust = TrustStatement.model_validate(
        {
            "level": "category_benchmarked",
            "calibration_ref": {
                "benchmark": "ssr_replica_benchmark",
                "study_id": "colgate_palmolive_2025",
                "checked_at": "2026-09-11T00:00:00Z",
            },
        }
    )
    assert trust.calibration_ref is not None


def test_nothing_in_the_package_produces_a_calibration_reference():
    for name, field in CalibrationRef.model_fields.items():
        assert field.is_required(), f"CalibrationRef.{name} must not have a default"
    assert TrustStatement.model_fields["level"].is_required()
    assert TrustStatement.model_fields["calibration_ref"].default is None


def test_trust_statement_round_trips_through_json():
    trust = TrustStatement(level=TrustLevel.UNCALIBRATED, caveats=["engine has never been benchmarked"])
    assert TrustStatement.model_validate(trust.model_dump(mode="json")) == trust


# --- anomalies, objection clusters, digests, report ----------------------------------------------

POPULATION_HASH = "dd44" * 16


def anomaly_payload(**overrides):
    payload = {
        "kind": "herding",
        "tick": 12,
        "evidence_trace_ids": [EVENT_ID],
    }
    payload.update(overrides)
    return payload


def digest_payload(**overrides):
    payload = {
        "scenario_hash": "aa11" * 16,
        "tick_unit": "day",
        "adoption": 0.32,
        "audience_pmfs": {"gym_regulars": (0.05, 0.1, 0.2, 0.3, 0.35)},
        "community_pmfs": {"community-1": (0.04, 0.1, 0.21, 0.3, 0.35)},
        "polarization": 0.18,
        "audience_divergence": 0.09,
    }
    payload.update(overrides)
    return payload


def pins_payload():
    return {
        "tier_a": "openrouter/camel-ai/persona-8b",
        "tier_b": "anthropic/claude-sonnet-4-5-20250929",
        "embed": "openai/text-embedding-3-small",
    }


def report_payload(**overrides):
    payload = {
        "run_id": "run-01j7x9k2m3n4p5q6r7s8t9v0wx",
        "trust": {"level": "uncalibrated", "caveats": ["engine has never been benchmarked"]},
        "pins": pins_payload(),
        "seeds": [4021, 917731],
        "findings": [finding_payload()],
        "anomalies": [anomaly_payload()],
        "objection_clusters": [{"label": "aftertaste", "verbatim_trace_ids": [EVENT_ID], "size": 14}],
        "digests": [digest_payload()],
    }
    payload.update(overrides)
    return payload


def test_anomaly_kinds_are_a_closed_set_and_evidence_is_required():
    assert {member.value for member in AnomalyKind} == {"herding", "backlash", "flop"}
    anomaly = Anomaly.model_validate(anomaly_payload())
    assert anomaly.kind is AnomalyKind.HERDING
    with pytest.raises(ValidationError):
        Anomaly.model_validate(anomaly_payload(evidence_trace_ids=[]))


def test_objection_cluster_carries_its_verbatims():
    cluster = ObjectionCluster.model_validate({"label": "aftertaste", "verbatim_trace_ids": [EVENT_ID], "size": 14})
    assert cluster.size == 14
    with pytest.raises(ValidationError):
        ObjectionCluster.model_validate({"label": "aftertaste", "verbatim_trace_ids": [], "size": 0})


def test_outcome_digest_carries_both_audience_and_community_distributions():
    digest = OutcomeDigest.model_validate(digest_payload())
    assert set(digest.audience_pmfs) == {"gym_regulars"}
    assert set(digest.community_pmfs) == {"community-1"}
    with pytest.raises(ValidationError):
        OutcomeDigest.model_validate(digest_payload(audience_pmfs={}))
    with pytest.raises(ValidationError):
        OutcomeDigest.model_validate(digest_payload(community_pmfs={}))


def test_digest_polarization_and_audience_divergence_are_separate_fields():
    digest = OutcomeDigest.model_validate(digest_payload())
    assert {"polarization", "audience_divergence"} <= set(OutcomeDigest.model_fields)
    assert digest.polarization != digest.audience_divergence


def test_digests_of_differing_tick_units_refuse_comparison():
    daily = OutcomeDigest.model_validate(digest_payload())
    weekly = OutcomeDigest.model_validate(digest_payload(tick_unit="week"))
    ensure_same_tick_unit(daily, daily)
    with pytest.raises(ValueError, match="not comparable"):
        ensure_same_tick_unit(daily, weekly)


def test_report_states_trust_once_and_keeps_findings_trustless():
    report = Report.model_validate(report_payload())
    assert report.trust.level is TrustLevel.UNCALIBRATED
    assert "trust" not in Finding.model_fields
    assert len(report.findings) == 1 and len(report.digests) == 1


def test_report_round_trips_through_json():
    report = Report.model_validate(report_payload())
    assert Report.model_validate(report.model_dump(mode="json")) == report
    assert Report.model_validate_json(report.model_dump_json()) == report


def test_report_refuses_a_digestless_document():
    with pytest.raises(ValidationError):
        Report.model_validate(report_payload(digests=[]))
