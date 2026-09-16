"""Telemetry is not the trace.

OpenTelemetry spans for every batch and call, exported over OTLP to whatever collector the user runs,
and doing nothing when none is configured — the core depends on `opentelemetry-api` alone; the SDK and
exporter are the optional ``otel`` extra (ADR 0022). Spans carry metadata only unless content capture is
explicitly enabled, so observability never becomes a second copy of the corpus or a redistribution of
persona data. Nothing analytical reads a span: the scientific record is the trace, and a study that
needs a number reads it from the trace, not from a collector that may have dropped it."""

from collections.abc import Mapping
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import Span, Status, StatusCode

TRACER_NAME = "simcore.inference"
TRACER_VERSION = "1.0.0"

# Every GenAI attribute name this engine emits, in one place, following the OpenTelemetry GenAI
# semantic conventions where they cover it and a `simcore.` namespace where they do not.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_SEED = "gen_ai.request.seed"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"  # the template is the tool that produced the prompt
# Content appears only when the user has enabled capture; these names never appear without it.
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"

SIMCORE_ROLE = "simcore.inference.role"
SIMCORE_ROUTE = "simcore.inference.route"
SIMCORE_TEMPLATE_ID = "simcore.inference.template_id"
SIMCORE_PROMPT_HASH = "simcore.inference.prompt_hash"
SIMCORE_LATENCY_MS = "simcore.inference.latency_ms"
SIMCORE_COST = "simcore.inference.cost"
SIMCORE_COST_SOURCE = "simcore.inference.cost_source"
SIMCORE_FAILURE_KIND = "simcore.inference.failure.kind"
SIMCORE_FAILURE_DETAIL = "simcore.inference.failure.detail"
# An endpoint's error body can quote the request that caused it, so it is content: attached only with capture.
SIMCORE_FAILURE_BODY = "simcore.inference.failure.body"
SIMCORE_ATTEMPTS = "simcore.inference.attempts"
SIMCORE_BATCH_SIZE = "simcore.inference.batch_size"
SIMCORE_WORLD_SEED = "simcore.world_seed"
SIMCORE_PERSONA_ID = "simcore.persona_id"
SIMCORE_TICK = "simcore.tick"
SIMCORE_EVENT_RETRY = "retry"
SIMCORE_EVENT_FALLBACK = "fallback"


def start_span(name: str, attributes: Mapping[str, Any], *, parent=None, operation: str = "chat", provider=None) -> tuple[Span, Any]:
    """Begin a span under `parent` (or the ambient context) and hand back what to run children under.

    Without a configured provider — the SDK is the optional `otel` extra — this returns a
    non-recording span and the calls below it cost nothing anyone can measure."""
    tracer = trace.get_tracer(TRACER_NAME, TRACER_VERSION, tracer_provider=provider)
    payload = {GEN_AI_OPERATION_NAME: operation, GEN_AI_PROVIDER_NAME: "openai", **dict(attributes)}
    span = tracer.start_span(name, context=parent, attributes={key: value for key, value in payload.items() if value is not None})
    return span, trace.set_span_in_context(span, parent or otel_context.get_current())


def record(span: Span, attributes: Mapping[str, Any]) -> None:
    clean = {key: value for key, value in attributes.items() if value is not None}
    if clean:
        span.set_attributes(clean)


def finish(span: Span, *, ok: bool, attributes: Mapping[str, Any] | None = None) -> None:
    record(span, attributes or {})
    if not ok:
        span.set_status(Status(StatusCode.ERROR))
    span.end()


def traceparent(context) -> dict[str, str]:
    """The headers that let a gateway's spans nest under the engine's."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier, context=context)
    return carrier
