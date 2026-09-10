import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    HashDigest,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PersonaId,
    PositiveInt,
    RunId,
    SignedUnitInterval,
    StimulusId,
    UnitInterval,
)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_unit_interval_accepts_inclusive_bounds(value):
    assert TypeAdapter(UnitInterval).validate_python(value) == value


@pytest.mark.parametrize("value", [-0.001, 1.001, 100.0])
def test_unit_interval_rejects_outside_bounds(value):
    with pytest.raises(ValidationError):
        TypeAdapter(UnitInterval).validate_python(value)


@pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_signed_unit_interval_accepts_inclusive_bounds(value):
    assert TypeAdapter(SignedUnitInterval).validate_python(value) == value


@pytest.mark.parametrize("value", [-1.001, 1.001])
def test_signed_unit_interval_rejects_outside_bounds(value):
    with pytest.raises(ValidationError):
        TypeAdapter(SignedUnitInterval).validate_python(value)


def test_non_negative_int_boundary():
    assert TypeAdapter(NonNegativeInt).validate_python(0) == 0
    with pytest.raises(ValidationError):
        TypeAdapter(NonNegativeInt).validate_python(-1)


def test_positive_int_boundary():
    assert TypeAdapter(PositiveInt).validate_python(1) == 1
    with pytest.raises(ValidationError):
        TypeAdapter(PositiveInt).validate_python(0)


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_non_empty_str_refuses_blank(value):
    with pytest.raises(ValidationError):
        TypeAdapter(NonEmptyStr).validate_python(value)


def test_non_empty_str_strips_surrounding_whitespace():
    assert TypeAdapter(NonEmptyStr).validate_python("  brief  ") == "brief"


def test_identifier_rules():
    adapter = TypeAdapter(Identifier)
    assert adapter.validate_python("matraix_0042") == "matraix_0042"
    assert adapter.validate_python("gss:1988:041") == "gss:1988:041"
    for bad in ("", " leading", "has space", "_underscore_start", "-dash_start"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_run_and_stimulus_ids_are_lowercase_alnum_and_sortable():
    assert TypeAdapter(RunId).validate_python("run20260911a")
    assert TypeAdapter(StimulusId).validate_python("stim00000001")
    run_id = TypeAdapter(RunId)
    for bad in ("RUN20260911A", "short", "with-dash", "x" * 65):
        with pytest.raises(ValidationError):
            run_id.validate_python(bad)


def test_persona_id_accepts_dataset_row_identifier():
    assert TypeAdapter(PersonaId).validate_python("matraix.row:000042")


def test_hash_digest_is_64_lowercase_hex_chars():
    digest = TypeAdapter(HashDigest)
    assert digest.validate_python("ab12" * 16)
    for bad in ("ab12" * 15, "AB12" * 16, "zz" * 32, "ab12" * 16 + "f"):
        with pytest.raises(ValidationError):
            digest.validate_python(bad)
