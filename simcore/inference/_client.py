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
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

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

from ._dispatch import (
    AdaptiveCeiling,
    DispatchStats,
    RateLimiter,
    request_estimate,
    retry_after,
)
from ._loop import run
from ._settings import ExecutionSettings
from ._wire import (
    CHAT_PATH,
    body_bytes,
    chat_body,
    estimate_tokens,
    gateway_cost,
    messages_text,
    price_table_cost,
    prompt_hash,
)


class UnpinnedRoleError(ValueError):
    """A study asked a role it never pinned. Refused before any network call: a misconfigured study
    fails in a second rather than after spending."""


@dataclass(frozen=True)
class _Reply:
    """One exchange's outcome plus what the dispatcher should make of it."""

    outcome: ChatOutcome
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
    ) -> None:
        self.pins = pins
        self.settings = settings or ExecutionSettings()
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._ceiling = AdaptiveCeiling(self.settings.max_concurrency)
        self._limiter = RateLimiter(
            self.settings.requests_per_minute, self.settings.tokens_per_minute, self._clock, self._sleep
        )
        self.stats = DispatchStats()
        # A short run of identical fatal errors — an invalid key, an unknown model — is not a thousand
        # separate misfortunes. The run is counted here and opens one circuit for the client.
        self._consecutive_fatals: dict[int, int] = {}
        self._circuit_detail: str | None = None
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
        return run(self._gather(list(requests), pins))

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

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- the batch: a bounded queue feeding workers under the ceiling -----------------------------------

    async def _gather(self, requests: list[ChatRequest], pins: list[ModelPin]) -> tuple[ChatOutcome, ...]:
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
                outcomes[index] = await self._execute(request, pin)

        producer = asyncio.create_task(produce())
        crew = [asyncio.create_task(work()) for _ in range(workers)]
        await asyncio.gather(producer, *crew)
        self.stats.ceiling_final = self._ceiling.value
        self.stats.ceiling_lowest = self._ceiling.lowest
        return tuple(outcomes)  # type: ignore[arg-type]

    async def _execute(self, request: ChatRequest, pin: ModelPin) -> ChatOutcome:
        routes = [(InferenceRoute.PRIMARY, pin)]
        fallback = self.pins.fallbacks.get(request.role)
        if request.role is not InferenceRole.EMBED and fallback is not None:
            routes.append((InferenceRoute.FALLBACK, fallback))
        last: ChatOutcome | None = None
        for route, route_pin in routes:
            last = await self._attempt_route(request, route_pin, route)
            if isinstance(last, Completion):
                return last
        assert last is not None
        return last

    async def _attempt_route(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute) -> ChatOutcome:
        attempts = 0
        while True:
            if self._circuit_detail is not None:
                return CallFailure(kind=FailureKind.CIRCUIT_OPEN, detail=self._circuit_detail, attempts=attempts, route=route)
            await self._ceiling.acquire()
            self.stats.in_flight_peak = max(self.stats.in_flight_peak, self._ceiling.in_flight)
            estimate = request_estimate(request)
            try:
                await self._limiter.acquire(estimate)
                attempts += 1
                reply = await self._exchange(request, pin, route, attempts)
            finally:
                await self._ceiling.release()
            if isinstance(reply.outcome, Completion):
                self._limiter.settle(estimate, float(reply.outcome.cost.input_tokens + reply.outcome.cost.output_tokens))
                self._consecutive_fatals.clear()
            if reply.limited:
                self.stats.rate_limited += 1
                await self._ceiling.lower()
            else:
                await self._ceiling.restore()
            if reply.fatal_status is not None:
                self._trip(pin, route, reply.fatal_status)
            if not reply.retryable or attempts > self.settings.max_retries:
                return reply.outcome
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

    async def _exchange(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute, attempts: int) -> _Reply:
        body = chat_body(request, pin)
        data = body_bytes(body)
        started = self._clock()
        try:
            response = await self._http.post(CHAT_PATH, content=data, headers=self._headers())
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
        return self._record(request, pin, route, response, latency_ms, prompt_hash(data), attempts)

    def _record(
        self,
        request: ChatRequest,
        pin: ModelPin,
        route: InferenceRoute,
        response: httpx.Response,
        latency_ms: int,
        hashed: str,
        attempts: int,
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
            )
        )

    def _cost_fields(self, pin: ModelPin, payload: dict, headers, input_tokens: int, output_tokens: int) -> dict:
        reported = gateway_cost(payload, headers)
        if reported is not None:
            return {"cost_source": CostSource.GATEWAY, "cost": reported}
        if pin.price is not None:
            return {"cost_source": CostSource.PRICE_TABLE, "cost": price_table_cost(pin.price, input_tokens, output_tokens)}
        return {"cost_source": CostSource.UNKNOWN, "cost": None}

    def _headers(self) -> dict:
        headers = {"content-type": "application/json"}
        if self.settings.api_key:
            headers["authorization"] = f"Bearer {self.settings.api_key}"
        return headers


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
