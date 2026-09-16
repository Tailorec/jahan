"""Dispatch at scale: a bounded queue, an adaptive in-flight ceiling, and a limiter on requests and tokens.

A tick's worth of calls must not become a coroutine per call or a storm of 429s. A bounded queue feeds
workers under a ceiling set to what the endpoint can serve; sustained 429s lower the ceiling and
successes restore it toward the configured maximum. Token counts are estimated from text before a call
is sent and corrected from reported usage after it, so a systematic underestimate stops exceeding the
token limit. `Retry-After` holds the next attempt at least as long as it says.

Time comes from an injected clock and sleeps from an injected awaitable, so the whole mechanism is
testable without a stopwatch."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from simcore.schemas import CallFailure, ChatOutcome, ChatRequest, Completion, InferenceRoute

from ._wire import estimate_tokens, messages_text

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


@dataclass
class DispatchStats:
    """What one batch measured about itself, kept for the operator and the tests — never the trace."""

    in_flight_peak: int = 0
    queued_peak: int = 0
    ceiling_lowest: int | None = None
    ceiling_final: int = 0
    rate_limited: int = 0
    cache_hits: int = 0


class AdaptiveCeiling:
    """How many calls may be in flight at once. A 429 halves the ceiling; a success walks it back up
    toward the configured maximum, so the endpoint's refusals decide the pace, not a guess."""

    def __init__(self, maximum: int, *, minimum: int = 1) -> None:
        self.maximum = maximum
        self.minimum = minimum
        self.value = maximum
        self.in_flight = 0
        self.lowest = maximum
        self._cond = asyncio.Condition()

    async def acquire(self) -> None:
        async with self._cond:
            while self.in_flight >= self.value:
                await self._cond.wait()
            self.in_flight += 1
            self.lowest = min(self.lowest, self.value)

    async def release(self) -> None:
        async with self._cond:
            self.in_flight -= 1
            self._cond.notify()

    async def lower(self) -> None:
        async with self._cond:
            self.value = max(self.minimum, self.value // 2)
            self.lowest = min(self.lowest, self.value)

    async def restore(self) -> None:
        async with self._cond:
            if self.value < self.maximum:
                self.value += 1
                self._cond.notify()


class _Bucket:
    """A continuous token bucket: it starts empty, so the requests (or tokens) issued in any window of
    its period never exceed what the endpoint agreed to serve in it."""

    def __init__(self, per_minute: float, clock: Clock, sleep: Sleep) -> None:
        self._rate = per_minute / 60.0
        self.capacity = per_minute
        self.balance = 0.0
        self._clock, self._sleep = clock, sleep
        self._since = clock()

    def _refill(self) -> None:
        now = self._clock()
        self.balance = min(self.capacity, self.balance + (now - self._since) * self._rate)
        self._since = now

    async def acquire(self, amount: float = 1.0) -> None:
        while True:
            self._refill()
            if self.balance >= amount:
                self.balance -= amount
                return
            # The sleep overshoots by a hair: a wait computed as deficit/rate can refill to a balance a
            # float short of the amount, and a zero-length sleep would then spin forever.
            await self._sleep((amount - self.balance) / self._rate + 1e-9)

    def settle(self, delta: float) -> None:
        """Return what an over-estimate reserved; a negative delta records the debt an under-estimate ran."""
        self.balance = min(self.capacity, self.balance + delta)


class RateLimiter:
    """Requests and tokens per minute, with a shared penalty window for `Retry-After`."""

    def __init__(
        self,
        requests_per_minute: float | None,
        tokens_per_minute: float | None,
        clock: Clock,
        sleep: Sleep,
    ) -> None:
        self._requests = _Bucket(requests_per_minute, clock, sleep) if requests_per_minute else None
        self._tokens = _Bucket(tokens_per_minute, clock, sleep) if tokens_per_minute else None
        self._penalty_until = 0.0
        self._clock, self._sleep = clock, sleep

    async def acquire(self, estimated_tokens: float) -> None:
        now = self._clock()
        if now < self._penalty_until:
            await self._sleep(self._penalty_until - now)
        if self._requests is not None:
            await self._requests.acquire(1.0)
        if self._tokens is not None:
            await self._tokens.acquire(estimated_tokens)

    def admissible(self, estimated_tokens: float) -> bool:
        """Whether a call this size can ever be admitted: a bucket holds at most one minute's tokens, so a
        call estimated above that would wait forever rather than fail."""
        return self._tokens is None or estimated_tokens <= self._tokens.capacity

    @property
    def tokens_per_minute(self) -> float | None:
        return self._tokens.capacity if self._tokens is not None else None

    def settle(self, estimated_tokens: float, actual_tokens: float) -> None:
        if self._tokens is not None:
            self._tokens.settle(estimated_tokens - actual_tokens)

    def penalize(self, seconds: float) -> None:
        self._penalty_until = max(self._penalty_until, self._clock() + seconds)


def request_estimate(request: ChatRequest) -> float:
    """What a call is expected to cost before it is sent: the prompt by its text length, and the whole
    budget for the answer, because an endpoint reserves what the request allows rather than what it gives."""
    return float(estimate_tokens(messages_text(request.messages)) + request.max_tokens)


def _settle_from(outcome: ChatOutcome, estimate: float, limiter: RateLimiter) -> None:
    if isinstance(outcome, Completion):
        limiter.settle(estimate, float(outcome.cost.input_tokens + outcome.cost.output_tokens))


def retry_after(headers) -> float | None:
    """Seconds a `Retry-After` asks for, in either of the forms a gateway sends — a delta or a date."""
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    from datetime import UTC, datetime

    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())
