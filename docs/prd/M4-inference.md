# PRD — M4 `inference`: every model call, recorded as what it was

## Problem Statement

Three modules and a corrective pass are complete, and the engine has never made a model call. `ChatPort` and `EmbedPort` are protocols with deterministic fakes; nothing speaks to a model, and every consumer — projection, audience interpretation, and later the agent's turns — runs against a stand-in.

The architecture's inference section predates what the corpus taught. ADR 0018 made projection produce every category attitude rather than a few sparse fields, so model calls now decide most of what a persona believes. And the section assumed the engine would carry each provider itself, which for an open-source research tool means owning Bedrock's, Anthropic's and OpenRouter's authentication, formats and failure modes.

The risk this module addresses is that a model call can change a study without the study knowing. A gateway can substitute a quantized model under the pinned name. A cache can hand five replicate seeds the same sample and erase the spread their comparison depends on. A provider's sampling temperature can make an attitude's variance a property of whoever served it. An exception can make a persona silently not act — the failure OASIS has. And an attitude completed at temperature zero is a deterministic function of the demographics the social graph is also built on, which inflates opinion clustering by construction (ADR 0019). Each of these produces confident numbers.

At scale the question is not whether calls can be concurrent but whether they are controlled. A million-persona world activates roughly 620,000 turns per tick; the engine must hold that without a coroutine per call, without a storm of 429s, and without letting a slow afternoon decide which personas acted.

## Solution

One module, one batch function, and the policies that change what the trace must say.

`complete(requests) -> outcomes` is synchronous to its caller and concurrent inside. It returns one outcome per request in request order — a `Completion` or a recorded failure — so a caller never depends on network timing and one failure never aborts or erases the rest (ADR 0023). `chat()` is one request over it; `embed()` batches texts to one pinned model.

The engine speaks one protocol — OpenAI Chat Completions and Embeddings — over `httpx` to a base URL the user configures, importing no provider SDK and no gateway library (ADR 0021). A self-hosted LiteLLM proxy is the documented default, reaching Bedrock, Anthropic and hosted providers; vLLM and Ollama are reached directly. Gateway retries, fallbacks and caching are documented off, because the engine owns all three and only the engine writes the trace.

Around that, five commitments. A call answered by a model outside its pin is a failure, not a result. A cost says where it came from, and an unknown cost stays unknown. A sampled answer is never shared across replicates (ADR 0025). A completed attitude is sampled by the engine from a distribution the model gives, at a recorded temperature, under the population's seed (ADR 0024). And telemetry is exported as OpenTelemetry, carries no persona content by default, and is never the scientific record (ADR 0022).

## User Stories

**Choosing where models run**

1. As a researcher, I want to point the engine at one OpenAI-compatible URL, so I can use Bedrock, Anthropic, OpenRouter, vLLM or Ollama without the engine supporting each.
2. As a maintainer, I want the engine to import no provider SDK or gateway library, so a new provider is a user's configuration rather than a change to the engine.
3. As a user running local models, I want documented configurations for LiteLLM, vLLM and Ollama, so setting one up is following steps rather than reading source.
4. As a user, I want an unpinned role refused before any network call, so a misconfigured study fails in a second rather than after spending.

**Running at scale**

5. As a researcher, I want a tick's calls sent concurrently up to what my endpoint can actually serve, so a large study finishes in hours rather than days.
6. As an operator, I want request and token rate limits that adapt to 429s, so a burst slows down rather than failing.
7. As a researcher, I want results returned in request order whatever order they arrive in, so a study's outcome never depends on network timing.
8. As an analyst, I want one failed call recorded as a failure while the rest of its batch completes, so no persona silently fails to act.
9. As a user, I want an invalid key or unknown model to fail the whole batch with one clear error, so I do not wait for twenty-five thousand identical failures.
10. As a notebook user, I want the batch call to work from inside a running event loop, so the engine is usable where research is done.
11. As an operator running several engine processes, I want documented gateway limits as a shared ceiling, so concurrent studies do not exceed a provider quota together.

**Recording truthfully**

12. As a methodologist, I want the model that actually served each call recorded beside the pinned one, so a gateway substitution is visible.
13. As a methodologist, I want a call served by a model outside its pin's declared aliases recorded as a pin failure, so no result comes from a model the study did not name.
14. As an analyst, I want every cost to state whether a gateway reported it, a declared price computed it, or it is unknown, so a budget is never enforced against invented prices.
15. As a researcher, I want budget enforcement to refuse unknown costs unless I explicitly accept unbudgeted spend, so a study cannot overspend silently. **(Deferred to `runner`, not done in M4:** inference records every cost's source truthfully; the refusal belongs to the module that owns the budget.**)**
16. As a researcher, I want a pinned fallback used only after the primary is exhausted and recorded as the fallback route, so a substitution is bounded and visible.
17. As a researcher, I want a re-run of the same seeds served from the cache and a new seed never served another replicate's sample, so re-runs are cheap and replicate spread stays real.
18. As a maintainer, I want the seed each call was sent with recorded where the provider honours seeds, so provenance is complete without promising determinism a provider does not give.

**Filled-in attitudes**

19. As a methodologist, I want a completed attitude sampled by the engine from the model's distribution under the population's seed, so its variance is reproducible whatever the provider does.
20. As a researcher, I want the completion temperature to be a recorded study parameter, so how much attitudes vary beyond demographics is a choice I can sweep.
21. As a methodologist, I want a distribution that does not cover the vocabulary or sum to one refused, so a malformed answer leaves a field uncompleted rather than inventing one.
22. As a maintainer, I want projection to submit all its completion batches in one call, so building a population is concurrent without projection managing concurrency.
23. As a researcher, I want a pin to declare whether it supports structured output, so a small model that cannot follow a strict schema still completes through validation and repair.

**Evidence**

24. As a researcher, I want a holdout evaluation that hides measured Stack Overflow attitudes, projects them from demographics and reports marginal distance and calibration against a demographic-conditional baseline, so whether projected attitudes mean anything is measured rather than asserted.
25. As a maintainer, I want that evaluation to run on the fake in CI and on a real endpoint when configured, so it cannot rot and can produce a real number.

**Observing a run**

26. As an operator, I want OpenTelemetry spans for batches and calls exported to whatever OTLP collector I run, so I can see latency, retries, cost and failures in the tool I already use.
27. As a researcher bound by the corpus terms, I want spans to carry no prompt or response content unless I enable it, so observability never redistributes persona data.
28. As a maintainer, I want the core to depend only on the OpenTelemetry API, so telemetry costs nothing until configured.

## Implementation Decisions

**The batch port.** `complete(requests) -> outcomes` with outcomes in request order. An outcome is a `Completion` or a `CallFailure` naming its kind — rate limited past retries, timed out, fatal response, circuit open, pin failure, invalid output — its attempts and the route last tried. The async core runs one event loop on a dedicated thread, so the synchronous facade is safe inside a running loop. `chat()` wraps a single request. The existing callers, projection and audience interpretation, move to the batch form.

**Transport.** `httpx` against `/v1/chat/completions` and `/v1/embeddings`. The request body is serialized once, hashed, and sent as those exact bytes. Response headers are read for a gateway's reported cost and served provider. Trace context is propagated in request headers so a gateway's spans nest under the engine's. No streaming.

**Queue and limiting.** A bounded queue, a concurrency ceiling configured to the endpoint's capacity, and an adaptive limiter on requests and tokens per minute. Token counts are estimated from text length before sending and corrected from reported usage; sustained 429s lower the ceiling and successes restore it. `Retry-After` is honoured.

**Retry, fallback and circuit breaking.** 429, 5xx, timeouts and connection errors retry with backoff; 400, 401, 403, 404 and 422 are fatal at once. A short run of identical fatal errors opens a circuit that fails the remaining batch with one error. Exhausted retries move to the role's pinned fallback; an unpinned fallback is never used, and embedding has none.

**Pins.** A pin becomes a specification rather than a bare identifier: the model name sent, the served identifiers it accepts, whether it supports structured output, whether it honours `seed`, and an optional price. The first success records the served model; any later call served outside the accepted set is a pin failure.

**Cost.** `CostRecorded` gains `served_model_id` and `cost_source` of `gateway`, `price_table` or `unknown`; an unknown cost is recorded as absent rather than zero, and a cached call bills zero as today. The runner's budget refuses unknown costs unless unbudgeted spend is accepted.

**Cache.** Persistent, in the user cache directory, keyed by served model, template id and hash, the exact request bytes, and for calls above temperature zero a sample key from replicate seed, persona and tick. Replay reads the trace and never the cache.

**Structured output and parsing.** A pin declaring structured output receives a strict `response_format` schema. Every response is parsed leniently with `coerce_json` salvaged from MatrAIx, validated, repaired once with a stricter prompt, and otherwise left as an invalid-output failure.

**Sampled completion.** Projection asks, per persona and attribute, for a probability distribution over the attribute's vocabulary. The engine validates coverage and normalisation, applies the recorded `completion_temperature`, and samples with the population's seeded stream. `completion_temperature` joins `PopulationParameters`. A population records the distribution each completed field was drawn from, so projection's calibration is measurable after the fact.

**Holdout evaluation.** A command selects Stack Overflow rows carrying measured attitudes, hides a declared attitude set, projects it from the conditioning set through the production path, and reports per-attribute marginal distance, calibration of the sampled distributions, and the share of demographic dependence recovered, beside a baseline that samples each attitude from its demographic-conditional marginal in the non-held-out rows. Results are written as a report with the pins, served models and seeds that produced them.

**Telemetry.** Spans per batch and per call, retries and fallbacks as span events, attributes under `gen_ai.*` defined in one module, world, tick and persona identifiers as attributes, content capture off unless enabled. The core depends on `opentelemetry-api`; the SDK and OTLP exporter are the optional `otel` extra.

**Configuration.** Endpoint URL, API key, concurrency ceiling, rate limits, timeouts and retry counts are execution configuration, read from the environment or a run's execution settings and never hashed. Pins and their specifications, prices, temperatures and templates live on `RunConfig` and `PopulationParameters` and are hashed.

**Contracts amended.** Module 1: the pin specification on `ModelPins`; `served_model_id` and `cost_source` on `CostRecorded`, with cost absent when unknown; a `CallFailure` outcome; `completion_temperature` on `PopulationParameters`; the recorded completion distribution on a population. Module 3: projection requests distributions through `complete`, samples under its seed, and audience interpretation moves to the batch port. `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities are re-pinned.

## Testing Decisions

Two layers. A scripted `httpx.MockTransport` drives the real client, queue, limiter, retry, fallback, circuit breaker, cache and served-model verification through sequences of 429s, timeouts, 5xx responses, served-model changes, malformed JSON, missing usage and reported costs — so the policies are tested as they run, never through a stand-in. `FakeChat` grows the batch `complete` shape with injectable failures for the modules that call inference, and stays deterministic across processes for the same prompt hash.

The suite keeps refusing sockets. Nothing in it reaches a real endpoint; the holdout evaluation's real-endpoint mode is exercised by a user, and its fake mode by CI.

The tests carrying the most weight are the ones this module exists for: outcomes return in request order when responses arrive reversed; one failed call leaves every other outcome in its batch recorded; a gateway answering from an undeclared model produces a pin failure, not a completion; two replicate seeds never share a cached sample while a re-run of one seed hits the cache; an unknown cost is recorded as unknown and refused by the budget; a distribution missing a vocabulary value leaves the field uncompleted; the same seed and the same distributions sample the same attitudes, while a different seed samples different ones; `complete` works from inside a running event loop; no span carries prompt content unless enabled; and an invalid key fails a batch of thousands after a handful of calls.

## Out of Scope

The cost-and-time forecast: inference supplies token estimates and measured throughput, and `runner`, which owns the budget, computes the forecast. Streaming. The Anthropic protocol, which ADR 0021 leaves for a need translation cannot meet. The `safety` role's moderation behaviour, which belongs to its caller. Any agent turn, tool calling or prompt assembly for personas, which belongs to `agent`. A second corpus with measured consumption joints. Choosing a tier-A model: the pins are configuration, and the distribution-fidelity benchmark between serving options is a study the holdout evaluation makes possible, not a decision this module makes.

## Further Notes

`FINAL_ARCH.md` §5.4 and `SALVAGE.md` are reconciled with ADR 0021–0025 ahead of this PRD. The quickstart must keep running offline on `FakeChat`; a real-endpoint example is documented against LiteLLM, and the example study's `att_ai` makes it the natural first holdout target. OASIS was reviewed as a salvage source for model access and contributes only its concurrency pattern; its CAMEL-based agents conflict with pinning, replay and trace completeness.
