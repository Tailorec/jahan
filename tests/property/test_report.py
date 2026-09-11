import pytest
from pydantic import ValidationError

from simcore.schemas import (
    CalibrationRef,
    Confidence,
    Finding,
    FindingKind,
    TrustLevel,
    TrustStatement,
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
