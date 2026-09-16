# Running the engine against one OpenAI-compatible endpoint

The engine speaks exactly two HTTP endpoints — `POST /v1/chat/completions` and `POST /v1/embeddings` —
over `httpx`, to one base URL you configure (ADR 0021). It imports no provider SDK and no gateway
library: whichever model answers is decided by your gateway's configuration, not by engine code. Three
documented ways to provide that endpoint, then the rules that make them honest.

Configuration splits in two, and the split is load-bearing:

- **Execution configuration** — the base URL, the API key, concurrency, rate limits, timeouts, retry
  counts, the cache location, telemetry. Read from the environment; never hashed; changing it changes
  how a run executes, not what it measured.
- **Study configuration** — the model pins and the identifiers each accepts, declared prices,
  temperatures, templates. Recorded on `RunConfig` and `PopulationParameters` and hashed into every
  identity.

## Engine-side environment

| Variable | Meaning | Default |
|---|---|---|
| `SIMCORE_INFERENCE_BASE_URL` (or `OPENAI_BASE_URL`) | the one endpoint: `http://host:port/v1` | `http://127.0.0.1:4000/v1` |
| `SIMCORE_INFERENCE_API_KEY` (or `OPENAI_API_KEY`) | bearer token, if the gateway wants one | none (no header sent) |
| `SIMCORE_INFERENCE_TIMEOUT_S` | per-attempt timeout | `90` |
| `SIMCORE_INFERENCE_CONCURRENCY` | maximum calls in flight | `32` |
| `SIMCORE_INFERENCE_QUEUE_BOUND` | how many queued requests the batch holds | `4096` |
| `SIMCORE_INFERENCE_REQUESTS_PER_MINUTE` / `SIMCORE_INFERENCE_TOKENS_PER_MINUTE` | engine-side rate ceilings | unset (unlimited) |
| `SIMCORE_INFERENCE_MAX_RETRIES` | retries after the first attempt | `3` |
| `SIMCORE_INFERENCE_BACKOFF_BASE_S` / `SIMCORE_INFERENCE_BACKOFF_CAP_S` | retry backoff | `0.5` / `20` |
| `SIMCORE_INFERENCE_CIRCUIT_THRESHOLD` | identical fatal responses that open the circuit | `5` |
| `SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE` | texts per embedding request | `64` |
| `SIMCORE_CACHE_DIR` | where the replicate-safe completion cache lives | `$XDG_CACHE_HOME` or `~/.cache/simcore/inference` |
| `SIMCORE_OTEL_CAPTURE_CONTENT` | attach prompt/response text to spans | off — see telemetry |

Model **pins are not environment variables**: they are study inputs, recorded and hashed. The
environment selects the endpoint that serves them.

## The engine owns retries, fallbacks and caching — turn the gateway's off

Three policies change what the trace must say, and only the engine writes the trace:

- **Retries.** A gateway retry happens *after* the engine has already seen a failure it must record as
  the outcome of one attempt. Double-layered retries turn the attempt count into fiction.
- **Fallbacks.** A model substitution the engine does not name is a Pin Failure — a result from an
  unnamed model. Fallbacks belong on the pin (`fallbacks` in `ModelPins`), never in gateway config.
- **Caching.** A cache that answers a temperature-zero call is invisible and harmless; a cache that
  answers a *sampled* call hands two replicate seeds the same draw and erases the spread their
  comparison exists to measure (ADR 0025). The engine's own cache keys sampled calls by replicate seed,
  persona and tick; a gateway cache cannot.

### LiteLLM proxy (the documented default)

The engine's own limiters are per-process. A shared ceiling across several studies is the gateway's
job, so set the limits once on a single LiteLLM proxy and let every engine process respect it.
`litellm_config.yaml`:

```yaml
model_list:
  - model_name: persona-8b #            the name the engine sends
    litellm_params:
      model: openrouter/camel-ai/persona-mistral-8b-it-v1 # any provider LiteLLM speaks
      api_key: os.environ/OPENROUTER_API_KEY
      rpm: 6000                          # requests per minute — the shared ceiling
      tpm: 2000000                       # tokens per minute — the shared ceiling

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY

litellm_settings:
  num_retries: 0        # the engine retries; a gateway retry hides an attempt from the trace
  request_timeout: 120  # above the engine's per-attempt timeout so the engine gives up first
  cache_responses: false # a gateway cache cannot honour the sample key; the engine's cache can
  fallbacks: []         # substitutions live on the pin, where the study records them
  drop_params: true
```

Run it with `litellm --config litellm_config.yaml`, then point the engine at
`SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1`. The pin's `model_id` is `persona-8b`, and
`serves` accepts whatever LiteLLM reports back in `model` (check the served model a run recorded — the
first completion carries it — and add it to the pin's accepted identifiers or fix the gateway).

**Several engine processes, one shared ceiling.** Set `rpm`/`tpm` per deployment on the LiteLLM
deployment above (or per key, with virtual keys). Because LiteLLM counts them centrally, N concurrent
studies cannot exceed the provider quota together. Set each engine process's
`SIMCORE_INFERENCE_REQUESTS_PER_MINUTE` to the gateway budget divided by the number of processes it
runs, so the engine paces itself before the gateway ever has to answer 429 — and leave the engine's
adaptive ceiling on: it is what absorbs the bursts the gateway still refuses.

### vLLM (self-hosted, OpenAI-compatible)

```bash
vllm serve camel-ai/Persona-8B --served-model-name persona-8b --max-num-seqs 32 --port 8000
```

Point at `http://127.0.0.1:8000/v1`. vLLM has no retries, fallbacks or caching to turn off; its
admission control is the concurrency ceiling, so set `SIMCORE_INFERENCE_CONCURRENCY` to (roughly)
`--max-num-seqs` and let excess batches queue rather than pile on the server. Declare the seed
capability honestly on the pin: vLLM honours `seed`, so `honours_seed: true` is right — but only
`structured_output: true` when you also pass `--guided-decoding-backend`, and check the served model
name (`vllm/...` versus `persona-8b`) lands in the pin's `serves`.

### Ollama (local)

```bash
ollama pull llama3.1:8b
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Point at `http://127.0.0.1:11434/v1`. Ollama exposes an OpenAI-compatible surface but answers
`model` as `<name>:<tag>` — pin `serves` to include it, or a served-model check will fail honestly
as a Pin Failure. Ollama's OpenAI layer does not reliably honour `seed` across versions and offers no
strict structured output, so pin `honours_seed: false` and `structured_output: false` unless you have
verified otherwise on the version you run: the engine then samples variance itself (the completion
temperature) and repairs its own output rather than promising provider determinism it cannot check.

## Embeddings

Embeddings ride the same base URL and limiter; the embedding pin never falls back, because anchors and
responses scored in different embedding spaces are not comparable (ADR 0012). vLLM needs
`--embed` (or `--task embed`) to serve `/v1/embeddings`; Ollama's OpenAI surface supports it since
v0.1.43; on LiteLLM give the `embed` model its own `model_name` entry with its own `rpm`/`tpm`.
`SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE` caps texts per request.

## Telemetry

Install the extra: `pip install "simcore[otel]"` (the core depends on `opentelemetry-api` alone and
costs nothing until an SDK is configured — ADR 0022). Point the SDK's OTLP exporter at your collector
(`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_EXPORTER=otlp`); spans for batches and calls carry GenAI
convention attributes, retries and fallbacks as events, and propagate trace context so the gateway's
own spans nest under the engine's. Prompt and response content is never attached unless
`SIMCORE_OTEL_CAPTURE_CONTENT=1`. Telemetry is not the scientific record: the trace is, and nothing
analytical reads a span.

## The holdout against a real endpoint

One command, from the repository root:

```bash
SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1 SIMCORE_INFERENCE_API_KEY=... \
  python -m simcore.holdout --endpoint --model persona-8b --hidden att_ai --pool 600 --seed 4021 --out holdout.json
```

It hides Stack Overflow's measured attitudes, projects them through the production path on the pinned
model, and writes a report naming the pins, the models that actually served the calls, the seeds, the
completion temperature and the row counts behind every number (ADR 0019). The same command without
`--endpoint` runs the fake in CI.
