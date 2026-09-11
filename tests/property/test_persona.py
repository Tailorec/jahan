import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import EmbeddingRef, FieldOrigin, Persona, PersonaFieldDomain, PersonaSource

DOMAINS = {
    "age": "demographic",
    "exercise_frequency": "category_behaviour",
    "brand_loyalty": "psychographic",
    "spend_band": "economic",
}


def persona_payload(**overrides):
    payload = {
        "persona_id": "p-000042",
        "source": "gss",
        "category": "beverage_protein",
        "conditioning_set": ["age", "exercise_frequency"],
        "conditioning": {"age": "25_34", "exercise_frequency": "3_plus_weekly"},
        "attributes": {"brand_loyalty": "medium", "spend_band": "5_10"},
        "attribute_domains": DOMAINS,
        "origins": {
            "age": "grounded",
            "exercise_frequency": "grounded",
            "brand_loyalty": "grounded",
            "spend_band": "synthesized",
        },
        "embedding": {"model_id": "text-embedding-3-small", "dim": 1536, "index": 17},
    }
    payload.update(overrides)
    return payload


def test_conditioned_persona_validates():
    persona = Persona.model_validate(persona_payload())
    assert persona.conditioning == {"age": "25_34", "exercise_frequency": "3_plus_weekly"}
    assert persona.origins["age"] is FieldOrigin.GROUNDED
    assert persona.origins["spend_band"] is FieldOrigin.SYNTHESIZED


def test_persona_missing_a_conditioning_attribute_refused():
    payload = persona_payload(conditioning={"age": "25_34"})
    with pytest.raises(ValidationError, match="missing"):
        Persona.model_validate(payload)


def test_persona_with_extra_conditioning_attribute_refused():
    payload = persona_payload(
        conditioning={"age": "25_34", "exercise_frequency": "3_plus_weekly", "sex": "female"}
    )
    with pytest.raises(ValidationError, match="unexpected"):
        Persona.model_validate(payload)


def test_empty_conditioning_set_refused():
    with pytest.raises(ValidationError):
        Persona.model_validate(persona_payload(conditioning_set=[]))


def test_conditioning_and_attributes_must_be_disjoint():
    payload = persona_payload(
        conditioning={"age": "25_34", "exercise_frequency": "3_plus_weekly"},
        attributes={"age": "25_34", "brand_loyalty": "medium", "spend_band": "5_10"},
    )
    with pytest.raises(ValidationError, match="disjoint|both"):
        Persona.model_validate(payload)


@pytest.mark.parametrize(
    ("attribute", "domain"),
    [("age", PersonaFieldDomain.DEMOGRAPHIC), ("brand_loyalty", PersonaFieldDomain.PSYCHOGRAPHIC)],
)
def test_demographic_and_psychographic_fields_refuse_synthesized_origin(attribute, domain):
    origins = {**persona_payload()["origins"], attribute: "synthesized"}
    with pytest.raises(ValidationError, match="may not be synthesized"):
        Persona.model_validate(persona_payload(origins=origins))


def test_calibrated_demographic_origin_allowed():
    payload = persona_payload(origins={**persona_payload()["origins"], "age": "calibrated"})
    assert Persona.model_validate(payload).origins["age"] is FieldOrigin.CALIBRATED


def test_every_projected_field_must_state_an_origin():
    origins = persona_payload()["origins"]
    del origins["brand_loyalty"]
    with pytest.raises(ValidationError, match="unstated"):
        Persona.model_validate(persona_payload(origins=origins))


def test_origin_for_unknown_attribute_refused():
    origins = {**persona_payload()["origins"], "hair_color": "grounded"}
    with pytest.raises(ValidationError, match="unknown attributes"):
        Persona.model_validate(persona_payload(origins=origins))


def test_domains_must_cover_every_projected_field():
    domains = dict(DOMAINS)
    del domains["spend_band"]
    with pytest.raises(ValidationError, match="no declared domain"):
        Persona.model_validate(persona_payload(attribute_domains=domains))


@pytest.mark.parametrize("source", ["matraix", "gss", "synthetic"])
def test_persona_source_accepts_the_known_value_set(source):
    assert TypeAdapter(PersonaSource).validate_python(source) == source


@pytest.mark.parametrize("source", ["census", "MATRAIX", ""])
def test_persona_source_refuses_unknown_values(source):
    with pytest.raises(ValidationError):
        TypeAdapter(PersonaSource).validate_python(source)


def test_embedding_is_a_positional_reference():
    persona = Persona.model_validate(persona_payload())
    assert isinstance(persona.embedding, EmbeddingRef)
    assert persona.embedding.index == 17
    assert persona.embedding.dim == 1536
    with pytest.raises(ValidationError):
        EmbeddingRef(model_id="text-embedding-3-small", dim=0, index=0)
    with pytest.raises(ValidationError):
        EmbeddingRef(model_id="text-embedding-3-small", dim=1536, index=-1)


def test_persona_round_trips_through_json():
    persona = Persona.model_validate(persona_payload())
    assert Persona.model_validate(persona.model_dump(mode="json")) == persona
    assert Persona.model_validate_json(persona.model_dump_json()) == persona


keys = st.sampled_from(["brand_loyalty", "spend_band", "age", "exercise_frequency"])
value = st.one_of(
    st.from_regex(r"[a-z][a-z0-9_]{0,11}", fullmatch=True),
    st.integers(min_value=0, max_value=1_000),
    st.floats(min_value=0.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
)


@given(spend=value, loyalty=value)
def test_persona_attribute_values_round_trip_over_generated_values(spend, loyalty):
    payload = persona_payload(
        attributes={"brand_loyalty": loyalty, "spend_band": spend},
        origins={**persona_payload()["origins"], "brand_loyalty": "grounded"},
    )
    persona = Persona.model_validate(payload)
    assert Persona.model_validate(persona.model_dump(mode="json")) == persona
