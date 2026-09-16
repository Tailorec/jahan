# Model calls are requested in batches, answered in request order, and fail as outcomes

A study's model calls come in batches by nature: one tick's turns are simultaneous in simulated time, since engagement is invisible within the tick it happens (ADR 0010), and a population's completions are independent of each other. Reaching an endpoint's real capacity means sending those calls concurrently, and every concern that comes with it — a bounded queue, a concurrency ceiling, request and token rate limits, backoff, the pinned fallback, the cache — has one correct owner. The inference port is therefore `complete(requests) -> outcomes`: synchronous to its caller, concurrent inside, returning one outcome per request **in request order**, where an outcome is either a `Completion` or a recorded failure. `chat()` remains as a one-request convenience over it.

## Considered options

An async port was rejected: it would make population, agent, world and runner async and their tests event-loop bound, where a missing `await` compiles and fails at run time, to gain a concurrency only inference needs to manage. A single-call port with callers using threads was rejected because every module would re-solve limiting and backoff, differently. Returning outcomes in completion order was rejected because it makes a caller's result depend on network timing.

## Consequences

Failure is a value, not an exception and not an absence. One failed call among twenty-five thousand neither aborts the others nor vanishes — the silent failure OASIS has, where an agent's exception is logged and returned and the simulation continues as if it had acted. The caller decides what a failure means, a failed turn or an uncompleted field, and the trace records it. A tick closes only when every outcome is recorded, never on a timer, so which personas acted can never depend on how fast a provider answered.

A synchronous facade over an async core cannot call `asyncio.run` from inside a running loop, as in a notebook or a future async runner, so inference runs its loop on a dedicated thread. Projection submits all of its completion batches in one call and becomes concurrent without knowing it.
