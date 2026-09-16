"""`InferenceClient`: every model call through one OpenAI-compatible endpoint, recorded as what it was.

The engine speaks one protocol over `httpx` and imports no provider SDK and no gateway library (ADR
0021); which provider answers is the gateway's business. A role resolves to its pin before any byte
leaves, the request body is serialized once and sent as exactly those bytes, and the response is
recorded as a `Completion` naming the model that served it, its tokens, latency and cost with its
source — or as a `CallFailure` (ADR 0023). A call answered by a model outside its pin's accepted
identifiers is a pin failure, never a result.

A batch runs on a bounded queue feeding workers under an adaptive in-flight ceiling and a limiter on
requests and tokens per minute, so a tick's hundred thousand calls become neither a hundred thousand
coroutines nor a storm of 429s."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx
import numpy as np

from simcore.schemas import (
    CallFailure,
    ChatOutcome,
    ChatRequest,
    Completion,
    CostRecorded,
    CostSource,
    FailureKind,
    FrozenDict,
    InferenceRole,
    InferenceRoute,
    ModelPin,
    ModelPins,
)

from ._cache import SampleCache
from ._dispatch import (
    AdaptiveCeiling,
    DispatchStats,
    RateLimiter,
    request_estimate,
    retry_after,
)
from ._loop import run
from ._otel import (
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_REQUEST_MAX_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_SEED,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_TOOL_NAME,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    SIMCORE_ATTEMPTS,
    SIMCORE_BATCH_SIZE,
    SIMCORE_COST,
    SIMCORE_COST_SOURCE,
    SIMCORE_EVENT_FALLBACK,
    SIMCORE_EVENT_RETRY,
    SIMCORE_FAILURE_DETAIL,
    SIMCORE_FAILURE_KIND,
    SIMCORE_LATENCY_MS,
    SIMCORE_PERSONA_ID,
    SIMCORE_PROMPT_HASH,
    SIMCORE_ROLE,
    SIMCORE_ROUTE,
    SIMCORE_TEMPLATE_ID,
    SIMCORE_TICK,
    SIMCORE_WORLD_SEED,
    finish,
    record,
    start_span,
    traceparent,
)
from ._settings import ExecutionSettings
from ._parsing import coerce_json, validate_schema
from ._wire import (
    CHAT_PATH,
    EMBEDDINGS_PATH,
    body_bytes,
    chat_body,
    derive_seed,
    embeddings_body,
    estimate_tokens,
    gateway_cost,
    messages_text,
    price_table_cost,
    prompt_hash,
)


class UnpinnedRoleError(ValueError):
    """A study asked a role it never pinned. Refused before any network call: a misconfigured study
    fails in a second rather than after spending."""


EMBEDDING_NORMALIZATION = "l2"
EMBEDDINGS_TEMPLATE = "embeddings"


@dataclass(frozen=True)
class EmbeddingVectors:
    """A batch's raw answer, before the run's dimension check and normalisation."""

    vectors: list[list[float]]
    served_model_id: str
    input_tokens: int
    payload: dict
    headers: object


@dataclass(frozen=True)
class EmbeddingResult:
    """The vectors one `embed` call produced, in input order, with the normalisation applied, the
    dimension the run fixed on, and the cost record of every capped batch that answered."""

    vectors: "np.ndarray"
    model_id: str
    served_model_id: str | None
    normalization: str
    dim: int
    costs: tuple[CostRecorded, ...]


class EmbeddingFailure(RuntimeError):
    """A recorded call failure with no partially-usable form: some vectors of a batch are not the
    vectors the caller asked for, so an exhausted embedding batch raises what it recorded."""

    def __init__(self, failure: CallFailure) -> None:
        super().__init__(f"embedding call failed: {failure.kind.value} — {failure.detail}")
        self.failure = failure


def _normalised(vectors: list[list[float]]) -> "np.ndarray":
    array = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.where(norms == 0, 1.0, norms)


@dataclass(frozen=True)
class _Reply:
    """One exchange's outcome plus what the dispatcher should make of it."""

    outcome: Completion | CallFailure | EmbeddingVectors
    retryable: bool = False
    limited: bool = False
    wait_s: float | None = None
    fatal_status: int | None = None


class InferenceClient:
    """The batch port: `complete(requests) -> outcomes`, synchronous and order-preserving outside,
    concurrent inside, with a `chat()` facade over a batch of one."""

    def __init__(
        self,
        pins: ModelPins,
        settings: ExecutionSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        template_hashes: Mapping[str, str] | None = None,
        tracer_provider=None,
    ) -> None:
        self._tracer_provider = tracer_provider
        self.pins = pins
        self.settings = settings or ExecutionSettings()
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._ceiling = AdaptiveCeiling(self.settings.max_concurrency)
        self._limiter = RateLimiter(
            self.settings.requests_per_minute, self.settings.tokens_per_minute, self._clock, self._sleep
        )
        self.stats = DispatchStats()
        self._template_hashes = dict(template_hashes or {})
        self._cache = SampleCache(self.settings.cache_dir) if self.settings.cache_dir is not None else None
        # A short run of identical fatal errors — an invalid key, an unknown model — is not a thousand
        # separate misfortunes. The run is counted here and opens one circuit for the client.
        self._consecutive_fatals: dict[int, int] = {}
        self._circuit_detail: str | None = None
        # One embedding space per run: every vector's dimension is checked against the first the run received.
        self._embedding_dim: int | None = None
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            transport=transport,
            timeout=httpx.Timeout(self.settings.timeout_s),
        )

    def resolve(self, role: InferenceRole) -> ModelPin:
        pin = getattr(self.pins, role.value)
        if pin is None:
            raise UnpinnedRoleError(f"the study pins no model for role {role.value!r}; refuse before spending")
        return pin

    def complete(self, requests: Sequence[ChatRequest]) -> tuple[ChatOutcome, ...]:
        """One outcome per request in request order, whatever order the responses arrive in. Every pin is
        resolved first, so an unpinned role is refused before any request is sent."""
        pins = [self.resolve(request.role) for request in requests]
        for request, pin in zip(requests, pins, strict=True):
            if request.role is InferenceRole.EMBED:
                raise ValueError("embeddings are not chat: they go through the embedding endpoint, never complete()")
        if not requests:
            return ()
        batch, batch_context = start_span("inference.chat.batch", {SIMCORE_BATCH_SIZE: len(requests)}, operation="batch", provider=self._tracer_provider)
        try:
            outcomes = run(self._gather(list(requests), pins, batch_context))
        finally:
            finish(batch, ok=True, attributes={SIMCORE_BATCH_SIZE: len(requests)})
        return outcomes

    def chat(
        self,
        role: InferenceRole,
        messages: Sequence[dict],
        *,
        temp: float,
        max_tokens: int,
        template_id: str,
        sample=None,
        json_schema: str | None = None,
    ) -> ChatOutcome:
        """One request over the batch port: exactly a batch of one."""
        request = ChatRequest(
            role=role,
            messages=tuple(_frozen(message) for message in messages),
            temp=temp,
            max_tokens=max_tokens,
            template_id=template_id,
            sample=sample,
            json_schema=json_schema,
        )
        return self.complete((request,))[0]

    def embed(self, texts: Sequence[str]) -> "EmbeddingResult":
        """Capped batches to the one pinned embedding model, through the same endpoint, queue, ceiling
        and limiter as every chat call. Embedding never falls back: anchors and vectors scored in
        different embedding spaces are not comparable (ADR 0012), so an exhausted batch fails the call
        rather than quietly changing the space.

        A chat failure is an outcome because a caller can act on some and not others; a failed batch of
        vectors has no partially-usable form, so it raises — with the recorded failure in hand."""
        pin = self.resolve(InferenceRole.EMBED)
        if not texts:
            return EmbeddingResult(vectors=np.zeros((0, self._embedding_dim or 0), dtype=np.float32), model_id=pin.model_id, served_model_id=None, normalization=EMBEDDING_NORMALIZATION, dim=self._embedding_dim or 0, costs=())
        cap = max(1, self.settings.embeddings_batch_size)
        batches = [list(texts[start : start + cap]) for start in range(0, len(texts), cap)]
        batch, batch_context = start_span("inference.embeddings.batch", {SIMCORE_BATCH_SIZE: len(texts), GEN_AI_REQUEST_MODEL: pin.model_id}, operation="embeddings", provider=self._tracer_provider)
        try:
            results = run(self._embed_all(batches, batch_context))
        finally:
            finish(batch, ok=True)
        vectors = np.concatenate([result.vectors for result in results], axis=0)
        costs = tuple(cost for result in results for cost in result.costs)
        first = next((result.served_model_id for result in results if result.served_model_id), None)
        return EmbeddingResult(
            vectors=vectors,
            model_id=self.resolve(InferenceRole.EMBED).model_id,
            served_model_id=first,
            normalization=EMBEDDING_NORMALIZATION,
            dim=int(vectors.shape[1]),
            costs=costs,
        )

    async def _embed_all(self, batches: list[list[str]], batch_context) -> list:
        return list(await asyncio.gather(*(self._embed_batch(batch, batch_context) for batch in batches)))

    async def _embed_batch(self, batch: list[str], batch_context) -> "EmbeddingResult":
        pin = self.resolve(InferenceRole.EMBED)
        span, call_context = start_span("inference.embeddings", {GEN_AI_REQUEST_MODEL: pin.model_id, SIMCORE_BATCH_SIZE: len(batch)}, parent=batch_context, operation="embeddings", provider=self._tracer_provider)
        data = body_bytes(embeddings_body(batch, pin))
        key = self._cache.key(pin, template_id=EMBEDDINGS_TEMPLATE, request_bytes=data) if self._cache else None
        if key and (entry := self._cache.get(key)) is not None:  # type: ignore[union-attr]
            self.stats.cache_hits += 1
            vectors = np.asarray(entry["vectors"], dtype=np.float32)
            cost = CostRecorded(
                kind="cost", role=InferenceRole.EMBED, model_id=pin.model_id, served_model_id=entry.get("served_model_id"),
                cost_source=CostSource.PRICE_TABLE, route=InferenceRoute.CACHE,
                input_tokens=entry.get("input_tokens", 0), output_tokens=0, cost=0.0,
            )
            return EmbeddingResult(vectors=vectors, model_id=pin.model_id, served_model_id=entry.get("served_model_id"), normalization=EMBEDDING_NORMALIZATION, dim=int(vectors.shape[1]), costs=(cost,))
        attempts = 0
        while True:
            if self._circuit_detail is not None:
                raise EmbeddingFailure(CallFailure(kind=FailureKind.CIRCUIT_OPEN, detail=self._circuit_detail, attempts=attempts, route=InferenceRoute.PRIMARY))
            await self._ceiling.acquire()
            self.stats.in_flight_peak = max(self.stats.in_flight_peak, self._ceiling.in_flight)
            estimate = float(sum(estimate_tokens(text) for text in batch))
            try:
                await self._limiter.acquire(estimate)
                attempts += 1
                reply = await self._embed_exchange(batch, pin, attempts, data, call_context)
            finally:
                await self._ceiling.release()
            if reply.limited:
                self.stats.rate_limited += 1
                await self._ceiling.lower()
            else:
                await self._ceiling.restore()
            if reply.fatal_status is not None:
                self._trip(pin, InferenceRoute.PRIMARY, reply.fatal_status)
            if isinstance(reply.outcome, EmbeddingVectors):
                self._limiter.settle(estimate, float(reply.outcome.input_tokens))
                self._consecutive_fatals.clear()
                vectors = _normalised(reply.outcome.vectors)
                dimension = int(vectors.shape[1])
                if self._embedding_dim is None:
                    self._embedding_dim = dimension
                elif dimension != self._embedding_dim:
                    finish(span, ok=False, attributes={SIMCORE_FAILURE_DETAIL: "embedding dimension changed mid run"})
                    raise ValueError(
                        f"the pinned embedding model answered with {dimension} dimensions, but this run's "
                        f"first vectors had {self._embedding_dim}; vectors from two spaces are not comparable"
                    )
                cost = CostRecorded(
                    kind="cost", role=InferenceRole.EMBED, model_id=pin.model_id, served_model_id=reply.outcome.served_model_id,
                    route=InferenceRoute.PRIMARY, input_tokens=reply.outcome.input_tokens, output_tokens=0,
                    **self._cost_fields(pin, reply.outcome.payload, reply.outcome.headers, reply.outcome.input_tokens, 0),
                )
                if self._cache and key:
                    self._cache.put(key, {"vectors": vectors.tolist(), "served_model_id": reply.outcome.served_model_id, "input_tokens": reply.outcome.input_tokens})
                finish(span, ok=True, attributes={GEN_AI_RESPONSE_MODEL: reply.outcome.served_model_id, GEN_AI_USAGE_INPUT_TOKENS: reply.outcome.input_tokens, SIMCORE_COST: cost.cost, SIMCORE_COST_SOURCE: cost.cost_source.value, SIMCORE_ROUTE: cost.route.value})
                return EmbeddingResult(vectors=vectors, model_id=pin.model_id, served_model_id=reply.outcome.served_model_id, normalization=EMBEDDING_NORMALIZATION, dim=dimension, costs=(cost,))
            assert isinstance(reply.outcome, CallFailure)
            if not reply.retryable or attempts > self.settings.max_retries:
                finish(span, ok=False, attributes=_outcome_attributes(reply.outcome))
                raise EmbeddingFailure(reply.outcome)
            wait_s = reply.wait_s
            if wait_s is None:
                wait_s = min(self.settings.backoff_cap_s, self.settings.backoff_base_s * 2.0 ** (attempts - 1))
            else:
                self._limiter.penalize(wait_s)
            await self._sleep(wait_s)

    async def _embed_exchange(self, batch: list[str], pin: ModelPin, attempts: int, data: bytes, call_context=None) -> _Reply:
        try:
            response = await self._http.post(EMBEDDINGS_PATH, content=data, headers=self._headers(call_context))
        except httpx.TimeoutException:
            return _Reply(CallFailure(kind=FailureKind.TIMED_OUT, detail="the embedding endpoint timed out", attempts=attempts, route=InferenceRoute.PRIMARY), retryable=True)
        except httpx.HTTPError as error:
            return _Reply(CallFailure(kind=FailureKind.FATAL_RESPONSE, detail=f"the embedding endpoint could not be reached: {error}", attempts=attempts, route=InferenceRoute.PRIMARY), retryable=True)
        if response.status_code == 429:
            return _Reply(CallFailure(kind=FailureKind.RATE_LIMITED, detail="the embedding endpoint rate limited the batch", attempts=attempts, route=InferenceRoute.PRIMARY), retryable=True, limited=True, wait_s=retry_after(response.headers))
        if response.status_code >= 400:
            fatal = response.status_code >= 500
            return _Reply(
                CallFailure(kind=FailureKind.FATAL_RESPONSE, detail=f"the embedding endpoint answered {response.status_code}: {response.text[:200]}", attempts=attempts, route=InferenceRoute.PRIMARY),
                retryable=fatal,
                fatal_status=None if fatal else response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            return _Reply(CallFailure(kind=FailureKind.INVALID_OUTPUT, detail="the embedding endpoint answered with something that is not JSON", attempts=attempts, route=InferenceRoute.PRIMARY))
        served = payload.get("model")
        if not isinstance(served, str) or served not in pin.serves:
            return _Reply(
                CallFailure(
                    kind=FailureKind.PIN_FAILURE,
                    detail=f"{pin.model_id!r} was served by {served!r}, which the embedding pin does not accept",
                    attempts=attempts,
                    route=InferenceRoute.PRIMARY,
                )
            )
        data_items = payload.get("data")
        if not isinstance(data_items, list) or len(data_items) != len(batch):
            return _Reply(CallFailure(kind=FailureKind.INVALID_OUTPUT, detail="the embedding endpoint returned something that is not one vector per text", attempts=attempts, route=InferenceRoute.PRIMARY))
        ordered = sorted(data_items, key=lambda item: item.get("index", 0))
        vectors = [[float(component) for component in item["embedding"]] for item in ordered]
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = _reported(usage.get("prompt_tokens")) or int(sum(estimate_tokens(text) for text in batch))
        return _Reply(EmbeddingVectors(vectors=vectors, served_model_id=served, input_tokens=input_tokens, payload=payload, headers=response.headers))

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- the batch: a bounded queue feeding workers under the ceiling -----------------------------------

    async def _gather(self, requests: list[ChatRequest], pins: list[ModelPin], batch_context) -> tuple[ChatOutcome, ...]:
        outcomes: list[ChatOutcome | None] = [None] * len(requests)
        queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, self.settings.queue_bound))
        workers = min(self._ceiling.maximum, len(requests))
        done = object()

        async def produce() -> None:
            for job in enumerate(zip(requests, pins, strict=True)):
                await queue.put(job)
                self.stats.queued_peak = max(self.stats.queued_peak, queue.qsize())
            for _ in range(workers):
                await queue.put(done)

        async def work() -> None:
            while True:
                job = await queue.get()
                if job is done:
                    return
                index, (request, pin) = job
                outcomes[index] = await self._execute(request, pin, batch_context)

        producer = asyncio.create_task(produce())
        crew = [asyncio.create_task(work()) for _ in range(workers)]
        await asyncio.gather(producer, *crew)
        self.stats.ceiling_final = self._ceiling.value
        self.stats.ceiling_lowest = self._ceiling.lowest
        return tuple(outcomes)  # type: ignore[arg-type]

    async def _execute(self, request: ChatRequest, pin: ModelPin, batch_context) -> ChatOutcome:
        sample = request.sample
        span, call_context = start_span(
            "inference.chat",
            {
                SIMCORE_ROLE: request.role.value,
                SIMCORE_TEMPLATE_ID: request.template_id,
                GEN_AI_TOOL_NAME: request.template_id,
                GEN_AI_REQUEST_MODEL: pin.model_id,
                GEN_AI_REQUEST_TEMPERATURE: request.temp,
                GEN_AI_REQUEST_MAX_TOKENS: request.max_tokens,
                SIMCORE_WORLD_SEED: sample.world_seed if sample else None,
                SIMCORE_PERSONA_ID: sample.persona_id if sample else None,
                SIMCORE_TICK: sample.tick if sample else None,
            },
            parent=batch_context,
            provider=self._tracer_provider,
        )
        routes = [(InferenceRoute.PRIMARY, pin)]
        fallback = self.pins.fallbacks.get(request.role)
        if request.role is not InferenceRole.EMBED and fallback is not None:
            routes.append((InferenceRoute.FALLBACK, fallback))
        last: ChatOutcome | None = None
        for index, (route, route_pin) in enumerate(routes):
            if index:
                span.add_event(SIMCORE_EVENT_FALLBACK, {GEN_AI_REQUEST_MODEL: route_pin.model_id})
            last = await self._attempt_route(request, route_pin, route, span, call_context)
            if isinstance(last, Completion):
                break
        finish(span, ok=isinstance(last, Completion), attributes=_outcome_attributes(last))
        assert last is not None
        return last

    async def _attempt_route(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute, span, call_context) -> ChatOutcome:
        # A pin that honours seeds is sent one derived from the draw; a pin that does not is sent none,
        # because recording a seed the provider ignored would promise determinism nobody gave.
        seed = derive_seed(request.sample) if pin.honours_seed and request.sample is not None else None
        schema = json.loads(request.json_schema) if request.json_schema is not None else None
        active, data, hashed = request, body_bytes(chat_body(request, pin, seed=seed)), None
        hashed = prompt_hash(data)
        # The cache is keyed on the request the study issued; the accepted bytes recorded beside it are
        # whichever attempt's they turned out to be, so a replay reproduces the warm run exactly.
        cached = await self._cache_hit(request, pin, route, data, hashed)
        if cached is not None:
            return cached
        attempts = 0
        repaired = False
        while True:
            if self._circuit_detail is not None:
                return CallFailure(kind=FailureKind.CIRCUIT_OPEN, detail=self._circuit_detail, attempts=attempts, route=route)
            await self._ceiling.acquire()
            self.stats.in_flight_peak = max(self.stats.in_flight_peak, self._ceiling.in_flight)
            estimate = request_estimate(active)
            try:
                await self._limiter.acquire(estimate)
                attempts += 1
                reply = await self._exchange(active, pin, route, attempts, data, hashed, seed, call_context)
            finally:
                await self._ceiling.release()
            if isinstance(reply.outcome, Completion):
                self._limiter.settle(estimate, float(reply.outcome.cost.input_tokens + reply.outcome.cost.output_tokens))
                self._consecutive_fatals.clear()
                await self._ceiling.restore()
                if attempts > 1 or repaired:
                    record(span, {SIMCORE_ATTEMPTS: attempts, SIMCORE_PROMPT_HASH: hashed, SIMCORE_ROUTE: route.value})
                if self.settings.content_capture:
                    record(span, {GEN_AI_INPUT_MESSAGES: json.dumps([dict(m) for m in active.messages]), GEN_AI_OUTPUT_MESSAGES: reply.outcome.text})
                if schema is not None:
                    errors = _validation_errors(reply.outcome.text, schema)
                    if errors and not repaired:
                        # Once, and only once: a stricter prompt naming what was wrong. Small models
                        # that cannot follow a schema complete where they can; what they cannot answer
                        # is refused, never coerced.
                        repaired = True
                        active = _repair_request(active, reply.outcome.text, errors, request.json_schema)
                        data = body_bytes(chat_body(active, pin, seed=seed))
                        hashed = prompt_hash(data)
                        continue
                    if errors:
                        return CallFailure(
                            kind=FailureKind.INVALID_OUTPUT,
                            detail=f"output still invalid after one repair: {errors[:4]}",
                            attempts=attempts,
                            route=route,
                        )
                await self._cache_store(request, pin, route, body_bytes(chat_body(request, pin, seed=seed)), reply.outcome)
                return reply.outcome
            if reply.limited:
                self.stats.rate_limited += 1
                await self._ceiling.lower()
            else:
                await self._ceiling.restore()
            if reply.fatal_status is not None:
                self._trip(pin, route, reply.fatal_status)
            if not reply.retryable or attempts > self.settings.max_retries:
                if isinstance(reply.outcome, CallFailure):
                    record(span, {SIMCORE_FAILURE_KIND: reply.outcome.kind.value, SIMCORE_FAILURE_DETAIL: reply.outcome.detail})
                return reply.outcome
            span.add_event(SIMCORE_EVENT_RETRY, {SIMCORE_ATTEMPTS: attempts, GEN_AI_REQUEST_MODEL: pin.model_id, SIMCORE_ROUTE: route.value})
            wait_s = reply.wait_s
            if wait_s is None:
                wait_s = min(self.settings.backoff_cap_s, self.settings.backoff_base_s * 2.0 ** (attempts - 1))
            else:
                self._limiter.penalize(wait_s)
            await self._sleep(wait_s)

    def _trip(self, pin: ModelPin, route: InferenceRoute, status: int) -> None:
        """Count a run of identical fatal responses. One that repeats past the threshold opens the
        circuit, so a batch meets one clear error instead of thousands of identical ones."""
        if self._circuit_detail is not None:
            return
        for seen in list(self._consecutive_fatals):
            if seen != status:
                del self._consecutive_fatals[seen]
        self._consecutive_fatals[status] = self._consecutive_fatals.get(status, 0) + 1
        if self._consecutive_fatals[status] >= self.settings.circuit_threshold:
            self._circuit_detail = (
                f"circuit open after {self._consecutive_fatals[status]} consecutive {status} responses from "
                f"{pin.model_id!r}; the endpoint is refusing calls and the rest of the batch will not be sent"
            )

    async def _exchange(
        self, request: ChatRequest, pin: ModelPin, route: InferenceRoute, attempts: int, data: bytes, hashed: str, seed: int | None = None, call_context=None
    ) -> _Reply:
        started = self._clock()
        try:
            response = await self._http.post(CHAT_PATH, content=data, headers=self._headers(call_context))
        except httpx.TimeoutException:
            return _Reply(
                CallFailure(kind=FailureKind.TIMED_OUT, detail=f"the endpoint did not answer {request.template_id!r} within {self.settings.timeout_s}s", attempts=attempts, route=route),
                retryable=True,
            )
        except httpx.HTTPError as error:
            return _Reply(
                CallFailure(kind=FailureKind.FATAL_RESPONSE, detail=f"the endpoint could not be reached: {error}", attempts=attempts, route=route),
                retryable=True,
            )
        latency_ms = max(0, int((self._clock() - started) * 1000))
        return self._record(request, pin, route, response, latency_ms, hashed, attempts, seed)

    def _record(
        self,
        request: ChatRequest,
        pin: ModelPin,
        route: InferenceRoute,
        response: httpx.Response,
        latency_ms: int,
        hashed: str,
        attempts: int,
        seed: int | None = None,
    ) -> _Reply:
        if response.status_code == 429:
            return _Reply(
                CallFailure(kind=FailureKind.RATE_LIMITED, detail="the endpoint rate limited the call", attempts=attempts, route=route),
                retryable=True,
                limited=True,
                wait_s=retry_after(response.headers),
            )
        if response.status_code >= 500:
            return _Reply(
                CallFailure(
                    kind=FailureKind.FATAL_RESPONSE,
                    detail=f"the endpoint answered {response.status_code}: {response.text[:200]}",
                    attempts=attempts,
                    route=route,
                ),
                retryable=True,
                fatal_status=response.status_code,
            )
        if response.status_code >= 400:
            # 400, 401, 403, 404 and 422 — a malformed request, an invalid key, a forbidden one, an
            # unknown model, an unprocessable body — are fatal at once. Retrying a refusal only spends.
            return _Reply(
                CallFailure(
                    kind=FailureKind.FATAL_RESPONSE,
                    detail=f"the endpoint answered {response.status_code}: {response.text[:200]}",
                    attempts=attempts,
                    route=route,
                ),
                fatal_status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            return _Reply(CallFailure(kind=FailureKind.INVALID_OUTPUT, detail="the endpoint answered with something that is not JSON", attempts=attempts, route=route))
        served = payload.get("model")
        if not isinstance(served, str) or served not in pin.serves:
            named = repr(served) if served is not None else "no model at all"
            return _Reply(
                CallFailure(
                    kind=FailureKind.PIN_FAILURE,
                    detail=f"{pin.model_id!r} was served by {named}, which the pin does not accept",
                    attempts=attempts,
                    route=route,
                )
            )
        text = _completion_text(payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = _reported(usage.get("prompt_tokens")) or estimate_tokens(messages_text(request.messages))
        output_tokens = _reported(usage.get("completion_tokens")) or estimate_tokens(text)
        cost = CostRecorded(
            kind="cost",
            role=request.role,
            model_id=pin.model_id,
            served_model_id=served,
            **self._cost_fields(pin, payload, response.headers, input_tokens, output_tokens),
            route=route,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return _Reply(
            Completion(
                text=text,
                template_id=request.template_id,
                prompt_hash=hashed,
                latency_ms=latency_ms,
                cost=cost,
                seed=seed,
            )
        )

    def _cost_fields(self, pin: ModelPin, payload: dict, headers, input_tokens: int, output_tokens: int) -> dict:
        reported = gateway_cost(payload, headers)
        if reported is not None:
            return {"cost_source": CostSource.GATEWAY, "cost": reported}
        if pin.price is not None:
            return {"cost_source": CostSource.PRICE_TABLE, "cost": price_table_cost(pin.price, input_tokens, output_tokens)}
        return {"cost_source": CostSource.UNKNOWN, "cost": None}

    def _headers(self, context=None) -> dict:
        headers = {"content-type": "application/json"}
        if self.settings.api_key:
            headers["authorization"] = f"Bearer {self.settings.api_key}"
        headers.update(traceparent(context))  # so a gateway's spans nest under the engine's
        return headers

    # --- the replicate-safe cache: a hit is the cache route at zero cost, a miss answers nothing -----------

    async def _cache_hit(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute, data: bytes, hashed: str) -> Completion | None:
        if self._cache is None or route is not InferenceRoute.PRIMARY:
            return None
        entry = self._cache.get(self._cache_key(request, pin, data))
        if entry is None:
            return None
        self.stats.cache_hits += 1
        return Completion(
            text=entry.get("text", ""),
            template_id=request.template_id,
            prompt_hash=entry.get("prompt_hash", hashed),
            latency_ms=0,
            seed=entry.get("seed"),
            cost=CostRecorded(
                kind="cost",
                role=request.role,
                model_id=pin.model_id,
                served_model_id=entry.get("served_model_id"),
                cost_source=CostSource.PRICE_TABLE,
                route=InferenceRoute.CACHE,
                input_tokens=entry.get("input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
                cost=0.0,
            ),
        )

    async def _cache_store(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute, data: bytes, outcome: Completion) -> None:
        # Only the pinned primary's answers are cached: an answer from a fallback must not silently
        # replace a later run's primary, because whether the fallback exists is part of the pin.
        if self._cache is None or route is not InferenceRoute.PRIMARY:
            return
        self._cache.put(
            self._cache_key(request, pin, data),
            {
                "text": outcome.text,
                "prompt_hash": outcome.prompt_hash,
                "served_model_id": outcome.cost.served_model_id,
                "input_tokens": outcome.cost.input_tokens,
                "output_tokens": outcome.cost.output_tokens,
                "seed": outcome.seed,
            },
        )

    def _cache_key(self, request: ChatRequest, pin: ModelPin, data: bytes) -> str:
        assert self._cache is not None
        return self._cache.key(
            pin,
            template_id=request.template_id,
            request_bytes=data,
            template_hash=self._template_hashes.get(request.template_id),
            temp=request.temp,
            sample=request.sample,
        )


def _frozen(message: dict) -> FrozenDict:
    return FrozenDict(message)


def _reported(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _completion_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


def _validation_errors(text: str, schema: dict) -> list[str]:
    """Why this answer does not satisfy the schema — starting with the salvage, so a response the
    schema would accept once its fences are stripped is never called invalid."""
    try:
        value = coerce_json(text)
    except ValueError:
        return ["no JSON value in the response"]
    return validate_schema(value, schema)


REPAIR_SYSTEM = (
    "Your previous answer failed validation: {errors}. Reply only with a JSON value that satisfies "
    "exactly this schema, no prose and no fences: {schema}"
)


def _repair_request(request: ChatRequest, answer: str, errors: list[str], schema: str | None) -> ChatRequest:
    messages = (
        *request.messages,
        FrozenDict({"role": "assistant", "content": answer}),
        FrozenDict({"role": "system", "content": REPAIR_SYSTEM.format(errors="; ".join(errors[:6]), schema=schema or "{}")}),
    )
    return request.model_copy(update={"messages": messages})


def _outcome_attributes(outcome: ChatOutcome | None) -> dict:
    if isinstance(outcome, Completion):
        attributes = {
            GEN_AI_RESPONSE_MODEL: outcome.cost.served_model_id,
            GEN_AI_USAGE_INPUT_TOKENS: outcome.cost.input_tokens,
            GEN_AI_USAGE_OUTPUT_TOKENS: outcome.cost.output_tokens,
            SIMCORE_LATENCY_MS: outcome.latency_ms,
            SIMCORE_COST: outcome.cost.cost,
            SIMCORE_COST_SOURCE: outcome.cost.cost_source.value,
            SIMCORE_ROUTE: outcome.cost.route.value,
            SIMCORE_PROMPT_HASH: outcome.prompt_hash,
            GEN_AI_REQUEST_SEED: outcome.seed,
        }
        return attributes
    if isinstance(outcome, CallFailure):
        return {SIMCORE_FAILURE_KIND: outcome.kind.value, SIMCORE_FAILURE_DETAIL: outcome.detail, SIMCORE_ATTEMPTS: outcome.attempts, SIMCORE_ROUTE: outcome.route.value}
    return {}
