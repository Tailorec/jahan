"""Projection: rows become personas, and a model may only choose values the corpus already holds."""

import copy
import json

import pytest

from simcore.population._project import COMPLETION_TEMPLATE_ID, project
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, FieldOrigin, Persona, canonical_hash
from tests.study_builders import load_fixture, load_ontology, pack_payload

MODEL = "openrouter/camel-ai/persona-8b"


def synthetic(rows: int = 200, seed: int = 7, *, diet_populated: float = 1.0, spend_populated: float = 0.5) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "medium", "high"), populated=diet_populated),
                "spend_band": AttributeShape(("5_10", "10_20"), populated=spend_populated),
            },
            rows=rows,
        ),
        seed=seed,
    )


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def rows_of(source: SyntheticCoresetSource, brief: BriefPack) -> list:
    conditioning = tuple(sorted(brief.ontology.conditioning_set))
    return list(source.rows(source.matching({}, present=conditioning)))


def off_list_responder(messages, template_id) -> str:
    request = json.loads(messages[-1]["content"])
    return json.dumps({persona["persona_id"]: "invented" for persona in request["personas"]})


def test_every_projected_field_states_an_origin():
    source = synthetic()
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(), completion_model_id=MODEL)
    for persona in projection.personas:
        assert set(persona.origins) == persona.projected_attributes
    with pytest.raises(Exception):
        Persona.model_validate(
            {
                "persona_id": "p-000001",
                "source": "synthetic",
                "conditioning": {"age": "25_34"},
                "attributes": {"spend_band": "5_10"},
                "origins": {"age": "grounded"},
                "baseline_beliefs": {"dimensions": {"value": 0.5, "fit": 0.5, "trust": 0.5}, "claim_credence": {"C1": 0.5}},
            }
        )


def test_completion_chooses_from_the_corpus_value_set():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(), completion_model_id=MODEL)
    completed = [persona for persona in projection.personas if "spend_band" in persona.origins and persona.origins["spend_band"] is FieldOrigin.SYNTHESIZED]
    assert completed
    assert all(persona.attributes["spend_band"] in source.values("spend_band") for persona in completed)


def test_an_off_list_answer_is_retried_once_then_the_field_is_left_absent():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    fake = FakeChat(off_list_responder)
    projection = project(brief, rows_of(source, brief), source, inference=fake, completion_model_id=MODEL)
    assert projection.completion is None and projection.synthesized_share == 0.0
    assert all(persona.origins.get("spend_band") is not FieldOrigin.SYNTHESIZED for persona in projection.personas)
    assert any("spend_band" not in persona.origins for persona in projection.personas)
    assert len(fake.calls) == 2  # one attempt, one stricter retry


def test_no_demographic_or_psychographic_field_is_synthesized():
    source = synthetic(diet_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(), completion_model_id=MODEL)
    assert any("diet_protein_focus" not in persona.origins for persona in projection.personas)
    assert all(
        persona.origins.get("diet_protein_focus") is not FieldOrigin.SYNTHESIZED for persona in projection.personas
    )


def test_completion_is_batched_rather_than_one_call_per_persona():
    source = synthetic(rows=400, spend_populated=0.3)
    brief = pack()
    fake = FakeChat()
    projection = project(brief, rows_of(source, brief), source, inference=fake, completion_model_id=MODEL)
    completed = [persona for persona in projection.personas if persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED]
    assert len(completed) > 20
    assert len(fake.calls) == 1  # one call for the whole attribute's batch, not one per persona


def test_the_projection_records_the_completing_model_template_and_synthesized_share():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(), completion_model_id=MODEL)
    assert projection.completion.model_id == MODEL
    assert projection.completion.template_id == COMPLETION_TEMPLATE_ID
    assert len(projection.completion.template_hash) == 64
    assert 0.0 < projection.synthesized_share < 1.0


def test_projecting_the_same_sample_twice_produces_identical_personas():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    rows = rows_of(source, brief)
    first = project(brief, rows, source, inference=FakeChat(), completion_model_id=MODEL)
    second = project(brief, rows, source, inference=FakeChat(), completion_model_id=MODEL)
    assert canonical_hash(first.personas[0]) == canonical_hash(second.personas[0])
    assert [canonical_hash(persona) for persona in first.personas] == [canonical_hash(persona) for persona in second.personas]


def test_a_sample_needing_no_completion_calls_no_model():
    source = synthetic(diet_populated=1.0, spend_populated=1.0)
    brief = pack()
    fake = FakeChat()
    projection = project(brief, rows_of(source, brief), source, inference=fake, completion_model_id=MODEL)
    assert fake.calls == []
    assert projection.completion is None and projection.synthesized_share == 0.0


def test_a_non_conditioning_calibrated_domain_is_not_completed():
    """A field the completion policy may not synthesize is left absent, not invented."""
    ontology = copy.deepcopy(load_ontology())
    ontology["attribute_domains"]["income"] = "demographic"
    ontology["relevance_order"] = [*ontology["relevance_order"], "income"]
    brief = BriefPack.model_validate({"brief": load_fixture("example_brief.json"), "ontology": ontology})
    source = SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("25_34", "35_44")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "high")),
                "income": AttributeShape(("low", "high"), populated=0.5),
            },
            rows=100,
        ),
        seed=3,
    )
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(), completion_model_id=MODEL)
    assert any("income" not in persona.origins for persona in projection.personas)
