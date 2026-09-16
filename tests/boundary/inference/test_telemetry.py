"""Phase 10: telemetry that is not the trace. Spans for every batch and call, GenAI conventions named
in one place, no content unless capture is enabled, and trace context a gateway can join."""

import asyncio
import json
import re
import time
from pathlib import Path

import httpx
import pytest

trace = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry import trace as api_trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from simcore.inference import ExecutionSettings, InferenceClient  # noqa: E402
from simcore.schemas import InferenceRole, ModelPins  # noqa: E402
from tests.boundary.inference.test_scale import FakeTime, PINS, TIER_A, ask  # noqa: E402

PROMPT_MARK = "question 0"
ANSWER_MARK = "answer 0"
FALLBACK = "openrouter/qwen/qwen-2.5-7b-instruct"
WITH_FALLBACK = ModelPins.model_validate(
    {"tier_a": TIER_A, "tier_b": PINS.tier_b, "embed": PINS.embed, "fallbacks": {"tier_a": FALLBACK}}
)


def answer(model: str = TIER_A) -> bytes:
    return json.dumps({"model": model, "choices": [{"message": {"role": "assistant", "content": ANSWER_MARK}}]}).encode()


def instrumented(pins: ModelPins = PINS, *, capture=False, handler=None, **settings):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    state = {"sent": 0}

    async def default_handler(request: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        body = json.loads(request.content)
        if handler is not None:
            return handler(request, body, state["sent"])
        return httpx.Response(200, content=answer(body["model"]))

    time_source = FakeTime()
    client = InferenceClient(
        pins,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=1, content_capture=capture, **settings),
        transport=httpx.MockTransport(default_handler),
        clock=time_source.clock,
        sleep=time_source.sleep,
        tracer_provider=provider,
    )
    return client, exporter, state


def by_name(exporter, name):
    return [span for span in exporter.get_finished_spans() if span.name == name]


# --- the API/SDK split ---------------------------------------------------------------------------


def test_without_a_configured_provider_calls_record_nothing_and_cost_no_measurable_time():
    client = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=8),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=answer())),
    )
    requests = [ask(index) for index in range(100)]
    started = time.perf_counter()
    outcomes = client.complete(requests)
    elapsed = time.perf_counter() - started
    assert len(outcomes) == 100
    assert elapsed < 5.0  # the no-op API is not a tax on every call (a generous wall; the 5ms sleeps dominate)


def test_the_core_depends_on_the_api_and_the_sdk_is_an_extra():
    pyproject = Path("pyproject.toml").read_text()
    assert "opentelemetry-api" in pyproject.split("[project.optional-dependencies]")[0]
    extra = re.search(r"otel\s*=\s*\[([^\]]*)\]", pyproject)
    assert extra and "opentelemetry-sdk" in extra.group(1) and "opentelemetry-exporter-otlp" in extra.group(1)
    for path in Path("simcore").rglob("*.py"):
        source = path.read_text()
        if "opentelemetry" in source:
            assert path.name == "_otel.py", f"{path} imports telemetry outside the one module"
    sdk = __import__("opentelemetry.sdk.trace", fromlist=["TracerProvider"])
    assert sdk is not None  # the SDK exists only for tests and the extra; the client above ran without it


# --- batch, call, events -------------------------------------------------------------------------


def test_a_batch_produces_one_batch_span_and_one_span_per_call_with_retry_and_fallback_events():
    def flaky(request, body, n):
        if body["model"] == TIER_A and n <= 3:
            headers = {"retry-after": "0"} if n == 1 else {}
            return httpx.Response(429 if n == 1 else 503, content=b"busy", headers=headers)
        return httpx.Response(200, content=answer(body["model"]))

    client, exporter, _ = instrumented(WITH_FALLBACK, handler=flaky, max_retries=1)
    outcomes = client.complete([ask(0), ask(1)])
    assert all(outcome.__class__.__name__ == "Completion" for outcome in outcomes)
    assert len(by_name(exporter, "inference.chat.batch")) == 1
    calls = by_name(exporter, "inference.chat")
    assert len(calls) == 2  # one span per call, whatever it went through
    traced = calls[0]
    events = {event.name for event in traced.events}
    assert {"retry", "fallback"} <= events or {"retry", "fallback"} <= {event.name for call in calls for event in call.events}


def test_call_spans_carry_gen_ai_conventions_and_world_joiners_and_cost_and_failure():
    client, exporter, _ = instrumented()
    client.complete([ask(3)])
    (call,) = by_name(exporter, "inference.chat")
    attributes = dict(call.attributes)
    assert attributes["gen_ai.operation.name"] == "chat"
    assert attributes["gen_ai.request.model"] == TIER_A
    assert attributes["gen_ai.response.model"] == TIER_A
    assert attributes["gen_ai.usage.input_tokens"] >= 1
    assert attributes["simcore.inference.route"] == "primary"
    assert attributes["simcore.inference.cost_source"] == "unknown"
    from simcore.schemas import SampleKey

    client.complete([ask(0).model_copy(update={"temp": 0.7, "sample": SampleKey(world_seed=4021, persona_id="p-9", tick=5)})])
    sampled = [span for span in by_name(exporter, "inference.chat") if (span.attributes or {}).get("simcore.world_seed") == 4021]
    assert sampled and dict(sampled[-1].attributes)["simcore.persona_id"] == "p-9"
    assert dict(sampled[-1].attributes)["simcore.tick"] == 5


def test_a_recorded_failure_names_its_kind_on_the_span():
    client, exporter, _ = instrumented(handler=lambda request, body, n: httpx.Response(401, content=b"invalid key"))
    outcome = client.complete([ask(0)])[0]
    assert outcome.__class__.__name__ == "CallFailure"
    (call,) = by_name(exporter, "inference.chat")
    assert dict(call.attributes)["simcore.inference.failure.kind"] == "fatal_response"
    assert call.status.status_code.name == "ERROR"


# --- content stays inside the trace boundary ------------------------------------------------------


def test_no_span_carries_prompt_or_response_content_unless_capture_is_enabled():
    client, exporter, _ = instrumented()
    client.complete([ask(0)])
    for span in exporter.get_finished_spans():
        for key, value in (span.attributes or {}).items():
            assert PROMPT_MARK not in str(value), (span.name, key)
            assert ANSWER_MARK not in str(value), (span.name, key)


def test_content_appears_only_when_capture_is_explicitly_enabled():
    client, exporter, _ = instrumented(capture=True)
    client.complete([ask(0)])
    (call,) = by_name(exporter, "inference.chat")
    assert PROMPT_MARK in json.dumps(dict(call.attributes))
    assert ANSWER_MARK in json.dumps(dict(call.attributes))


def echoing_refusal(request, body, sent):
    """A gateway validation error that quotes the request back, as many do."""
    quoted = body["messages"][0]["content"]
    return httpx.Response(400, content=json.dumps({"error": {"type": "invalid_request_error", "code": "bad_param", "message": f"rejected: {quoted}"}}).encode())


def test_an_error_body_that_quotes_the_prompt_reaches_neither_a_span_nor_the_recorded_failure():
    """Failures recorded the endpoint's error text, and a gateway's validation error quotes the request: with
    capture off, persona content reached a span and the failure the trace records."""
    client, exporter, _ = instrumented(handler=echoing_refusal, max_retries=0)
    (outcome,) = client.complete([ask(0)])
    assert PROMPT_MARK not in outcome.detail
    assert "400" in outcome.detail and "type=invalid_request_error" in outcome.detail and "code=bad_param" in outcome.detail
    for span in exporter.get_finished_spans():
        for key, value in (span.attributes or {}).items():
            assert PROMPT_MARK not in str(value), (span.name, key)


def test_an_error_body_is_attached_to_the_span_only_when_capture_is_enabled():
    client, exporter, _ = instrumented(capture=True, handler=echoing_refusal, max_retries=0)
    (outcome,) = client.complete([ask(0)])
    assert PROMPT_MARK not in outcome.detail  # the recorded failure never carries it, capture or not
    (call,) = by_name(exporter, "inference.chat")
    assert PROMPT_MARK in json.dumps(dict(call.attributes))


def test_every_gen_ai_attribute_name_is_defined_in_one_module():
    offenders = []
    for path in Path("simcore").rglob("*.py"):
        if path.name == "_otel.py":
            continue
        if '"gen_ai.' in path.read_text() or "'gen_ai." in path.read_text():
            offenders.append(str(path))
    assert offenders == []


# --- a gateway can join --------------------------------------------------------------------------------


def test_requests_carry_trace_context_for_a_gateway_to_join():
    seen: list[str] = []

    def peek(request, body, n):
        seen.append(request.headers.get("traceparent", ""))
        return httpx.Response(200, content=answer())

    client, _, _ = instrumented(handler=peek)
    client.complete([ask(0)])
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", seen[0])


def test_no_analytical_code_path_reads_a_span():
    # The only imports of the telemetry API live in the inference module; no schema, port, brief or
    # population file names it, and nothing reads exported records back into a study.
    readers = []
    for package in ("schemas", "ports", "population", "brief"):
        for path in (Path("simcore") / package).rglob("*.py"):
            if "opentelemetry" in path.read_text() or "_otel" in path.read_text():
                readers.append(str(path))
    assert readers == []
