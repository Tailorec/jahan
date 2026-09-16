"""Phase 4: at scale. A tick's worth of calls held without a coroutine per call and without a storm of
429s: a bounded queue, an adaptive ceiling, request and token rate limits that adapt, and Retry-After."""

import asyncio
import json

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import ChatRequest, Completion, FrozenDict, InferenceRole, ModelPins

TIER_A = "openrouter/camel-ai/persona-8b"
PINS = ModelPins.model_validate({"tier_a": TIER_A, "tier_b": "anthropic/claude-sonnet-4-5-20250929", "embed": "openai/text-embedding-3-small"})


class FakeTime:
    """A clock the tests control: sleeps advance it instantly, so a rate-limited batch costs no wall time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def ask(index: int) -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(FrozenDict({"role": "user", "content": f"question {index}"}),),
        temp=0.0,
        max_tokens=8,
        template_id="persona_turn",
    )


def answer(index: int = 0) -> bytes:
    return json.dumps({"model": TIER_A, "choices": [{"message": {"role": "assistant", "content": f"answer {index}"}}]}).encode()


def build(*, concurrency=4, transport_handler, **settings) -> tuple[InferenceClient, FakeTime]:
    time = FakeTime()
    client = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=concurrency, **settings),
        transport=httpx.MockTransport(transport_handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    return client, time


# --- the ceiling holds in flight, the queue holds the rest ------------------------------------------


def test_a_batch_far_larger_than_the_ceiling_never_has_more_calls_in_flight_than_the_ceiling():
    state = {"in_flight": 0, "peak": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.005)
        state["in_flight"] -= 1
        return httpx.Response(200, content=answer())

    client, _ = build(concurrency=4, transport_handler=handler)
    outcomes = client.complete([ask(index) for index in range(40)])
    assert len(outcomes) == 40 and all(isinstance(outcome, Completion) for outcome in outcomes)
    assert state["peak"] <= 4  # the transport itself saw no more than the ceiling
    assert client.stats.in_flight_peak <= 4


def test_memory_held_by_queued_requests_does_not_grow_with_batch_size_beyond_the_queue_bound():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=answer())

    client, _ = build(concurrency=2, queue_bound=3, transport_handler=handler)
    outcomes = client.complete([ask(index) for index in range(200)])
    assert len(outcomes) == 200
    assert client.stats.queued_peak <= 3


# --- rate limits hold over a measured window -----------------------------------------------------------


def test_the_request_rate_limit_is_never_exceeded_over_a_measured_window():
    sent: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(time.now)
        return httpx.Response(200, content=answer())

    client, time = build(concurrency=2, requests_per_minute=10, transport_handler=handler)
    outcomes = client.complete([ask(index) for index in range(30)])
    assert len(outcomes) == 30
    for moment in sent:
        in_window = sum(1 for other in sent if moment <= other < moment + 60.0)
        assert in_window <= 10


def test_neither_limit_is_exceeded_when_both_are_configured():
    sent: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(time.now)
        return httpx.Response(200, content=answer())

    time = FakeTime()
    client = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=2, requests_per_minute=6, tokens_per_minute=400),
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    outcomes = client.complete([ask(index) for index in range(20)])
    assert len(outcomes) == 20
    for moment in sent:
        assert sum(1 for other in sent if moment <= other < moment + 60.0) <= 6


# --- estimates are corrected by reported usage ----------------------------------------------------------


def usage_answer(prompt_tokens: int, completion_tokens: int) -> bytes:
    return json.dumps(
        {
            "model": TIER_A,
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }
    ).encode()


def batch_actual_tokens(sent: list[tuple[float, int]], moment: float, window: float = 60.0) -> int:
    return sum(tokens for when, tokens in sent if moment <= when < moment + window)


def test_a_systematic_underestimate_corrected_by_usage_stops_exceeding_the_token_limit():
    # The request estimates ~11 tokens; every call is actually answered with 400 — a 36x underestimate.
    tpm = 1_000
    sent: list[tuple[float, int]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append((time.now, 400))
        return httpx.Response(200, content=usage_answer(200, 200))

    time = FakeTime()
    client = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=1, tokens_per_minute=tpm),
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    client.complete([ask(index) for index in range(8)])
    worst = max(batch_actual_tokens(sent, moment) for moment, _ in sent)
    assert worst <= tpm + 400  # at most one in-flight call can overshoot a corrected limit


def test_without_correction_the_same_underestimate_would_blow_the_token_limit():
    tpm = 1_000
    sent: list[tuple[float, int]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append((time.now, 400))
        return httpx.Response(200, content=answer())  # reports no usage: nothing to correct with

    time = FakeTime()
    client = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=1, tokens_per_minute=tpm),
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    client.complete([ask(index) for index in range(8)])
    worst = max(batch_actual_tokens(sent, moment) for moment, _ in sent)
    assert worst > tpm + 400  # uncorrected, the estimates let a real flood through the gate


# --- the ceiling adapts to the endpoint's answers ---------------------------------------------------------


def test_a_run_of_429s_lowers_the_ceiling_and_a_run_of_successes_raises_it_back():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 3:  # every attempt of the first call is rate limited: three halvings
            return httpx.Response(429, headers={"retry-after": "0"}, content=b"{}")
        return httpx.Response(200, content=answer())

    client, _ = build(concurrency=8, transport_handler=handler)
    outcomes = client.complete([ask(0), ask(1)])
    assert all(isinstance(outcome, Completion) for outcome in outcomes)
    assert client.stats.ceiling_lowest == 1  # 8 → 4 → 2 → 1 under sustained 429s
    assert client.stats.ceiling_final > client.stats.ceiling_lowest
    # a run of successes walks it back toward the configured maximum
    client.complete([ask(index) for index in range(30)])
    assert client.stats.ceiling_final == 8


def test_a_retry_after_delays_the_next_attempt_by_at_least_what_it_says():
    state = {"first": True, "when_first_failed": None}

    async def handler(request: httpx.Request) -> httpx.Response:
        if state["first"]:
            state["first"] = False
            state["when_first_failed"] = time.now
            return httpx.Response(429, headers={"retry-after": "2"}, content=b"{}")
        return httpx.Response(200, content=answer())

    client, time = build(concurrency=1, transport_handler=handler)
    outcome = client.complete([ask(0)])[0]
    assert isinstance(outcome, Completion)
    assert time.now - state["when_first_failed"] >= 2.0
    assert any(slept >= 2.0 for slept in time.slept)
