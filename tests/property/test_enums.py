import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import ClaimSource, PersonaFieldDomain


def test_claim_source_is_the_three_glossary_values():
    assert {member.value for member in ClaimSource} == {"user_asserted", "public_source", "assumed"}


def test_persona_field_domain_is_closed():
    assert {member.value for member in PersonaFieldDomain} == {
        "demographic",
        "psychographic",
        "economic",
        "decision_rule",
        "media",
    }


@pytest.mark.parametrize("bad", ["invented", "", "USER_ASSERTED", "asserted by user"])
def test_mistyped_claim_source_cannot_invent_a_category(bad):
    with pytest.raises(ValidationError):
        TypeAdapter(ClaimSource).validate_python(bad)


@pytest.mark.parametrize("bad", ["behavioural", "", "DEMOGRAPHIC", "demographics"])
def test_mistyped_field_domain_cannot_invent_a_category(bad):
    with pytest.raises(ValidationError):
        TypeAdapter(PersonaFieldDomain).validate_python(bad)
