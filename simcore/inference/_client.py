"""`InferenceClient`: every model call through one OpenAI-compatible endpoint, recorded as what it was.

The engine speaks one protocol over `httpx` and imports no provider SDK and no gateway library (ADR
0021); which provider answers is the gateway's business. A role resolves to its pin before any byte
leaves, the request body is serialized once and sent as exactly those bytes, and the response is
recorded as a `Completion` naming the model that served it, its tokens, latency and cost with its
source — or as a `CallFailure` (ADR 0023). A call answered by a model outside its pin's accepted
identifiers is a pin failure, never a result.
"""

import asyncio
import time
from collections.abc import Callable, Sequence

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


class InferenceClient:
    """The batch port: `complete(requests) -> outcomes`, synchronous and order-preserving outside,
    concurrent inside, with a `chat()` facade over a batch of one."""

    def __init__(
        self,
        pins: ModelPins,
        settings: ExecutionSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pins = pins
        self.settings = settings or ExecutionSettings()
        self._clock = clock
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
        return run(self._gather(requests, pins))

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

    async def _gather(self, requests: Sequence[ChatRequest], pins: Sequence[ModelPin]) -> tuple[ChatOutcome, ...]:
        outcomes = await asyncio.gather(
            *(self._attempt(request, pin) for request, pin in zip(requests, pins, strict=True))
        )
        return tuple(outcomes)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _attempt(self, request: ChatRequest, pin: ModelPin) -> ChatOutcome:
        return await self._exchange(request, pin, InferenceRoute.PRIMARY)

    async def _exchange(self, request: ChatRequest, pin: ModelPin, route: InferenceRoute) -> ChatOutcome:
        body = chat_body(request, pin)
        data = body_bytes(body)
        started = self._clock()
        try:
            response = await self._http.post(CHAT_PATH, content=data, headers=self._headers())
        except httpx.TimeoutException:
            return CallFailure(kind=FailureKind.TIMED_OUT, detail=f"the endpoint did not answer {request.template_id!r} within {self.settings.timeout_s}s", attempts=1, route=route)
        except httpx.HTTPError as error:
            return CallFailure(kind=FailureKind.FATAL_RESPONSE, detail=f"the endpoint could not be reached: {error}", attempts=1, route=route)
        latency_ms = max(0, int((self._clock() - started) * 1000))
        return self._record(request, pin, route, response, latency_ms, prompt_hash(data))

    def _record(
        self,
        request: ChatRequest,
        pin: ModelPin,
        route: InferenceRoute,
        response: httpx.Response,
        latency_ms: int,
        hashed: str,
    ) -> ChatOutcome:
        if response.status_code == 429:
            return CallFailure(kind=FailureKind.RATE_LIMITED, detail="the endpoint rate limited the call", attempts=1, route=route)
        if response.status_code >= 400:
            return CallFailure(
                kind=FailureKind.FATAL_RESPONSE,
                detail=f"the endpoint answered {response.status_code}: {response.text[:200]}",
                attempts=1,
                route=route,
            )
        try:
            payload = response.json()
        except ValueError:
            return CallFailure(kind=FailureKind.INVALID_OUTPUT, detail="the endpoint answered with something that is not JSON", attempts=1, route=route)
        served = payload.get("model")
        if not isinstance(served, str) or served not in pin.serves:
            named = repr(served) if served is not None else "no model at all"
            return CallFailure(
                kind=FailureKind.PIN_FAILURE,
                detail=f"{pin.model_id!r} was served by {named}, which the pin does not accept",
                attempts=1,
                route=route,
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
            **self._cost_fields(request.role, pin, payload, response.headers, input_tokens, output_tokens),
            route=route,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return Completion(
            text=text,
            template_id=request.template_id,
            prompt_hash=hashed,
            latency_ms=latency_ms,
            cost=cost,
        )

    def _cost_fields(self, role, pin, payload, headers, input_tokens, output_tokens) -> dict:
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
