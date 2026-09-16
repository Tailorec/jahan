"""Phase 3: the batch port. One outcome per request in request order, failures recorded not raised,
concurrent inside, callable from anywhere — and the deterministic fake grown to the same shape."""

import asyncio
import json

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.population import interpret_audience
from simcore.ports import ChatPort
from simcore.ports.fake import FakeChat
from simcore.schemas import (
    CallFailure,
    ChatRequest,
    Completion,
    FailureKind,
    FrozenDict,
    InferenceRole,
)
from tests.boundary.inference.test_one_call import TICKING_CLOCK, PINS, TIER_A


def ask(who: str, template_id: str = "persona_turn") -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(FrozenDict({"role": "user", "content": f"what do you think, {who}?"}),),
        temp=0.0,
        max_tokens=32,
        template_id=template_id,
    )


def answering_echo() -> tuple[httpx.MockTransport, list[str]]:
    """A transport that echoes the request's subject back, late first: the last request answered
    completes soonest, so any order other than the request's own would be visible."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        who = body["messages"][-1]["content"][-2]
        delay = {"c": 0.0, "b": 0.02, "a": 0.04}[who]  # a (first in) answers last
        await asyncio.sleep(delay)
        seen.append(who)
        payload = {"model": TIER_A, "choices": [{"message": {"role": "assistant", "content": f"{who} says yes"}}]}
        return httpx.Response(200, content=json.dumps(payload).encode())

    return httpx.MockTransport(handler), seen


def client(transport: httpx.MockTransport) -> InferenceClient:
    return InferenceClient(PINS, ExecutionSettings(base_url="http://gateway.test/v1"), transport=transport, clock=TICKING_CLOCK)


# --- order and failure -----------------------------------------------------------------------------


def test_outcomes_return_in_request_order_when_the_transport_answers_them_in_reverse():
    transport, _ = answering_echo()
    outcomes = client(transport).complete([ask("a"), ask("b"), ask("c")])
    assert [outcome.text for outcome in outcomes] == ["a says yes", "b says yes", "c says yes"]
    assert all(isinstance(outcome, Completion) for outcome in outcomes)


def test_one_failing_request_leaves_every_other_outcome_a_completion_and_the_failure_is_recorded():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        who = body["messages"][-1]["content"][-2]
        if who == "b":
            return httpx.Response(503, content=b"overloaded")
        payload = {"model": TIER_A, "choices": [{"message": {"role": "assistant", "content": f"{who} says yes"}}]}
        return httpx.Response(200, content=json.dumps(payload).encode())

    outcomes = client(httpx.MockTransport(handler)).complete([ask("a"), ask("b"), ask("c")])
    first, middle, last = outcomes
    assert isinstance(first, Completion) and isinstance(last, Completion)
    assert isinstance(middle, CallFailure) and middle.kind is FailureKind.FATAL_RESPONSE
    assert middle.route.value == "primary" and middle.attempts >= 1


def test_a_single_request_call_is_exactly_a_batch_of_one():
    transport, _ = answering_echo()
    c = client(transport)
    direct = c.complete([ask("c")])[0]
    wrapped = c.chat(InferenceRole.TIER_A, [{"role": "user", "content": "what do you think, c?"}], temp=0.0, max_tokens=32, template_id="persona_turn")
    assert isinstance(direct, Completion) and isinstance(wrapped, Completion)
    assert (direct.text, direct.prompt_hash) == (wrapped.text, wrapped.prompt_hash)


# --- the caller's loop is not our loop ---------------------------------------------------------------


def test_the_batch_call_works_from_inside_a_running_event_loop():
    transport, _ = answering_echo()
    c = client(transport)

    async def notebook_cell() -> tuple:
        # We are inside a running loop here; `complete` is synchronous to its caller and concurrent
        # inside, on the module's own loop, so this cannot deadlock on the loop it is called from.
        return c.complete([ask("a"), ask("b"), ask("c")])

    outcomes = asyncio.run(notebook_cell())
    assert [outcome.text for outcome in outcomes] == ["a says yes", "b says yes", "c says yes"]


# --- the deterministic fake grows the same shape ------------------------------------------------------


def test_the_fake_answers_batches_deterministically_across_processes():
    requests = [ask("a"), ask("b", template_id="reflection")]
    first = FakeChat().complete(requests)
    second = FakeChat().complete(requests)
    assert [(o.text, o.prompt_hash) for o in first] == [(o.text, o.prompt_hash) for o in second]
    assert all(isinstance(o, Completion) for o in first)


@pytest.mark.parametrize(
    "kind",
    [FailureKind.RATE_LIMITED, FailureKind.TIMED_OUT, FailureKind.FATAL_RESPONSE, FailureKind.CIRCUIT_OPEN, FailureKind.PIN_FAILURE, FailureKind.INVALID_OUTPUT],
)
def test_the_fake_can_inject_each_failure_kind(kind):
    outcomes = FakeChat(failures={"persona_turn": kind}).complete([ask("a"), ask("b", template_id="reflection")])
    failure, completion = outcomes
    assert isinstance(failure, CallFailure) and failure.kind is kind and failure.attempts == 1
    assert isinstance(completion, Completion)


def test_the_fake_is_a_chat_port_and_so_is_the_client():
    transport, _ = answering_echo()
    assert isinstance(FakeChat(), ChatPort)
    assert isinstance(client(transport), ChatPort)


# --- audience interpretation, first real consumer ------------------------------------------------------


def test_audience_interpretation_runs_through_the_batch_port():
    from tests.boundary.population.test_interpret import fixture, pack  # its behaviour and tests are unchanged

    fake = FakeChat(responder=lambda messages, template_id: json.dumps({"exercise_frequency": "3_plus_weekly"}))
    audience = interpret_audience(
        "people who train three times a week or more", pack(audiences=[]), name="gym_regulars", catalog=fixture(), inference=fake
    )
    assert set(audience.attribute_filters) == {"exercise_frequency"}
    assert len(fake.calls) == 1  # one batched call


def test_a_failed_interpretation_call_raises_naming_the_failure():
    from tests.boundary.population.test_interpret import fixture, pack

    fake = FakeChat(failures={"audience_interpretation": FailureKind.RATE_LIMITED})
    with pytest.raises(ValueError, match="rate_limited"):
        interpret_audience("anyone", pack(audiences=[]), catalog=fixture(), inference=fake)
