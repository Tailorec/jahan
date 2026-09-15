"""The evidence grade a gate report carries, and the one claim its evidence may not support."""

import pytest
from pydantic import ValidationError

from simcore.population import assess, build
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, FieldOrigin, GateFailure, GateReport, Population
from tests.study_builders import pack_payload, population_payload


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def extracted_source(origin: FieldOrigin, rows: int = 4000) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly"), origin=origin),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            },
            rows=rows,
        ),
        seed=11,
    )


MATCHING = {
    "age": {"18_24": 0.25, "25_34": 0.25, "35_44": 0.25, "45_54": 0.25},
    "sex": {"female": 0.5, "male": 0.5},
    "exercise_frequency": {"rarely": 0.334, "weekly": 0.333, "3_plus_weekly": 0.333},
    "diet_protein_focus": {"low": 0.334, "medium": 0.333, "high": 0.333},
}


def pack_with_targets(marginals: dict, **brief_overrides) -> BriefPack:
    payload = pack_payload(**brief_overrides)
    payload["ontology"]["targets"] = {"source": "a measured category survey", "marginals": marginals}
    return BriefPack.model_validate(payload)


# --- the grade the report carries -------------------------------------------------------------


def test_a_report_of_measured_gates_grades_as_measured():
    report = GateReport.model_validate(
        {
            **population_payload()["gate_report"],
            "attribute_origins": {"exercise_frequency": "measured", "age": "measured"},
        }
    )
    assert report.evidence is FieldOrigin.MEASURED


def test_one_extracted_gate_lowers_the_whole_report():
    report = GateReport.model_validate(
        {
            **population_payload()["gate_report"],
            "attribute_origins": {"exercise_frequency": "measured", "age": "extracted"},
        }
    )
    assert report.evidence is FieldOrigin.EXTRACTED


def test_the_grade_is_computed_and_a_contradicting_value_is_refused():
    payload = {
        **population_payload()["gate_report"],
        "attribute_origins": {"exercise_frequency": "measured", "age": "extracted"},
    }
    report = GateReport.model_validate(payload)
    assert report.model_dump(mode="json")["evidence"] == "extracted"
    with pytest.raises(ValidationError, match="computed"):
        GateReport.model_validate({**payload, "evidence": "measured"})


def test_the_grade_survives_a_population_round_trip():
    base = population_payload()
    gate_report = {**base["gate_report"], "attribute_origins": {"exercise_frequency": "measured", "age": "extracted"}}
    personas = [{**persona, "origins": {**persona["origins"], "age": "extracted"}} for persona in base["personas"]]
    population = Population.model_validate(population_payload(gate_report=gate_report, personas=personas))
    assert population.gate_report.evidence is FieldOrigin.EXTRACTED
    restored = Population.model_validate_json(population.model_dump_json())
    assert restored.gate_report.evidence is FieldOrigin.EXTRACTED


# --- the one refusal --------------------------------------------------------------------------


def test_category_targets_on_a_non_measured_attribute_is_refused_by_name_and_tier():
    with pytest.raises(GateFailure, match=r"category targets for 'exercise_frequency'.*extracted"):
        assess(pack_with_targets(MATCHING, audiences=[]), 1000, 4021, coreset=extracted_source(FieldOrigin.EXTRACTED))


def test_a_study_declaring_no_audiences_still_gates_on_targets_when_measured():
    report = assess(pack_with_targets(MATCHING, audiences=[]), 1000, 4021, coreset=extracted_source(FieldOrigin.MEASURED))
    assert report.reference.value == "category_targets"
    assert report.evidence is FieldOrigin.MEASURED


def test_build_refuses_the_strong_claim_before_any_model_is_called():
    fake = FakeChat()
    with pytest.raises(GateFailure, match="category targets"):
        build(
            pack_with_targets(MATCHING, audiences=[]),
            300,
            4021,
            coreset=extracted_source(FieldOrigin.EXTRACTED),
            inference=fake,
        )
    assert fake.calls == []