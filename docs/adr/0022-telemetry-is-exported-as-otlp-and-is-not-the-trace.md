# Telemetry is exported as OpenTelemetry, carries no persona content by default, and is not the trace

Running a study means knowing why it was slow, what it cost, and which calls failed. The engine emits OpenTelemetry spans for its model calls and stages, depends only on the OpenTelemetry API — which does nothing until configured — and exports over OTLP to whatever collector a user points it at. It integrates no observability product: Phoenix, Langfuse, Jaeger and Grafana are all reached the same way, by configuration.

Spans use the OpenTelemetry GenAI conventions (`gen_ai.*`) because they are vendor-neutral. Those conventions are still in Development status with no release to pin, so every attribute name lives in one place and their churn costs one edit.

## Considered options

Integrating Arize Phoenix was rejected: it would bind an MIT project to one product, and Phoenix is licensed under the Elastic License 2.0, which is source-available rather than open source. Emitting OpenInference, Phoenix's own conventions, was rejected for the same binding. Recording model calls only in the engine's own trace was rejected because the trace is shaped for replay and findings, not for latency, error rates and cost dashboards.

## Consequences

Telemetry is never the scientific record. ADR 0006's trace is self-verifying and is what replay and analysis read; spans are sampled, batched and dropped by design, and nothing analytical may read them. The two are joined by carrying world, turn and persona identifiers as span attributes, and trace context is propagated to the gateway so its own spans nest beneath the engine's.

Prompts carry persona values drawn from a research-only corpus, and exporting them to a hosted service would redistribute corpus content that ADR 0016 keeps out of reach. Spans therefore carry metadata only by default — requested and served model, tokens, latency, cost, template id and hash, route. Capturing prompt and response content is an explicit opt-in, documented for self-hosted collectors. The same warning applies to a gateway's own logging, which captures content unless configured not to, and the documentation says so.
