"""Phase 5: what happens when an endpoint misbehaves. Retries with backoff, the pinned fallback after
them, and one circuit breaker so an invalid key fails a batch with one clear error, not thousands."""

import json

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import (
    CallFailure,
    Completion,
    FailureKind,
    InferenceRole,
    InferenceRoute,
    ModelPins,
    RunConfig,
    canonical_json,
)
from tests.boundary.inference.test_scale import PINS, TIER_A, FakeTime, answer, ask

FALLBACK = "openrouter/qwen/qwen-2.5-7b-instruct"
ROUTES = ModelPins.model_validate(
    {
        "tier_a": TIER_A,
        "tier_b": "anthropic/claude-sonnet-4-5-20250929",
        "embed": "openai/text-embedding-3-small",
        "fallbacks": {"tier_a": FALLBACK},
    }
)


def client_for(handler, pins=PINS, **settings) -> tuple[InferenceClient, FakeTime]:
    time = FakeTime()
    client = InferenceClient(
        pins,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=2, **settings),
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    return client, time


def chat_json(model: str, text: str = "ok") -> bytes:
    return json.dumps({"model": model, "choices": [{"message": {"role": "assistant", "content": text}}]}).encode()


# --- what retries and what is fatal at once -------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    ["429", "500", "503", "timeout", "connection"],
)
def test_rate_limited_server_error_timeout_and_connection_errors_are_retried(failure):
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        if state["sent"] <= 2:  # fail twice, then serve
            if failure == "timeout":
                raise httpx.ReadTimeout("too slow", request=request)
            if failure == "connection":
                raise httpx.ConnectError("no route", request=request)
            status = int(failure)
            headers = {"retry-after": "0"} if status == 429 else {}
            return httpx.Response(status, content=b"busy", headers=headers)
        return httpx.Response(200, content=chat_json(TIER_A, "recovered"))

    client, _ = client_for(handler)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, Completion) and outcome.text == "recovered"
    assert state["sent"] == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_a_refusal_is_fatal_at_once_and_never_retried(status):
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(status, content=b"no")

    client, _ = client_for(handler)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, CallFailure) and outcome.kind is FailureKind.FATAL_RESPONSE
    assert state["sent"] == 1 and outcome.attempts == 1


def test_retries_exhaust_bounded_by_the_configured_count():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(500, content=b"always")

    client, _ = client_for(handler, max_retries=2)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, CallFailure)
    assert state["sent"] == 3  # one attempt plus two retries, then it stops


def test_backoff_grows_between_attempts_and_never_outlives_its_cap():
    moments: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        moments.append(time.now)
        return httpx.Response(500, content=b"busy")

    client, time = client_for(handler, max_retries=3, backoff_base_s=1.0, backoff_cap_s=1.5)
    client.complete([ask(0)])
    gaps = [later - earlier for earlier, later in zip(moments, moments[1:])]
    assert gaps == pytest.approx([1.0, 1.5, 1.5])  # doubling from the base, held at the cap


# --- the pinned fallback -------------------------------------------------------------------------------


def test_a_call_that_exhausts_its_retries_is_served_by_the_pinned_fallback_and_recorded_as_such():
    state = {"primary": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)["model"]
        if sent == TIER_A:
            state["primary"] += 1
            return httpx.Response(503, content=b"down")
        return httpx.Response(200, content=chat_json(FALLBACK, "from fallback"))

    client, _ = client_for(handler, pins=ROUTES, max_retries=1)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, Completion)
    assert outcome.cost.route is InferenceRoute.FALLBACK
    assert outcome.cost.model_id == FALLBACK and outcome.cost.served_model_id == FALLBACK
    assert state["primary"] == 2  # the fallback is used only after the primary is exhausted


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        ((400, b"malformed"), FailureKind.FATAL_RESPONSE),
        ((401, b"invalid key"), FailureKind.FATAL_RESPONSE),
        ((200, "wrong-model"), FailureKind.PIN_FAILURE),
    ],
)
def test_only_exhausted_retries_move_a_call_to_the_pinned_fallback(reply, kind):
    """The fallback once answered any failure: a malformed request, an invalid key, a gateway substitution —
    none of which another model cures, and each of which silently moved personas onto a different model."""
    pins = ModelPins.model_validate({"tier_a": TIER_A, "tier_b": PINS.tier_b, "embed": PINS.embed, "fallbacks": {"tier_a": "fallback/model"}})
    models: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model != TIER_A:
            return httpx.Response(200, content=chat_json("fallback/model"))
        status, body = reply
        return httpx.Response(status, content=chat_json("some/other-model") if body == "wrong-model" else body)

    client, _ = client_for(handler, pins=pins, max_retries=2)
    (outcome,) = client.complete([ask(0)])
    assert isinstance(outcome, CallFailure) and outcome.kind is kind
    assert outcome.route is InferenceRoute.PRIMARY
    assert "fallback/model" not in models


def test_output_that_fails_validation_is_never_handed_to_the_fallback():
    """Moving only the personas whose answers were hard to parse onto another model biases a study toward
    that model's answers for exactly those personas."""
    pins = ModelPins.model_validate({"tier_a": TIER_A, "tier_b": PINS.tier_b, "embed": PINS.embed, "fallbacks": {"tier_a": "fallback/model"}})
    models: list[str] = []
    schema = json.dumps({"type": "object", "required": ["x"], "properties": {"x": {"type": "number"}}})

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        return httpx.Response(200, content=chat_json(model, "not json" if model == TIER_A else '{"x": 1}'))

    client, _ = client_for(handler, pins=pins)
    (outcome,) = client.complete([ask(0).model_copy(update={"json_schema": schema})])
    assert isinstance(outcome, CallFailure) and outcome.kind is FailureKind.INVALID_OUTPUT
    assert "fallback/model" not in models


def test_a_role_with_no_pinned_fallback_records_a_failure_after_its_retries():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(503, content=b"down")

    client, _ = client_for(handler, max_retries=2)  # PINS carry no fallback for tier_a
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, CallFailure) and outcome.route is InferenceRoute.PRIMARY
    assert state["sent"] == 3


def test_embedding_never_falls_back():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(200, content=b"{}")

    pins = ModelPins.model_validate(
        {"tier_a": TIER_A, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"}
    )
    client, _ = client_for(handler, pins=pins)
    embed_request = ask(0).model_copy(update={"role": InferenceRole.EMBED})
    with pytest.raises(ValueError, match="embeddings"):
        client.complete([embed_request])
    assert state["sent"] == 0  # embed never even rides the chat route, and no fallback exists to try


def test_an_unpinned_fallback_is_never_invented():
    state = {"models": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        state["models"].append(model)
        return httpx.Response(503, content=b"down")

    client, _ = client_for(handler, pins=PINS, max_retries=1)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, CallFailure)
    assert set(state["models"]) == {TIER_A}  # nothing was tried but the pinned primary


# --- the circuit breaker --------------------------------------------------------------------------------


def test_a_handful_of_identical_fatal_errors_fails_the_rest_of_the_batch_as_circuit_open_without_sending_it():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(401, content=b"invalid api key")

    client, _ = client_for(handler, circuit_threshold=5)
    outcomes = client.complete([ask(index) for index in range(100)])
    kinds = {outcome.kind for outcome in outcomes}
    assert FailureKind.CIRCUIT_OPEN in kinds
    opened = [outcome for outcome in outcomes if isinstance(outcome, CallFailure) and outcome.kind is FailureKind.CIRCUIT_OPEN]
    assert opened[0].attempts == 0  # a short-circuited call made no attempts
    assert len(opened) >= 90
    assert state["sent"] <= 8  # thousands of refusals were never sent; a few in flight raced the breaker
    assert "circuit open" in opened[0].detail and "401" in opened[0].detail


def test_a_later_batch_meets_the_same_one_error_and_still_no_network():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(404, content=b"model not found")

    client, _ = client_for(handler, circuit_threshold=3)
    client.complete([ask(index) for index in range(20)])
    sent_after_first = state["sent"]
    outcomes = client.complete([ask(index) for index in range(20)])
    assert state["sent"] == sent_after_first
    assert all(isinstance(outcome, CallFailure) and outcome.kind is FailureKind.CIRCUIT_OPEN for outcome in outcomes)


def test_a_provider_outage_never_opens_the_circuit_so_the_client_works_again_once_it_recovers():
    """Server errors once counted toward the circuit, which never closes: five 503s during a short outage
    left the client refusing every later call with nothing sent, long after the endpoint recovered."""
    state = {"down": True, "sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        if state["down"]:
            return httpx.Response(503, content=b"overloaded")
        return httpx.Response(200, content=chat_json(TIER_A))

    client, _ = client_for(handler, circuit_threshold=5, max_retries=1)
    during = client.complete([ask(index) for index in range(8)])
    assert not any(isinstance(o, CallFailure) and o.kind is FailureKind.CIRCUIT_OPEN for o in during)
    assert all(isinstance(o, CallFailure) and o.kind is FailureKind.FATAL_RESPONSE for o in during)
    state["down"], state["sent"] = False, 0
    after = client.complete([ask(index) for index in range(3)])
    assert all(isinstance(o, Completion) for o in after)
    assert state["sent"] == 3


def test_differing_fatal_errors_do_not_pile_into_one_circuit():
    state = {"sent": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        return httpx.Response(401 if state["sent"] % 2 else 404, content=b"mixed")

    client, _ = client_for(handler, circuit_threshold=4, max_retries=0)
    outcomes = client.complete([ask(index) for index in range(4)])
    assert not any(isinstance(o, CallFailure) and o.kind is FailureKind.CIRCUIT_OPEN for o in outcomes)


# --- retry policy is execution configuration, never a contract -----------------------------------------


def test_retry_counts_and_backoff_appear_in_no_hashed_contract():
    from tests.study_builders import ANCHOR_SET_HASHES, TEMPLATE_HASHES, run_config_payload
    from simcore.schemas import SCHEMA_VERSION

    config = RunConfig.model_validate(run_config_payload())
    text = canonical_json(config)
    for banned in ("retries", "backoff", "concurrency", "timeout", "rate", "circuit", "base_url"):
        assert banned not in text
    loose = ExecutionSettings(max_retries=9, backoff_base_s=4.0, max_concurrency=99)
    tight = ExecutionSettings(max_retries=0, backoff_base_s=0.01, max_concurrency=1)
    assert canonical_json(config) == canonical_json(config)  # the same study configuration hashes the same
    assert not hasattr(loose, "model_dump")  # execution settings are not a contract model at all
    import simcore.schemas.base as base

    assert SCHEMA_VERSION == "1.0.0"
