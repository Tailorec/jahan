"""Phase 2: one model call through the real client, end to end, proven against a scripted transport.

A role resolves to its pin or the call is refused before any byte leaves; the request is serialized
once, hashed, and sent as exactly those bytes; the completion records its latency, tokens, served
model and cost with its source; and a model outside the pin's accepted identifiers comes back as a
pin failure rather than a result."""

import hashlib
import json

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient, UnpinnedRoleError
from simcore.schemas import (
    CallFailure,
    FrozenDict,
    ChatRequest,
    Completion,
    CostSource,
    FailureKind,
    InferenceRole,
    InferenceRoute,
    ModelPins,
    SampleKey,
)

TIER_A = "openrouter/camel-ai/persona-8b"
TIER_B = "anthropic/claude-sonnet-4-5-20250929"
EMBED = "openai/text-embedding-3-small"

PINS = ModelPins.model_validate({"tier_a": TIER_A, "tier_b": TIER_B, "embed": EMBED})


def chat_request(**overrides) -> ChatRequest:
    payload = {
        "role": InferenceRole.TIER_A,
        "messages": (FrozenDict({"role": "user", "content": "would you buy it?"}),),
        "temp": 0.0,
        "max_tokens": 64,
        "template_id": "persona_turn",
    }
    payload.update(overrides)
    return ChatRequest.model_validate(payload)


def completion_json(model: str, text: str = "probably yes", *, usage: dict | None = None, extra: dict | None = None) -> str:
    payload: dict = {"model": model, "choices": [{"message": {"role": "assistant", "content": text}}]}
    if usage is not None:
        payload["usage"] = usage
    payload.update(extra or {})
    return json.dumps(payload)


class Script:
    """A scripted transport: replies to each request in order, recording what was sent."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.sent: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            reply = self.replies.pop(0) if self.replies else (200, completion_json(TIER_A))
            status, body = reply if isinstance(reply, tuple) else (200, reply)
            headers = {}
            if status == 429:
                headers["retry-after"] = "2"
            return httpx.Response(status, content=body.encode("utf-8") if isinstance(body, str) else body, headers=headers)

        return httpx.MockTransport(handler)


class Clock:
    """A monotonic clock that advances a fixed step per read: latency becomes scripted arithmetic."""

    def __init__(self, step: float = 0.5) -> None:
        self.now = 1_000.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


TICKING_CLOCK = Clock()


def client(script: Script, pins: ModelPins = PINS, **settings) -> InferenceClient:
    return InferenceClient(
        pins,
        ExecutionSettings(base_url="http://gateway.test/v1", **settings),
        transport=script.transport(),
        clock=TICKING_CLOCK,
    )


def ok(model: str = TIER_A, **usage) -> str:
    return completion_json(model, usage={"prompt_tokens": 120, "completion_tokens": 7, **usage})


# --- resolution before spending -------------------------------------------------------------------


def test_an_unpinned_role_is_refused_before_any_request_is_sent():
    script = Script(ok())
    with pytest.raises(UnpinnedRoleError, match="safety"):
        client(script).chat(InferenceRole.SAFETY, [{"role": "user", "content": "moderate this"}], temp=0.0, max_tokens=8, template_id="moderation")
    assert script.sent == []


def test_an_unpinned_role_is_refused_when_it_hides_inside_a_batch():
    script = Script(ok(), ok())
    with pytest.raises(UnpinnedRoleError):
        client(script).complete([chat_request(), chat_request(role=InferenceRole.SAFETY)])
    assert script.sent == []


# --- the bytes sent are the bytes hashed ------------------------------------------------------------


def test_the_prompt_hash_is_computed_from_exactly_the_bytes_sent():
    script = Script(ok())
    outcome = client(script).complete([chat_request()])[0]
    assert isinstance(outcome, Completion)
    assert outcome.prompt_hash == hashlib.sha256(script.sent[0].content).hexdigest()


def test_the_request_is_sent_once_serialized_to_the_endpoint_path_it_advertises():
    script = Script(ok())
    outcome = client(script).complete([chat_request()])[0]
    request = script.sent[0]
    assert request.url.path == "/v1/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == TIER_A
    assert body["messages"] == [{"role": "user", "content": "would you buy it?"}]
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"messages": (FrozenDict({"role": "user", "content": "would you try it?"}),)},
        {"temp": 0.5, "sample": SampleKey(world_seed=1, persona_id="p-1")},
        {"max_tokens": 128},
        {"role": InferenceRole.TIER_B},
    ],
    ids=["one-word-difference", "temperature", "budget", "role"],
)
def test_changing_any_request_field_changes_the_prompt_hash(overrides):
    script = Script(ok(TIER_A), ok(TIER_B if overrides.get("role") == InferenceRole.TIER_B else TIER_A))
    c = client(script)
    outcomes = c.complete([chat_request(), chat_request(**overrides)])
    assert all(isinstance(outcome, Completion) for outcome in outcomes)
    assert outcomes[0].prompt_hash != outcomes[1].prompt_hash


def test_the_name_sent_is_the_pin_and_identical_requests_hash_alike():
    script = Script(ok(TIER_B), ok(TIER_B))
    c = client(script, pins=ModelPins.model_validate({"tier_a": {"model_id": TIER_B, "serves": [TIER_B]}, "tier_b": TIER_B, "embed": EMBED}))
    outcomes = c.complete([chat_request(), chat_request()])
    assert json.loads(script.sent[0].content)["model"] == TIER_B
    assert outcomes[0].prompt_hash == outcomes[1].prompt_hash  # identical requests still hash alike


# --- what a completion records ------------------------------------------------------------------------


def test_a_completion_records_served_model_tokens_latency_and_its_route():
    script = Script(ok(TIER_A))
    outcome = client(script).complete([chat_request()])[0]
    assert isinstance(outcome, Completion)
    assert outcome.text == "probably yes"
    assert outcome.cost.served_model_id == TIER_A
    assert (outcome.cost.input_tokens, outcome.cost.output_tokens) == (120, 7)
    assert outcome.latency_ms == 500
    assert outcome.cost.route is InferenceRoute.PRIMARY


def test_tokens_are_estimated_when_the_response_reports_no_usage():
    script = Script(completion_json(TIER_A))
    outcome = client(script).complete([chat_request()])[0]
    assert outcome.cost.input_tokens >= 1 and outcome.cost.output_tokens >= 1
    assert outcome.cost.cost_source is CostSource.UNKNOWN  # estimation never pretends to bill


# --- a cost says where it came from -------------------------------------------------------------------


def test_a_gateway_reported_cost_is_recorded_as_gateway():
    script = Script(completion_json(TIER_A, usage={"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0035}))
    outcome = client(script).complete([chat_request()])[0]
    assert outcome.cost.cost_source is CostSource.GATEWAY and outcome.cost.cost == 0.0035


def test_a_cost_reported_only_in_a_gateway_header_is_still_gateway():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=completion_json(TIER_A, usage={"prompt_tokens": 10, "completion_tokens": 2}).encode(), headers={"x-litellm-response-cost": "0.002"})

    c = InferenceClient(PINS, ExecutionSettings(base_url="http://gateway.test/v1"), transport=httpx.MockTransport(handler), clock=TICKING_CLOCK)
    outcome = c.complete([chat_request()])[0]
    assert outcome.cost.cost_source is CostSource.GATEWAY and outcome.cost.cost == 0.002


def test_a_declared_price_computes_a_price_table_cost():
    priced = ModelPins.model_validate(
        {"tier_a": {"model_id": TIER_A, "serves": [TIER_A], "price": {"input_per_million": 1.0, "output_per_million": 2.0}}, "tier_b": TIER_B, "embed": EMBED}
    )
    script = Script(ok())
    outcome = client(script, pins=priced).complete([chat_request()])[0]
    assert outcome.cost.cost_source is CostSource.PRICE_TABLE
    assert outcome.cost.cost == pytest.approx((120 * 1.0 + 7 * 2.0) / 1_000_000)


def test_neither_reported_nor_priced_is_recorded_as_unknown_never_as_zero():
    script = Script(ok())
    outcome = client(script).complete([chat_request()])[0]
    assert outcome.cost.cost_source is CostSource.UNKNOWN
    assert outcome.cost.cost is None


# --- a pin is a specification -------------------------------------------------------------------------


def test_a_response_served_by_an_undeclared_model_is_a_pin_failure():
    script = Script(ok("quantized/knife-edge-1.3b"))
    outcome = client(script).complete([chat_request()])[0]
    assert isinstance(outcome, CallFailure)
    assert outcome.kind is FailureKind.PIN_FAILURE
    assert outcome.route is InferenceRoute.PRIMARY
    assert "knife-edge" in outcome.detail


def test_a_response_served_by_a_declared_alias_is_a_completion():
    aliased = ModelPins.model_validate(
        {"tier_a": {"model_id": "vllm/persona-8b", "serves": ["vllm/persona-8b", "camel-ai/persona-mistral-8b-it-v1"]}, "tier_b": TIER_B, "embed": EMBED}
    )
    script = Script(ok("camel-ai/persona-mistral-8b-it-v1"))
    outcome = client(script, pins=aliased).complete([chat_request()])[0]
    assert isinstance(outcome, Completion)
    assert outcome.cost.served_model_id == "camel-ai/persona-mistral-8b-it-v1"
    assert outcome.cost.model_id == "vllm/persona-8b"


def test_a_served_model_that_changes_mid_run_is_caught_on_the_first_call_it_changes():
    script = Script(ok(TIER_A), ok(TIER_A), ok("substituted/other"), ok(TIER_A))
    c = client(script)
    outcomes = c.complete([chat_request()] * 4)
    assert isinstance(outcomes[0], Completion) and isinstance(outcomes[1], Completion)
    assert isinstance(outcomes[2], CallFailure) and outcomes[2].kind is FailureKind.PIN_FAILURE
    assert isinstance(outcomes[3], Completion)


def test_a_response_that_names_no_model_is_a_pin_failure_not_an_unnamed_result():
    script = Script(json.dumps({"choices": [{"message": {"role": "assistant", "content": "sure"}}]}))
    outcome = client(script).complete([chat_request()])[0]
    assert isinstance(outcome, CallFailure) and outcome.kind is FailureKind.PIN_FAILURE


# --- the engine owns the protocol ----------------------------------------------------------------------

BANNED_IMPORTS = ("openai", "anthropic", "litellm", "boto3", "botocore", "azure", "langchain", "llama_index", "mistralai", "cohere", "google.genai")


def test_the_engine_imports_no_provider_sdk_or_gateway_library():
    import sys

    import simcore.inference  # noqa: F401

    roots = {banned.split(".")[0] for banned in BANNED_IMPORTS}
    offenders = sorted(name for name in sys.modules if name.split(".")[0] in roots)
    assert offenders == []


def test_no_source_file_in_the_package_names_a_provider_import():
    import re
    from pathlib import Path

    pattern = re.compile(rf"^\s*(?:from|import)\s+({'|'.join(re.escape(b) for b in BANNED_IMPORTS)})(?:[.\s]|$)", re.MULTILINE)
    package = Path("simcore")
    offenders = [str(path) for path in package.rglob("*.py") if pattern.search(path.read_text())]
    assert offenders == []
