import pytest
from pydantic import ValidationError

from tests.demo_contracts import DemoBrief, make_brief_payload


def test_unknown_field_rejected():
    payload = make_brief_payload(unexpected_key="x")
    with pytest.raises(ValidationError, match="unexpected_key"):
        DemoBrief.model_validate(payload)


def test_mutation_refused_after_construction():
    brief = DemoBrief.model_validate(make_brief_payload())
    with pytest.raises(ValidationError, match="frozen"):
        brief.title = "Changed"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_rejected(bad):
    payload = make_brief_payload(audience_mix={"gym_regulars": bad})
    with pytest.raises(ValidationError):
        DemoBrief.model_validate(payload)


def test_surrounding_whitespace_stripped():
    brief = DemoBrief.model_validate(make_brief_payload(title="  Protein water  "))
    assert brief.title == "Protein water"


def test_sequence_fields_accept_lists_and_store_immutable_tuples():
    payload = make_brief_payload(claims=["a", "b"])
    assert isinstance(DemoBrief.model_validate(payload).claims, tuple)
