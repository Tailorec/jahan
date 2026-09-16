"""Phase 7: seeds, structured output and repair. What a pin's declared capabilities change about a
request, and how a response becomes trustworthy — parse leniently, validate, repair once, refuse
otherwise."""

import hashlib
import json

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.inference._parsing import coerce_json, validate_schema
from simcore.inference._wire import body_bytes, derive_seed
from simcore.schemas import (
    CallFailure,
    ChatRequest,
    Completion,
    FailureKind,
    FrozenDict,
    InferenceRole,
    ModelPin,
    ModelPins,
    SampleKey,
)
from tests.boundary.inference.test_scale import FakeTime, TIER_A, ask

OBJECT_SCHEMA = json.dumps({"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}})
PIN_HONOURING = ModelPins.model_validate({"tier_a": {"model_id": TIER_A, "honours_seed": True}, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"})
PIN_STRUCTURED = ModelPins.model_validate({"tier_a": {"model_id": TIER_A, "structured_output": True}, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"})
PIN_BARE = ModelPins.model_validate({"tier_a": TIER_A, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"})


def answer(content: str, model: str = TIER_A) -> bytes:
    return json.dumps({"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}).encode()


def client_with(pins: ModelPins, handler, **settings) -> tuple[InferenceClient, FakeTime]:
    time = FakeTime()
    return InferenceClient(
        pins,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=1, **settings),
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    ), time


def sampled(template_id: str = "persona_turn", **overrides) -> ChatRequest:
    payload = {
        "role": InferenceRole.TIER_A,
        "messages": (FrozenDict({"role": "user", "content": "how would you rate it?"}),),
        "temp": 0.9,
        "max_tokens": 16,
        "template_id": template_id,
        "sample": SampleKey(world_seed=4021, persona_id="p-7", tick=3, seq=2),
    }
    payload.update(overrides)
    return ChatRequest.model_validate(payload)


# --- seeds -------------------------------------------------------------------------------------------


def test_a_seed_honouring_pin_is_sent_a_seed_derived_from_the_draw_and_the_seed_is_recorded():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=answer("4"))

    client, _ = client_with(PIN_HONOURING, handler)
    outcome = client.complete([sampled()])[0]
    expected = derive_seed(sampled().sample)
    assert seen[0]["seed"] == expected
    assert isinstance(outcome, Completion) and outcome.seed == expected


def test_the_seed_follows_the_draw_not_the_message():
    seeds = {
        derive_seed(SampleKey(world_seed=seed, persona_id="p-1", tick=0, seq=0))
        for seed in (4021, 917731)
    } | {
        derive_seed(SampleKey(world_seed=4021, persona_id="p-1", tick=t, seq=0))
        for t in (0, 1, 2)
    }
    assert len(seeds) == 4  # different world, tick or sequence, different seed
    assert derive_seed(SampleKey(world_seed=4021, persona_id="p-1", tick=0, seq=0)) == derive_seed(SampleKey(world_seed=4021, persona_id="p-1", tick=0, seq=0))


def test_a_pin_that_does_not_honour_seeds_is_sent_no_seed():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=answer("4"))

    client, _ = client_with(PIN_BARE, handler)
    outcome = client.complete([sampled()])[0]
    assert "seed" not in seen[0]
    assert outcome.seed is None  # determinism is never promised, only recorded where it was asked for


# --- structured output --------------------------------------------------------------------------------


def test_a_structured_output_pin_receives_a_strict_schema():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=answer('{"answer": "yes"}'))

    client, _ = client_with(PIN_STRUCTURED, handler)
    client.complete([sampled(json_schema=OBJECT_SCHEMA)])
    format_ = seen[0]["response_format"]
    assert format_["type"] == "json_schema"
    assert format_["json_schema"]["strict"] is True
    assert format_["json_schema"]["schema"] == json.loads(OBJECT_SCHEMA)


def test_a_pin_without_the_capability_is_never_sent_a_response_format():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=answer("yes"))

    client, _ = client_with(PIN_BARE, handler)
    client.complete([sampled(json_schema=OBJECT_SCHEMA)])
    assert "response_format" not in seen[0]


# --- parse leniently, validate, repair once, otherwise refuse ------------------------------------------------


def test_leniently_parseable_output_is_accepted_after_validation():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=answer('Sure! Here it is:\n```json\n{"answer": "yes"}\n```\nHope that helps.'))

    client, _ = client_with(PIN_BARE, handler)
    outcome = client.complete([sampled(json_schema=OBJECT_SCHEMA)])[0]
    assert isinstance(outcome, Completion)  # prose and fences are the ordinary behaviour of small models


def test_output_that_fails_validation_is_repaired_once_and_accepted():
    state = {"n": 0, "bodies": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        body = json.loads(request.content)
        state["bodies"].append(body)
        if state["n"] == 1:
            return httpx.Response(200, content=answer('{"answer": 42}'))  # a number where a string belongs
        return httpx.Response(200, content=answer('{"answer": "forty-two"}'))

    client, _ = client_with(PIN_BARE, handler)
    outcome = client.complete([sampled(json_schema=OBJECT_SCHEMA)])[0]
    assert isinstance(outcome, Completion) and outcome.text == '{"answer": "forty-two"}'
    assert state["n"] == 2
    stricter = state["bodies"][1]["messages"][-1]
    assert stricter["role"] == "user" and "failed validation" in stricter["content"]
    roles = [message["role"] for message in state["bodies"][1]["messages"]]
    # Strict chat templates refuse a system message anywhere but the start; a real endpoint answered 400.
    assert "system" not in roles[roles.index("assistant"):]
    assert outcome.prompt_hash == hashlib.sha256(body_bytes(state["bodies"][1])).hexdigest()  # the accepted attempt's hash is the repaired request's own bytes


def test_output_still_invalid_after_repair_is_an_invalid_output_failure_never_a_coerced_value():
    state = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(200, content=answer("I think it's nice!"))  # never JSON, twice

    client, _ = client_with(PIN_BARE, handler)
    outcome = client.complete([sampled(json_schema=OBJECT_SCHEMA)])[0]
    assert isinstance(outcome, CallFailure) and outcome.kind is FailureKind.INVALID_OUTPUT
    assert state["n"] == 2  # asked once, repaired once, refused once — no third attempt


def test_a_validated_completion_is_the_one_the_cache_will_replay(tmp_path):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, content=answer('{"answer": 7}'))
        return httpx.Response(200, content=answer('{"answer": "seven"}'))

    root = tmp_path
    first_client, _ = client_with(PIN_BARE, handler, cache_dir=root)
    warm = first_client.complete([sampled(json_schema=OBJECT_SCHEMA, template_id="t7")])[0]
    calls["n"] = 0
    replay, _ = client_with(PIN_BARE, handler, cache_dir=root)
    hit = replay.complete([sampled(json_schema=OBJECT_SCHEMA, template_id="t7")])[0]
    assert isinstance(warm, Completion) and isinstance(hit, Completion)
    assert hit.text == warm.text == '{"answer": "seven"}'
    assert calls["n"] == 0  # the cache replays the repaired answer, not the refused original


# --- the salvage functions in their own right ------------------------------------------------------------


def test_coerce_json_recovers_objects_arrays_and_refuses_prose():
    assert coerce_json('{"a": 1}') == {"a": 1}
    assert coerce_json('text ["b", 2] more') == ["b", 2]
    with pytest.raises(ValueError):
        coerce_json("no json at all")


def test_validate_schema_states_its_disagreements():
    assert validate_schema({"answer": "x"}, json.loads(OBJECT_SCHEMA)) == []
    errors = validate_schema({"answer": 7, "extra": 1}, json.loads(OBJECT_SCHEMA))
    assert any("string" in error for error in errors)
