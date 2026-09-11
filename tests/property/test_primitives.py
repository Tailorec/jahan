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


VALID_ULID = "01j7x9k2m3n4p5q6r7s8t9v0wx"


@pytest.mark.parametrize(("id_type", "prefix", "other_prefix"), [(RunId, "run-", "st-"), (StimulusId, "st-", "run-")])
def test_run_and_stimulus_ids_are_prefixed_lowercase_ulids(id_type, prefix, other_prefix):
    adapter = TypeAdapter(id_type)
    assert adapter.validate_python(f"{prefix}{VALID_ULID}")
    for bad in (
        VALID_ULID,
        f"{other_prefix}{VALID_ULID}",
        f"{prefix.rstrip('-')}_{VALID_ULID}",
        f"{prefix}{VALID_ULID.upper()}",
        f"{prefix}{VALID_ULID[:-1]}",
        f"{prefix}8{VALID_ULID[1:]}",
        f"{prefix}{VALID_ULID[:-1]}u",
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_persona_id_is_prefixed_dataset_row_identifier():
    adapter = TypeAdapter(PersonaId)
    assert adapter.validate_python("p-000042")
    assert adapter.validate_python("p-gss:1988:041")
    for bad in ("000042", "q-000042", "p-", "p-has space", "p--leading-dash"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_hash_digest_is_64_lowercase_hex_chars():
    digest = TypeAdapter(HashDigest)
    assert digest.validate_python("ab12" * 16)
    for bad in ("ab12" * 15, "AB12" * 16, "zz" * 32, "ab12" * 16 + "f"):
        with pytest.raises(ValidationError):
            digest.validate_python(bad)
