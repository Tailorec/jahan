"""Projection: rows become personas, and a model may only choose values the corpus already holds."""

import copy
import json
import math

import pytest

from simcore.population._project import COMPLETION_BATCH_SIZE, COMPLETION_RETRY_SYSTEM, COMPLETION_TEMPLATE_ID, project
from simcore.ports.coreset import DecodedRow
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, FieldOrigin, GateFailure, Persona, canonical_hash
from tests.study_builders import load_fixture, load_ontology, pack_payload

MODEL = "openrouter/camel-ai/persona-8b"
FALLBACK = "openrouter/qwen/qwen-2.5-7b-instruct"


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


def missing_count(rows, attribute: str) -> int:
    return sum(1 for row in rows if attribute not in row.values)


def asked(call: str) -> dict:
    return json.loads(json.loads(call)[-1]["content"])


def off_list_responder(messages, template_id) -> str:
    request = json.loads(messages[-1]["content"])
    return json.dumps({persona["persona_id"]: "invented" for persona in request["personas"]})


def test_every_projected_field_states_an_origin():
    source = synthetic()
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    for persona in projection.personas:
        assert set(persona.origins) == persona.projected_attributes
    with pytest.raises(Exception):
        Persona.model_validate(
            {
                "persona_id": "p-000001",
                "source": "synthetic",
                "conditioning": {"age": "25_34"},
                "attributes": {"spend_band": "5_10"},
                "origins": {"age": "measured"},
                "baseline_beliefs": {"dimensions": {"value": 0.5, "fit": 0.5, "trust": 0.5}, "claim_credence": {"C1": 0.5}},
            }
        )


def test_projection_defaults_a_corpus_field_to_measured_and_honours_a_rows_tier():
    source = synthetic(diet_populated=1.0, spend_populated=1.0)
    brief = pack()
    rows = rows_of(source, brief)[:10]
    projected = project(brief, rows, source, inference=FakeChat(model_id=MODEL))
    assert all(origin is FieldOrigin.MEASURED for persona in projected.personas for origin in persona.origins.values())

    first = rows[0]
    attribute = next(iter(first.values))
    tiered = DecodedRow(row_id=first.row_id, source=first.source, values=first.values, tiers={attribute: FieldOrigin.EXTRACTED})
    extracted = project(brief, [tiered], source, inference=FakeChat(model_id=MODEL))
    assert extracted.personas[0].origins[attribute] is FieldOrigin.EXTRACTED


def test_completion_chooses_from_the_corpus_value_set():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    completed = [persona for persona in projection.personas if "spend_band" in persona.origins and persona.origins["spend_band"] is FieldOrigin.SYNTHESIZED]
    assert completed
    assert all(persona.attributes["spend_band"] in source.values("spend_band") for persona in completed)


def test_an_off_list_answer_is_retried_once_then_the_field_is_left_absent():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    fake = FakeChat(off_list_responder)
    projection = project(brief, rows_of(source, brief), source, inference=fake)
    assert projection.completion is None and projection.synthesized_share == 0.0
    assert all(persona.origins.get("spend_band") is not FieldOrigin.SYNTHESIZED for persona in projection.personas)
    assert any("spend_band" not in persona.origins for persona in projection.personas)
    batches = math.ceil(missing_count(rows_of(source, brief), "spend_band") / COMPLETION_BATCH_SIZE)
    assert len(fake.calls) == 2 * batches  # each batch: one attempt, one stricter retry


def test_no_demographic_or_psychographic_field_is_synthesized():
    source = synthetic(diet_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    assert any("diet_protein_focus" not in persona.origins for persona in projection.personas)
    assert all(
        persona.origins.get("diet_protein_focus") is not FieldOrigin.SYNTHESIZED for persona in projection.personas
    )


def test_completion_is_batched_rather_than_one_call_per_persona():
    source = synthetic(rows=400, spend_populated=0.3)
    brief = pack()
    fake = FakeChat()
    projection = project(brief, rows_of(source, brief), source, inference=fake)
    completed = [persona for persona in projection.personas if persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED]
    assert len(completed) > 20
    missing = missing_count(rows_of(source, brief), "spend_band")
    assert len(fake.calls) == math.ceil(missing / COMPLETION_BATCH_SIZE) < missing
    assert all(len(asked(call)["personas"]) <= COMPLETION_BATCH_SIZE for call in fake.calls)


def test_the_projection_records_the_completing_model_template_and_synthesized_share():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    assert projection.completion.model_id == MODEL
    assert projection.completion.template_id == COMPLETION_TEMPLATE_ID
    assert len(projection.completion.template_hash) == 64
    assert 0.0 < projection.synthesized_share < 1.0


def test_projecting_the_same_sample_twice_produces_identical_personas():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    rows = rows_of(source, brief)
    first = project(brief, rows, source, inference=FakeChat(model_id=MODEL))
    second = project(brief, rows, source, inference=FakeChat(model_id=MODEL))
    assert canonical_hash(first.personas[0]) == canonical_hash(second.personas[0])
    assert [canonical_hash(persona) for persona in first.personas] == [canonical_hash(persona) for persona in second.personas]


def test_a_sample_needing_no_completion_calls_no_model():
    source = synthetic(diet_populated=1.0, spend_populated=1.0)
    brief = pack()
    fake = FakeChat()
    projection = project(brief, rows_of(source, brief), source, inference=fake)
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
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    assert any("income" not in persona.origins for persona in projection.personas)


def test_a_large_population_completes_within_the_answer_budget_it_is_given():
    """Two thousand personas in one call once needed a ten-thousand-token answer under a limit of 1024;
    against a fake that cuts answers off at their budget, as a provider does, batching completes them all."""
    source = synthetic(rows=2000, spend_populated=0.3)
    brief = pack()
    rows = rows_of(source, brief)
    projection = project(brief, rows, source, inference=FakeChat(model_id=MODEL))
    completed = sum(1 for persona in projection.personas if persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED)
    assert completed == missing_count(rows, "spend_band") > 1000


def test_a_retry_asks_only_about_the_personas_still_missing_and_keeps_accepted_answers():
    requests: list[dict] = []

    def half_wrong_then_right(messages, template_id) -> str:
        request = json.loads(messages[-1]["content"])
        requests.append(request)
        strict = messages[0]["content"] == COMPLETION_RETRY_SYSTEM
        return json.dumps({
            persona["persona_id"]: (request["values"][0] if strict or index % 2 == 0 else "invented")
            for index, persona in enumerate(request["personas"])
        })

    source = synthetic(rows=40, spend_populated=0.0)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(half_wrong_then_right))
    first, retry = requests[0], requests[1]
    assert len(retry["personas"]) == len(first["personas"]) // 2
    assert {p["persona_id"] for p in retry["personas"]} == {p["persona_id"] for index, p in enumerate(first["personas"]) if index % 2}
    assert all(persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED for persona in projection.personas)


def integer_coded(rows: int = 60) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "high")),
                "spend_band": AttributeShape((5, 10, 20), populated=0.0),
            },
            rows=rows,
        ),
        seed=3,
    )


def test_an_integer_coded_vocabulary_is_completed_with_its_own_integers():
    """A correct answer to an integer-coded attribute was once refused for being spelled as text."""
    source = integer_coded()
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=MODEL))
    completed = [persona.attributes["spend_band"] for persona in projection.personas if persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED]
    assert len(completed) == len(projection.personas)
    assert all(value == 5 and type(value) is int for value in completed)


def test_a_number_is_matched_by_its_value_and_an_off_list_number_is_refused():
    source = integer_coded()
    brief = pack()
    rows = rows_of(source, brief)
    off_list = {f"p-{row.row_id}" for index, row in enumerate(rows) if index % 2}

    def spelled_or_invented(messages, template_id) -> str:
        request = json.loads(messages[-1]["content"])
        return json.dumps({persona["persona_id"]: (7 if persona["persona_id"] in off_list else " 10.0") for persona in request["personas"]})

    projection = project(brief, rows, source, inference=FakeChat(spelled_or_invented))
    for persona in projection.personas:
        if persona.persona_id in off_list:
            assert "spend_band" not in persona.origins
        else:
            assert persona.attributes["spend_band"] == 10 and type(persona.attributes["spend_band"]) is int


class RoutedChat(FakeChat):
    """A chat whose completions are served by whichever model `route` names for each call."""

    def __init__(self, route, responder=None) -> None:
        super().__init__(responder)
        self._route = route
        self.served = 0

    def chat(self, role, messages, **kwargs):
        completion = super().chat(role, messages, **kwargs)
        self.served += 1
        model = self._route(self.served, messages)
        return completion.model_copy(update={"cost": completion.cost.model_copy(update={"model_id": model})})


def test_provenance_records_the_model_that_answered_not_the_one_expected():
    """A completion served by the fallback was once recorded as the primary the caller had named."""
    source = synthetic(spend_populated=0.5)
    brief = pack()
    projection = project(brief, rows_of(source, brief), source, inference=FakeChat(model_id=FALLBACK))
    assert projection.completion.model_id == FALLBACK


def test_fields_completed_by_more_than_one_model_are_refused():
    source = synthetic(spend_populated=0.5)
    brief = pack()
    alternating = RoutedChat(lambda served, messages: MODEL if served % 2 else FALLBACK)
    with pytest.raises(GateFailure, match="more than one model"):
        project(brief, rows_of(source, brief), source, inference=alternating)


def test_a_model_whose_answers_were_all_refused_is_not_recorded_as_completing_anything():
    def invented_then_valid(messages, template_id) -> str:
        request = json.loads(messages[-1]["content"])
        strict = messages[0]["content"] == COMPLETION_RETRY_SYSTEM
        return json.dumps({persona["persona_id"]: (request["values"][0] if strict else "invented") for persona in request["personas"]})

    source = synthetic(rows=20, spend_populated=0.0)
    brief = pack()
    retried_on_fallback = RoutedChat(
        lambda served, messages: FALLBACK if messages[0]["content"] == COMPLETION_RETRY_SYSTEM else MODEL,
        invented_then_valid,
    )
    projection = project(brief, rows_of(source, brief), source, inference=retried_on_fallback)
    assert projection.completion.model_id == FALLBACK
