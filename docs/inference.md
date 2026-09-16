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
| `SIMCORE_INFERENCE_REQUESTS_PER_MINUTE` / `SIMCORE_INFERENCE_TOKENS_PER_MINUTE` | engine-side rate ceilings. A single call estimated above the token limit fails at once as `exceeds_rate_limit`, so set it above your largest request | unset (unlimited) |
| `SIMCORE_INFERENCE_MAX_RETRIES` | retries after the first attempt | `3` |
| `SIMCORE_INFERENCE_BACKOFF_BASE_S` / `SIMCORE_INFERENCE_BACKOFF_CAP_S` | retry backoff | `0.5` / `20` |
| `SIMCORE_INFERENCE_CIRCUIT_THRESHOLD` | identical refusals (4xx) that open the circuit; server errors are retried and never open it | `5` |
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

`litellm_config.yaml`:

```yaml
model_list:
  - model_name: tier-a                         # the name the engine sends — use it as the pin's model_id
    litellm_params:
      model: openrouter/meta-llama/llama-3.1-8b-instruct   # substitute the provider model you run
      api_key: os.environ/OPENROUTER_API_KEY
    rpm: 6000                                  # requests per minute for this deployment
    tpm: 2000000                               # tokens per minute for this deployment

litellm_settings:
  num_retries: 0         # the engine retries; a gateway retry hides an attempt from the trace
  request_timeout: 120   # above the engine's per-attempt timeout, so the engine gives up first
  cache: false           # off by default; keep it off — a gateway cache cannot honour the sample key
  fallbacks: []          # substitutions live on the pin, where the study records them
  # drop_params stays at its default (false). Set true, LiteLLM silently removes parameters a provider does
  # not support — `seed`, `response_format` — while the engine records them as sent. Left false, an
  # unsupported parameter is an error, and the pin's capability declaration can be corrected.

router_settings:
  optional_pre_call_checks:
    - enforce_model_rate_limits   # without this, rpm and tpm only steer routing and limit nothing

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Run it with `litellm --config litellm_config.yaml`, then point the engine at
`SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1`. The pin's `model_id` is `tier-a`, and `serves`
must accept whatever LiteLLM reports back in `model`: run one call, read the served model the completion
recorded, and add it to the pin's accepted identifiers — or fix the gateway. A run fixes the served
identifier on its first answer, so a gateway that later answers from another accepted alias produces a
Pin Failure rather than a silent change of model.

**Several engine processes, one shared ceiling.** By default LiteLLM uses a deployment's `rpm` and `tpm`
only to choose between deployments; they become limits only with `enforce_model_rate_limits` as above.
With it, N concurrent studies against one proxy cannot exceed those limits together. Several *proxy*
instances need Redis (`redis_host`, `redis_port`, `redis_password` under `router_settings`) to share
that state. Set each engine process's `SIMCORE_INFERENCE_REQUESTS_PER_MINUTE` to the gateway budget
divided by the number of processes, so the engine paces itself before the gateway has to answer 429, and
leave the engine's adaptive ceiling on to absorb the bursts it still refuses.

### vLLM (self-hosted, OpenAI-compatible)

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --served-model-name tier-a --max-num-seqs 32 --port 8000
```

Point at `http://127.0.0.1:8000/v1`. vLLM has no retries, fallbacks or caching to turn off; its admission
control is the concurrency ceiling, so set `SIMCORE_INFERENCE_CONCURRENCY` to roughly `--max-num-seqs`
and let excess batches queue. Structured outputs are supported by default on its OpenAI-compatible
server, so `structured_output: true` is right without any extra flag (the older
`--guided-decoding-backend` was removed in v0.12.0; the backend is now chosen with
`--structured-outputs-config.backend`, default `auto`). vLLM accepts a per-request `seed`, so
`honours_seed: true` is appropriate. Check the served model name lands in the pin's `serves`.

### Ollama (local)

```bash
ollama pull llama3.1:8b
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Point at `http://127.0.0.1:11434/v1`. Ollama's OpenAI-compatible chat endpoint lists `seed` among its
supported fields, but supports JSON mode rather than JSON-schema structured output, so pin
`structured_output: false`. Pin `honours_seed: true` only after confirming on the version you run that a
repeated seeded call returns the same answer; otherwise leave it false and let the engine's completion
temperature supply the variance. Read the `model` your version returns on the first call and add it to
the pin's `serves`, or the served-model check fails honestly as a Pin Failure.

## Embeddings

Embeddings ride the same base URL and limiter; the embedding pin never falls back, because anchors and
responses scored in different embedding spaces are not comparable (ADR 0012). vLLM serves
`/v1/embeddings` for an embedding model, detecting the pooling runner automatically (`--runner pooling`
forces it); Ollama's OpenAI-compatible surface supports `/v1/embeddings`; on LiteLLM give the `embed`
model its own `model_name` entry with its own `rpm`/`tpm`.
`SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE` caps texts per request.

### Titan Text Embeddings v2 through LiteLLM (the elicitation route)

Neither of Bedrock's OpenAI-compatible endpoints serves embeddings, and OpenAI's embedding models
are not offered on AWS — so elicitation embeds through a local LiteLLM proxy that also serves the
chat models, one base URL for both (ADR 0028). The pinned model is Amazon Titan Text Embeddings v2:

```yaml
model_list:
  - model_name: amazon.titan-embed-text-v2:0   # the provider's own id: the pin's model_id, and what a check records
    litellm_params:
      model: bedrock/amazon.titan-embed-text-v2:0
      aws_region_name: us-east-1
    rpm: 6000
    tpm: 2000000
```

Point the engine at `SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1` as usual, and pin
`amazon.titan-embed-text-v2:0` with `serves` accepting whatever LiteLLM reports back in `model` (read it
from the first call's cost record, as with chat). **Name the embedding model by the provider's own id, never
by a short alias.** An anchor check is evidence about one model, and its record names the model it judged:
Titan's first records named it `embed`, which says nothing about what passed or failed, and repointing that
alias would let another model inherit the result. The anchor check and pinning refuse a model id with no
provider qualifier (no `.` or `/`). Titan returns 1024-dimensional vectors;
the run fixes its embedding space on the first batch and refuses a later dimension change. The
mapping validation (`python -m simcore.elicitation`) measures whether SSR survives this
substitution; Cohere Embed v4 is the next candidate if it does not.

## Telemetry

Install the extra: `pip install "simcore[otel]"` (the core depends on `opentelemetry-api` alone and
costs nothing until an SDK is configured — ADR 0022). Point the SDK's OTLP exporter at your collector
(`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_EXPORTER=otlp`); spans for batches and calls carry GenAI
convention attributes, retries and fallbacks as events, and propagate trace context so the gateway's
own spans nest under the engine's. Prompt and response content — and an endpoint's error body, which can quote the request — is never
attached unless `SIMCORE_OTEL_CAPTURE_CONTENT=1`; a recorded failure keeps only the status and the
error's identifier-like type and code, capture or not. Telemetry is not the scientific record: the trace is, and nothing
analytical reads a span.

## The holdout against a real endpoint

One command, from the repository root:

```bash
SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1 SIMCORE_INFERENCE_API_KEY=... \
  python -m simcore.holdout --endpoint --model tier-a --information demographics --hidden att_ai --pool 600 --seed 4021 --out holdout.json
```

It hides Stack Overflow's measured attitudes, projects them through the production path on the pinned
model, and writes a report naming the pins, the models that actually served the calls, the seeds, the
completion temperature and the row counts behind every number (ADR 0019). `--information` picks the arm: `demographics` (the default, and ADR 0019's question) gives projection only the
conditioning set; `all` gives it every other declared attribute. Either way the baseline sees exactly what
projection saw, so a correlated attitude can never make a model look better than the comparison it is held to.
Read log loss and Brier score
first, each beside the demographic-conditional baseline's: they are proper scoring rules, so neither
uniform guessing nor ignoring demographics can score well. Marginal distance cannot see demographics and
calibration rewards uniform guessing, so neither is a verdict on its own; recovered dependence is
corrected for the information sparse demographic cells show by chance. The same command without
`--endpoint` runs the fake in CI.
