import pickle
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, ClassVar

import pytest
from pydantic import AwareDatetime, ValidationError, create_model

from simcore.schemas import FrozenDict, SimBaseModel
from tests.demo_contracts import DemoBrief, make_brief_payload


def test_unknown_field_rejected():
    payload = make_brief_payload(unexpected_key="x")
    with pytest.raises(ValidationError, match="unexpected_key"):
        DemoBrief.model_validate(payload)


def test_mutation_refused_after_construction():
    brief = DemoBrief.model_validate(make_brief_payload())
    with pytest.raises(ValidationError, match="frozen"):
        brief.title = "Changed"


def test_mapping_field_contents_refuse_mutation():
    brief = DemoBrief.model_validate(make_brief_payload())
    assert isinstance(brief.audience_mix, FrozenDict)
    with pytest.raises(TypeError):
        brief.audience_mix["gym_regulars"] = 0.99
    assert not hasattr(brief.audience_mix, "update")


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


@pytest.mark.parametrize(
    "annotation",
    [
        list[str],
        dict[str, str],
        set[str],
        Mapping[str, str],
        Sequence[str],
        list[str] | None,
        tuple[list[str], ...],
        FrozenDict[str, list[str]],
        Annotated[dict[str, int], "metadata"],
    ],
    ids=str,
)
def test_mutable_container_annotation_refused_at_class_definition(annotation):
    with pytest.raises(TypeError, match="mutable container"):
        create_model("Sloppy", __base__=SimBaseModel, field=(annotation, ...))


@pytest.mark.parametrize(
    "annotation",
    [tuple[str, ...], frozenset[str], FrozenDict[str, str], FrozenDict[str, tuple[int, ...]], tuple[str, ...] | None],
    ids=str,
)
def test_immutable_container_annotation_allowed(annotation):
    create_model("Tidy", __base__=SimBaseModel, field=(annotation, ...))


def test_hash_exclusion_naming_a_missing_field_refused():
    with pytest.raises(TypeError, match="fetchd_at"):

        class Misspelled(SimBaseModel):
            _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"fetchd_at"})
            fetched_at: str


@pytest.mark.parametrize("exclude", ["fetched_at", {"fetched_at"}, frozenset({1})], ids=repr)
def test_hash_exclusion_must_be_a_frozenset_of_names(exclude):
    with pytest.raises(TypeError, match="frozenset of field names"):

        class Loose(SimBaseModel):
            _hash_exclude_: ClassVar[Any] = exclude
            fetched_at: str


@pytest.mark.parametrize(
    "update",
    [
        {"unexpected_key": "x"},
        {"audience_mix": {"gym_regulars": 7.0}},
        {"audience_mix": {"gym_regulars": float("nan")}},
        {"title": "   "},
    ],
    ids=["unknown-field", "out-of-range", "non-finite", "blank"],
)
def test_copy_with_update_is_validated(update):
    brief = DemoBrief.model_validate(make_brief_payload())
    with pytest.raises(ValidationError):
        brief.model_copy(update=update)


def test_copy_with_update_applies_and_stays_immutable():
    brief = DemoBrief.model_validate(make_brief_payload())
    copy = brief.model_copy(update={"title": "  Sparkling water ", "audience_mix": {"dieters": 1.0}})
    assert copy.title == "Sparkling water"
    assert copy.claims == brief.claims
    with pytest.raises(TypeError):
        copy.audience_mix["dieters"] = 0.5


def test_models_with_mapping_fields_cross_processes_and_live_in_sets():
    brief = DemoBrief.model_validate(make_brief_payload())
    assert pickle.loads(pickle.dumps(brief)) == brief
    assert len({brief, DemoBrief.model_validate(make_brief_payload())}) == 1


@pytest.mark.parametrize("annotation", [datetime, datetime | None, tuple[datetime, ...]], ids=str)
def test_timezone_less_datetime_annotation_refused_at_class_definition(annotation):
    with pytest.raises(TypeError, match="AwareDatetime"):
        create_model("Ambiguous", __base__=SimBaseModel, field=(annotation, ...))


def test_aware_datetime_annotation_allowed_and_naive_values_refused():
    stamped = create_model("Stamped", __base__=SimBaseModel, at=(AwareDatetime, ...))
    assert stamped(at="2026-09-01T00:00:00Z").at.tzinfo is not None
    with pytest.raises(ValidationError):
        stamped(at="2026-09-01T00:00:00")
