import pytest
from pydantic import ValidationError

from simcore.schemas import (
    CallFailure,
    Completion,
    CostRecorded,
    CostSource,
    FailureKind,
    InferenceRole,
    InferenceRoute,
    ModelPin,
    ModelPins,
    PinPrice,
)
from tests.study_builders import events_of_representative_cost


def completion(**overrides) -> dict:
    payload = {
        "text": "I would probably try it after training.",
        "template_id": "persona_turn",
        "prompt_hash": "12" * 32,
        "latency_ms": 840,
        "cost": events_of_representative_cost(),
    }
    payload.update(overrides)
    return payload


def cost(**overrides) -> dict:
    payload = {
        "kind": "cost",
        "role": "tier_a",
        "model_id": "openrouter/camel-ai/persona-8b",
        "served_model_id": "openrouter/camel-ai/persona-8b",
        "cost_source": "gateway",
        "route": "primary",
        "input_tokens": 812,
        "output_tokens": 96,
        "cost": 0.004,
    }
    payload.update(overrides)
    return payload


def test_completion_carries_text_template_prompt_hash_latency_and_its_cost_record():
    parsed = Completion.model_validate(completion())
    assert (parsed.text, parsed.template_id, parsed.prompt_hash, parsed.latency_ms) == (
        "I would probably try it after training.", "persona_turn", "12" * 32, 840)
    assert isinstance(parsed.cost, CostRecorded) and parsed.cost.kind == "cost"
    assert Completion.model_validate_json(parsed.model_dump_json()) == parsed


def test_the_cost_record_is_the_one_the_trace_receives():
    parsed = Completion.model_validate(completion())
    assert CostRecorded.model_validate(parsed.cost.model_dump(mode="json")) == parsed.cost


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"latency_ms": -1}, "latency_ms"),
        ({"prompt_hash": "not-a-hash"}, "prompt_hash"),
        ({"cost": cost(role="embed", model_id="openai/text-embedding-3-small", served_model_id="openai/text-embedding-3-small")}, "vectors, not completions"),
    ],
    ids=["negative-latency", "malformed-prompt-hash", "embedding-role"],
)
def test_completion_refuses_what_a_chat_call_cannot_return(overrides, match):
    with pytest.raises(ValidationError, match=match):
        Completion.model_validate(completion(**overrides))


def test_an_empty_response_is_still_a_completion():
    assert Completion.model_validate(completion(text="")).text == ""


# --- a pin is a specification -------------------------------------------------------------------


def test_a_bare_model_identifier_reads_as_a_pin_accepting_only_itself():
    pin = ModelPin.model_validate("openrouter/camel-ai/persona-8b")
    assert pin.model_id == "openrouter/camel-ai/persona-8b"
    assert pin.serves == {"openrouter/camel-ai/persona-8b"}
    assert pin.structured_output is False and pin.honours_seed is False
    assert pin.price is None


def test_a_pin_carries_the_name_sent_its_served_identifiers_capabilities_and_price():
    pin = ModelPin.model_validate(
        {
            "model_id": "litellm/persona-8b",
            "serves": ["litellm/persona-8b", "camel-ai/persona-mistral-8b-it-v1"],
            "structured_output": True,
            "honours_seed": True,
            "price": {"input_per_million": 0.10, "output_per_million": 0.20},
        }
    )
    assert pin.serves == {"litellm/persona-8b", "camel-ai/persona-mistral-8b-it-v1"}
    assert pin.structured_output and pin.honours_seed
    assert isinstance(pin.price, PinPrice) and pin.price.input_per_million == 0.10
    assert ModelPins.model_validate(
        {"tier_a": pin, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"}
    ).tier_a == pin


def test_a_pin_that_would_not_answer_to_its_own_name_is_refused():
    with pytest.raises(ValidationError, match="its own name"):
        ModelPin.model_validate({"model_id": "litellm/persona-8b", "serves": ["someone/else"]})


def test_the_embedding_role_still_refuses_a_fallback():
    with pytest.raises(ValidationError, match="never falls back"):
        ModelPins.model_validate(
            {
                "tier_a": "openrouter/camel-ai/persona-8b",
                "tier_b": "anthropic/claude-sonnet-4-5-20250929",
                "embed": {"model_id": "openai/text-embedding-3-small", "serves": ["openai/text-embedding-3-small", "text-embedding-3-small"]},
                "fallbacks": {"embed": "openai/text-embedding-3-large"},
            }
        )


def test_a_fallback_identical_to_its_primary_is_refused_even_through_another_name():
    with pytest.raises(ValidationError, match="is its primary model"):
        ModelPins.model_validate(
            {
                "tier_a": "openrouter/camel-ai/persona-8b",
                "tier_b": "anthropic/claude-sonnet-4-5-20250929",
                "embed": "openai/text-embedding-3-small",
                "fallbacks": {"tier_a": {"model_id": "openrouter/camel-ai/persona-8b", "serves": ["openrouter/camel-ai/persona-8b", "camel-ai/persona-mistral-8b-it-v1"]}},
            }
        )


# --- a cost says where it came from -------------------------------------------------------------


def test_a_cost_records_the_served_model_beside_the_pinned_one_and_its_source():
    parsed = CostRecorded.model_validate(cost())
    assert parsed.model_id == "openrouter/camel-ai/persona-8b"
    assert parsed.served_model_id == "openrouter/camel-ai/persona-8b"
    assert parsed.cost_source is CostSource.GATEWAY
    assert CostRecorded.model_validate_json(parsed.model_dump_json()) == parsed


def test_an_unknown_cost_is_recorded_as_absent_never_as_zero():
    parsed = CostRecorded.model_validate(cost(cost_source="unknown", cost=None))
    assert parsed.cost is None and parsed.cost_source is CostSource.UNKNOWN


@pytest.mark.parametrize(
    "overrides",
    [
        {"cost_source": "unknown"},  # an unknown cost that still carries a number
        {"cost": None},  # a known source with no number
        {"cost_source": "price_table", "cost": None},
    ],
    ids=["unknown-with-a-number", "gateway-without-a-number", "price-table-without-a-number"],
)
def test_a_contradiction_between_a_cost_and_its_source_is_refused(overrides):
    with pytest.raises(ValidationError, match="absent"):
        CostRecorded.model_validate(cost(**overrides))


@pytest.mark.parametrize(
    ("route", "served", "valid"),
    [("primary", "openrouter/camel-ai/persona-8b", True), ("primary", None, False), ("fallback", None, False), ("cache", None, True)],
    ids=["primary-names-its-server", "primary-names-none", "fallback-names-none", "cache-may-name-none"],
)
def test_a_call_on_a_model_route_records_which_model_served_it(route, served, valid):
    payload = cost(route=route, served_model_id=served)
    if route == "cache":
        payload["cost"] = 0.0
    if valid:
        assert CostRecorded.model_validate(payload).route.value == route
    else:
        with pytest.raises(ValidationError, match="served"):
            CostRecorded.model_validate(payload)


def test_a_cached_call_still_bills_nothing():
    assert CostRecorded.model_validate(cost(route="cache", cost=0.0)).cache_hit is True
    with pytest.raises(ValidationError, match="bills nothing"):
        CostRecorded.model_validate(cost(route="cache", cost=0.004))


# --- a failed call is an outcome ----------------------------------------------------------------


def test_a_call_failure_names_its_kind_its_attempts_and_its_last_route():
    failure = CallFailure(
        kind=FailureKind.RATE_LIMITED,
        detail="429 on every attempt",
        attempts=4,
        route=InferenceRoute.FALLBACK,
    )
    assert failure.kind is FailureKind.RATE_LIMITED and failure.attempts == 4
    assert failure.route is InferenceRoute.FALLBACK
    assert CallFailure.model_validate_json(failure.model_dump_json()) == failure


@pytest.mark.parametrize(
    "kind",
    ["rate_limited", "timed_out", "fatal_response", "circuit_open", "pin_failure", "invalid_output", "exceeds_rate_limit"],
)
def test_the_closed_set_of_failure_kinds(kind):
    assert CallFailure(kind=kind, detail="x", attempts=1, route="primary").kind is FailureKind(kind)


@pytest.mark.parametrize(
    "overrides",
    [{"attempts": -1}, {"detail": ""}, {"kind": "provider_sadness"}],
    ids=["negative-attempts", "wordless-failure", "unknown-kind"],
)
def test_a_call_failure_refuses_an_ungrounded_record(overrides):
    payload = {"kind": "timed_out", "detail": "gave up", "attempts": 2, "route": "primary"}
    payload.update(overrides)
    with pytest.raises(ValidationError):
        CallFailure.model_validate(payload)
