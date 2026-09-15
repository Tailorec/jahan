"""The natural-language step: words become predicates, bounded by what the catalog holds."""

import json
from pathlib import Path

import pytest

from simcore.population import interpret_audience
from simcore.ports.fake import FakeChat
from simcore.ports.fixture import FixtureCoresetSource
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import Audience, BandRange, BriefPack, Exactly
from tests.study_builders import pack_payload

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def fixture() -> FixtureCoresetSource:
    return FixtureCoresetSource.from_json(FIXTURES / "mini_coreset.json")


def sparse() -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "high"), populated=0.0),
            },
            rows=400,
        ),
        seed=1,
    )


def fake_returning(payload) -> FakeChat:
    return FakeChat(responder=lambda messages, template_id: json.dumps(payload))


def test_the_interpretation_reaches_the_model_and_returns_its_predicates():
    audience = interpret_audience(
        "people who train three times a week or more",
        pack(audiences=[]),
        name="gym_regulars",
        catalog=fixture(),
        inference=fake_returning({"exercise_frequency": "3_plus_weekly"}),
    )
    hand_authored = Audience(name="gym_regulars", share=None, attribute_filters={"exercise_frequency": Exactly(value="3_plus_weekly")})
    assert audience == hand_authored


def test_the_model_is_given_the_coverage_table_as_its_whole_vocabulary():
    fake = fake_returning({"exercise_frequency": "weekly"})
    interpret_audience("people who train", pack(audiences=[]), catalog=fixture(), inference=fake)
    assert fake.calls
    messages = json.loads(fake.calls[0])
    user = json.loads(next(message["content"] for message in messages if message["role"] == "user"))
    assert user["description"] == "people who train"
    offered = {entry["attribute"] for entry in user["attributes"]}
    assert "exercise_frequency" in offered
    assert "eye_colour" not in offered
    entry = next(entry for entry in user["attributes"] if entry["attribute"] == "exercise_frequency")
    assert entry["values"] == ["rarely", "weekly", "3_plus_weekly"]
    assert set(entry["carrying"]) == {"gss", "amazon", "synthetic"}


def test_a_filter_on_an_unknown_attribute_is_refused_with_the_permitted_vocabulary():
    with pytest.raises(ValueError, match=r"eye_colour.*does not declare"):
        interpret_audience("brown-eyed people", pack(audiences=[]), catalog=fixture(), inference=fake_returning({"eye_colour": "brown"}))


def test_a_filter_no_admissible_source_carries_is_refused_with_its_coverage():
    with pytest.raises(ValueError, match=r"diet_protein_focus.*coverage"):
        interpret_audience("high protein dieters", pack(audiences=[]), catalog=sparse(), inference=fake_returning({"diet_protein_focus": "high"}))


def test_an_attribute_absent_from_every_source_is_refused_with_its_coverage():
    with pytest.raises(ValueError, match=r"spend_band.*coverage"):
        interpret_audience("big spenders", pack(audiences=[]), catalog=fixture(), inference=fake_returning({"spend_band": "10_20"}))


def test_a_value_outside_the_vocabulary_is_refused_rather_than_coerced():
    with pytest.raises(ValueError, match=r"daily.*not one of the attribute's values"):
        interpret_audience("daily trainers", pack(audiences=[]), catalog=fixture(), inference=fake_returning({"exercise_frequency": "daily"}))


def test_a_band_range_is_accepted_when_both_bounds_are_values():
    audience = interpret_audience(
        "people who train at least weekly",
        pack(audiences=[]),
        catalog=fixture(),
        inference=fake_returning({"exercise_frequency": {"range": ["weekly", "3_plus_weekly"]}}),
    )
    assert audience.attribute_filters["exercise_frequency"] == BandRange(first="weekly", last="3_plus_weekly")


def test_a_range_bound_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError, match="not one of the attribute's values"):
        interpret_audience(
            "people who train at least daily",
            pack(audiences=[]),
            catalog=fixture(),
            inference=fake_returning({"exercise_frequency": {"range": ["daily", "3_plus_weekly"]}}),
        )