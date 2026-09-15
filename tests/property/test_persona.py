import warnings

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import KNOWN_PERSONA_SOURCES, EmbeddingRef, FieldOrigin, Persona, PersonaSource
from tests.study_builders import persona_payload


def test_persona_validates_with_every_field_stating_its_origin():
    persona = Persona.model_validate(persona_payload())
    assert persona.conditioning["exercise_frequency"] == "3_plus_weekly"
    assert persona.origins["age"] is FieldOrigin.MEASURED
    assert persona.origins["spend_band"] is FieldOrigin.SYNTHESIZED
    assert persona.projected_attributes == {"age", "sex", "exercise_frequency", "diet_protein_focus", "spend_band"}


def test_persona_carries_no_copy_of_what_its_category_requires():
    for field in ("conditioning_set", "attribute_domains", "category"):
        assert field not in Persona.model_fields


def test_persona_without_conditioning_refused():
    payload = persona_payload(
        conditioning={},
        origins={"diet_protein_focus": "measured", "spend_band": "synthesized"},
    )
    with pytest.raises(ValidationError, match="conditioned"):
        Persona.model_validate(payload)


def test_conditioning_and_attributes_must_be_disjoint():
    payload = persona_payload(attributes={"age": "25_34", "diet_protein_focus": "high", "spend_band": "5_10"})
    with pytest.raises(ValidationError, match="both"):
        Persona.model_validate(payload)


def test_every_projected_field_must_state_an_origin():
    origins = persona_payload()["origins"]
    del origins["diet_protein_focus"]
    with pytest.raises(ValidationError, match="unstated"):
        Persona.model_validate(persona_payload(origins=origins))


def test_origin_for_unknown_attribute_refused():
    origins = {**persona_payload()["origins"], "hair_color": "measured"}
    with pytest.raises(ValidationError, match="unknown attributes"):
        Persona.model_validate(persona_payload(origins=origins))


@pytest.mark.parametrize("source", sorted(KNOWN_PERSONA_SOURCES))
def test_known_persona_sources_accepted_silently(source):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert TypeAdapter(PersonaSource).validate_python(source) == source


def test_documented_dataset_corpora_are_known():
    assert {"amazon", "gss", "wiki", "prism", "stackoverflow", "synthetic"} <= KNOWN_PERSONA_SOURCES
    assert "matraix" not in KNOWN_PERSONA_SOURCES


def test_unrecognised_but_well_formed_source_warns_and_passes():
    with pytest.warns(UserWarning, match="unrecognised persona source 'census'"):
        assert TypeAdapter(PersonaSource).validate_python("census") == "census"


@pytest.mark.parametrize("source", ["", "MATRAIX", "has space", "1gss"])
def test_malformed_source_refused(source):
    with pytest.raises(ValidationError):
        TypeAdapter(PersonaSource).validate_python(source)


def test_embedding_is_a_positional_reference():
    persona = Persona.model_validate(persona_payload(index=2, embedding={"model_id": "text-embedding-3-small", "dim": 1536, "index": 2}))
    assert isinstance(persona.embedding, EmbeddingRef)
    assert (persona.embedding.index, persona.embedding.dim) == (2, 1536)
    with pytest.raises(ValidationError):
        EmbeddingRef(model_id="text-embedding-3-small", dim=0, index=0)
    with pytest.raises(ValidationError):
        EmbeddingRef(model_id="text-embedding-3-small", dim=1536, index=-1)


def test_a_persona_may_omit_its_embedding():
    assert Persona.model_validate(persona_payload()).embedding is None


def test_persona_round_trips_through_json():
    persona = Persona.model_validate(persona_payload())
    assert Persona.model_validate(persona.model_dump(mode="json")) == persona
    assert Persona.model_validate_json(persona.model_dump_json()) == persona


value = st.one_of(
    st.from_regex(r"[a-z][a-z0-9_]{0,11}", fullmatch=True),
    st.integers(min_value=0, max_value=1_000),
    st.floats(min_value=0.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
)


@given(spend=value, focus=value)
def test_persona_attribute_values_round_trip_over_generated_values(spend, focus):
    persona = Persona.model_validate(persona_payload(attributes={"diet_protein_focus": focus, "spend_band": spend}))
    assert Persona.model_validate(persona.model_dump(mode="json")) == persona


def test_persona_carries_complete_baseline_beliefs_without_a_claim_list_of_its_own():
    persona = Persona.model_validate(persona_payload())
    assert set(persona.baseline_beliefs.claim_credence) == {"C1", "C2", "C3"}
    assert "claim_ids" not in type(persona.baseline_beliefs).model_fields
    payload = persona_payload()
    del payload["baseline_beliefs"]
    with pytest.raises(ValidationError, match="baseline_beliefs"):
        Persona.model_validate(payload)
