# The engine speaks one OpenAI-compatible endpoint and imports no provider

ConsumerSim is open source, and the people running it will use Bedrock, Anthropic, OpenAI, OpenRouter, a vLLM cluster or a laptop running Ollama. Supporting each by importing its SDK makes the engine own every provider's authentication, request format and failure modes, and makes each new provider a change to the engine. Instead the engine speaks exactly one wire protocol — OpenAI Chat Completions and Embeddings over HTTP — to a base URL the user configures, and imports no provider SDK and no gateway library. Whatever translates that protocol to a provider is the user's to run.

The documented default is a self-hosted LiteLLM proxy, which translates the protocol to Bedrock with the user's own credentials, to Anthropic and to most hosted providers, and emits OpenTelemetry of its own. vLLM and Ollama serve the protocol directly and can be pointed at without a gateway; configuring them is documented, not built.

## Considered options

Importing provider SDKs, as MatrAIx's `model_client.py` does, was rejected: it is the maintenance burden this decision exists to avoid, and it would make the engine's dependency set a function of its users' providers. Speaking both the OpenAI and the Anthropic protocol was rejected as doubling the adapter and its tests for no capability the gateways do not already translate; the Anthropic protocol can be added if a need appears that translation cannot meet. Depending on OpenRouter was rejected as the default because it is hosted, cannot reach a user's own Bedrock account, and by default serves one model name from several hosts.

## Consequences

A gateway may substitute what serves a request — OpenRouter can route one model name to hosts running different quantizations, and LiteLLM can fall back across deployments — which would silently break ADR 0009's pins and ADR 0012's recorded routes. The engine therefore sends the pinning a gateway accepts, requires gateway-side fallbacks to be off, records the model the response says actually served each call beside the one it asked for, and treats a mismatch as a failure of the pin rather than a detail. Pinning costs availability, and that trade is made visibly.

`FINAL_ARCH.md` §5.4's salvage of MatrAIx's per-provider branches is withdrawn. What survives is provider-independent: `coerce_json`, the pin precedence, and token accounting.
