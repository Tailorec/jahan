# Plan: M4 `inference` — every model call, recorded as what it was

> Source PRD: `docs/prd/M4-inference.md`
> Binding decisions: ADR 0021 (one OpenAI-compatible endpoint, no provider imports), ADR 0022 (OTLP telemetry that is not the trace), ADR 0023 (batches answered in request order, failures as outcomes), ADR 0024 (completed attitudes sampled by the engine), ADR 0025 (no cached sample shared across replicates), ADR 0009 and 0012 (pins verified, routes recorded), ADR 0011 (replay reads the trace), ADR 0016 (no corpus content leaves by accident), ADR 0019 (the conditional variance and the holdout owed here). `CONTEXT.md` (Pinned Model, Served Model, Pin Failure, Cost Source, Completion Temperature, Holdout Evaluation). Where `FINAL_ARCH.md` §5.4 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **One endpoint, one protocol** — OpenAI Chat Completions and Embeddings over `httpx`, to a base URL the user configures. No provider SDK and no gateway library is imported anywhere; a gateway, LiteLLM by default, owns provider translation. The request bytes the engine hashes are the bytes it sends.
- **Batch first** — `complete(requests) -> outcomes` is synchronous to its caller and concurrent inside, returns one outcome per request in request order, and an outcome is a `Completion` or a `CallFailure`. `chat()` is one request over it. A failed call is recorded, never raised for one request and never dropped.
- **The engine owns every policy that changes the trace** — retries, the pinned fallback, the cache and rate limiting live in the engine; the gateway is a translator with its own retries, fallbacks and caching documented off.
- **A pin is a specification** — the model name sent, the served identifiers accepted, structured-output and seed capability, and an optional price. A call served outside its pin is a pin failure. Embedding never falls back.
- **A cost says where it came from** — `gateway`, `price_table` or `unknown`; unknown is recorded as absent, never as zero. Budget enforcement belongs to `runner`.
- **A sampled answer belongs to one replicate** — the cache key carries a sample key for any call above temperature zero; replay reads the trace, never the cache.
- **Variance is the engine's** — completed attitudes are sampled by the engine from the model's distribution under the population seed at a recorded temperature.
- **Execution configuration is not study configuration** — endpoint, key, concurrency, rate limits, timeouts and retry counts come from the environment and are never hashed; pins, prices, temperatures and templates are on `RunConfig` and `PopulationParameters` and are.
- **Telemetry is not the trace** — OTLP spans, metadata only unless content capture is enabled, and nothing analytical reads them. The core depends on `opentelemetry-api` alone.
- **Contract amendments come first** — nothing can record a served model, a cost source or a failure outcome that does not exist yet. `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities are re-pinned.
- **Test posture** — a scripted HTTP transport drives the real client and its policies; `FakeChat` serves the modules that call inference. The suite never reaches a network.

---

## Phase 1: Contracts — pins, cost events and failure outcomes

**User stories**: 4, 12, 13, 14 (the shapes)

### What to build

The shapes the rest of the module records into. A pin stops being a bare model identifier and becomes a specification: the name sent to the endpoint, the served identifiers it accepts, whether it supports structured output and honours a seed, and an optional price. A cost event gains the model that actually served the call and where its cost came from, and a cost may be absent when nobody knows it. A failed call gains a first-class outcome that names what went wrong, how many attempts were made and which route was last tried.

Nothing produces these yet. The phase is done when the shapes exist, refuse contradictions, and every existing pin in the suite still validates.

### Acceptance criteria

- [x] A pin carries the model name sent, its accepted served identifiers, its structured-output and seed capabilities and an optional price, and a bare model identifier still reads as a pin accepting only itself
- [x] The embedding role still refuses a fallback, and a fallback identical to its primary is still refused
- [x] A cost event records the served model beside the pinned one and a cost source of gateway, price table or unknown
- [x] An unknown cost is absent rather than zero, a known cost is present, and a contradiction between the two is refused
- [x] A cached call still bills nothing
- [x] A call failure names its kind — rate limited, timed out, fatal response, circuit open, pin failure or invalid output — its attempts and its last route
- [x] Pinned identities in `tests/fixtures/hash_stability.json` are re-pinned with the change recorded in the commit that moves them

---

## Phase 2: One call, recorded truthfully

**User stories**: 1, 2, 4, 12, 13, 14

### What to build

A single model call through the real client, end to end: a role resolves to its pin or is refused before any network call; the request is serialized once, hashed, and sent as exactly those bytes; the response is parsed into a completion that records its latency, tokens, served model and cost with its source. The first successful call records the served model, and a later call served by a model outside the pin's accepted identifiers comes back as a pin failure rather than a completion.

It is proven against a scripted transport, so the suite still never opens a socket.

### Acceptance criteria

- [x] An unpinned role is refused before any request is sent
- [x] The prompt hash is computed from exactly the bytes sent, and changing any request field changes it
- [x] A completion records served model, input and output tokens, latency and the route it came by
- [x] A gateway-reported cost is recorded as gateway; a declared price computes a price-table cost; neither yields unknown
- [x] A response served by an undeclared model is a pin failure, and one served by a declared alias is a completion
- [x] A served model that changes mid-run is caught on the first call it changes
- [x] The engine imports no provider SDK or gateway library, asserted rather than assumed
- [x] No test reaches the network

---

## Phase 3: The batch port

**User stories**: 7, 8, 10

### What to build

The interface every other module calls. A batch of requests goes in; one outcome per request comes back in request order, whatever order the responses arrived in; a failed call is a recorded outcome beside the completions around it. The concurrency lives on an event loop of the module's own, so a caller that is already inside a running loop, like a notebook, calls it the same way.

The deterministic fake grows the same shape with injectable failures, and audience interpretation moves onto the batch port as its first real consumer.

### Acceptance criteria

- [x] Outcomes return in request order when the transport answers them in reverse
- [x] One failing request leaves every other outcome in its batch a completion, and the failure is recorded, not raised
- [x] The batch call works from inside a running event loop
- [x] A single-request call is exactly a batch of one
- [x] The fake answers batches deterministically across processes and can inject each failure kind
- [x] Audience interpretation runs through the batch port with its behaviour and tests unchanged

---

## Phase 4: At scale

**User stories**: 5, 6

### What to build

A tick's worth of calls held without a coroutine per call and without a storm of 429s. A bounded queue feeds a concurrency ceiling set to what the endpoint can serve; an adaptive limiter holds both requests and tokens per minute, estimating tokens from text before sending and correcting from reported usage. Sustained 429s lower the ceiling and successes restore it, and a `Retry-After` is honoured.

### Acceptance criteria

- [x] A batch far larger than the concurrency ceiling never has more calls in flight than the ceiling, asserted at the transport
- [x] Memory held by queued requests does not grow with batch size beyond the queue's bound
- [x] Neither the request nor the token rate limit is exceeded over a measured window
- [x] Token estimates are corrected by reported usage, so a systematic underestimate stops exceeding the token limit
- [x] A run of 429s lowers the in-flight ceiling, and a run of successes raises it back toward the configured maximum
- [x] A `Retry-After` delays the next attempt by at least what it says

---

## Phase 5: Retries, the pinned fallback and the circuit breaker

**User stories**: 9, 16

### What to build

What happens when an endpoint misbehaves. Rate limiting, server errors, timeouts and connection failures are retried with backoff; malformed, unauthorized, forbidden, not-found and unprocessable requests fail at once. When retries are exhausted the call moves to the role's pinned fallback and is recorded as the fallback route; an unpinned fallback is never used and embedding never falls back. A short run of identical fatal errors — an invalid key, an unknown model — opens a circuit that fails the rest of the batch with one clear error instead of thousands.

### Acceptance criteria

- [x] 429, 5xx, timeouts and connection errors are retried, and 400, 401, 403, 404 and 422 are not
- [x] A call that exhausts its retries is served by the pinned fallback and recorded with the fallback route and its served model
- [x] A role with no pinned fallback records a failure after its retries, and embedding never falls back
- [x] A handful of identical fatal errors fails the remaining batch as circuit open, without sending the remaining requests
- [x] Retry counts and backoff are execution configuration and appear in no hashed contract

---

## Phase 6: The replicate-safe cache

**User stories**: 17

### What to build

A persistent cache in the user cache directory that makes a re-run cheap without making replicates identical. Its key covers the served model, the template id and hash, the exact request bytes and — for any call above temperature zero — a sample key from replicate seed, persona and tick. A temperature-zero call may be shared. A hit is recorded as the cache route and bills nothing; replay never consults it.

### Acceptance criteria

- [x] Re-running the same seed serves its sampled calls from the cache, recorded as the cache route at zero cost
- [x] Two replicate seeds never receive the same cached sample for a call above temperature zero
- [x] A temperature-zero call is shared across replicates
- [x] A changed served model, template or request byte never serves an old answer
- [x] The cache survives a new process and lives outside the repository
- [x] Deleting the cache changes cost and never changes a result

---

## Phase 7: Seeds and structured output

**User stories**: 18, 23

### What to build

What a pin's declared capabilities change about a request. A pin that honours seeds is sent one derived from world seed, persona, tick and sequence, and the seed is recorded; a pin that does not is sent none, and determinism is never promised. A pin declaring structured output receives a strict schema. Every response is parsed leniently, validated, repaired once with a stricter prompt, and otherwise recorded as an invalid-output failure — so a small model that cannot follow a schema still completes where it can.

### Acceptance criteria

- [x] A seed-honouring pin is sent a seed derived from world seed, persona, tick and sequence, and the seed is recorded
- [x] A pin that does not honour seeds is sent no seed
- [x] A structured-output pin receives a strict schema and one without that capability does not
- [x] Leniently parseable output is accepted after validation, and output that fails validation is repaired once
- [x] Output still invalid after repair is an invalid-output failure, never a coerced value

---

## Phase 8: Embeddings

**User stories**: 1

### What to build

Embeddings through the same endpoint, client and limiter, sent in capped batches to one pinned model. Every vector's dimension is checked against the first the run received, the normalisation applied is recorded, and the embedding role never falls back, because anchors and responses scored in different embedding spaces are not comparable.

### Acceptance criteria

- [x] Texts are embedded through the same endpoint and limiter as chat calls
- [x] Batches respect a size cap and return vectors in input order
- [x] A vector whose dimension differs from the run's first is refused
- [x] The normalisation applied is recorded
- [x] An exhausted embedding call fails; it never falls back

---

## Phase 9: Sampled completion

**User stories**: 19, 20, 21, 22

### What to build

Projection stops asking for a value at temperature zero and asks for a probability distribution over each attribute's vocabulary per persona, submitting all of its batches in one call. The engine validates that each distribution covers the vocabulary and sums to one, applies the study's recorded completion temperature, and samples with the population's seeded stream. A population records the distribution each completed field was drawn from, so projection's calibration can be measured later. This changes module 3 and moves pinned population identities.

### Acceptance criteria

- [x] Projection submits its completion batches through one batch call
- [x] A completed field is sampled from the returned distribution under the population's seed, and the same seed and distributions reproduce it
- [x] A different population seed samples differently from the same distributions
- [x] Completion temperature is a recorded population parameter, and raising it measurably widens the sampled values
- [x] A distribution missing a vocabulary value or not summing to one leaves the field uncompleted
- [x] A population records the distribution behind each completed field, and it survives a round trip
- [x] Demographic and psychographic fields are still never completed
- [x] Moved population identities are re-pinned, with the change recorded in the commit that moves them

---

## Phase 10: Telemetry

**User stories**: 26, 27, 28

### What to build

OpenTelemetry spans for every batch and call, exported over OTLP to whatever collector a user configures and doing nothing when none is. Retries and fallbacks are span events; attributes use the GenAI conventions, named in one place; world, tick and persona identifiers join spans to the trace without making spans a record anything reads. Prompt and response content is never attached unless capture is explicitly enabled, and trace context is propagated so a gateway's spans nest under the engine's.

### Acceptance criteria

- [x] The core depends on the OpenTelemetry API only, and the SDK and exporter are an optional extra
- [x] With no telemetry configured, calls produce no spans and cost no measurable time
- [x] A batch produces one batch span and one span per call, with retries and fallbacks as events
- [x] No span carries prompt or response content unless capture is enabled, asserted over every attribute
- [x] Every GenAI attribute name is defined in one module
- [x] Requests carry trace context for a gateway to join
- [x] No analytical code path reads a span

---

## Phase 11: The holdout evaluation

**User stories**: 24, 25

### What to build

The measurement projection's credibility rests on. On Stack Overflow rows carrying measured attitudes, a declared attitude set is hidden, projected from the conditioning set through the production path, and scored: per-attribute marginal distance, calibration of the sampled distributions, and how much of the attitudes' dependence on demographics is recovered — all beside a baseline that samples each attitude from its demographic-conditional marginal in rows not held out. The report records the pins, served models, seeds and parameters that produced it. It runs on the fake in CI and against a real endpoint when a user configures one.

### Acceptance criteria

- [x] Held-out rows are never used to build the baseline
- [x] The evaluation reports marginal distance, calibration and recovered demographic dependence per attribute, beside the baseline's
- [x] The report records pins, served models, seeds, completion temperature and row counts
- [x] A fake that returns the true conditional marginals scores at the baseline, and one that returns uniform distributions scores worse — so the metrics are proven to discriminate
- [x] It runs on the fake in CI, and against the cached real shards when they are present
- [x] Pointed at a real endpoint, it runs from one documented command

---

## Phase 12: Gateway documentation and reconciliation

**User stories**: 3, 11

### What to build

The documentation that makes one endpoint usable, and the documents brought back into step with what was built. LiteLLM, vLLM and Ollama each get a working configuration, including turning a gateway's own retries, fallbacks and caching off and using its request and token limits as a shared ceiling for several engine processes. `FINAL_ARCH.md`, `SALVAGE.md` and `CONTEXT.md` are checked against the code, and anything that changed during implementation is reconciled. Budget refusal of unknown costs is recorded as owed to `runner`, not claimed here.

### Acceptance criteria

- [ ] LiteLLM, vLLM and Ollama each have a configuration a user can follow without reading source
- [ ] The LiteLLM configuration turns off its retries, fallbacks and caching, and explains why
- [ ] Running several engine processes against one gateway's shared limits is documented
- [ ] `FINAL_ARCH.md` §5.4, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
- [ ] Refusing unknown costs is recorded as owed to `runner`, with story 15 marked deferred rather than done
