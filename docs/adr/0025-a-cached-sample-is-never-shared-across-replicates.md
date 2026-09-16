# A cached sample is never shared across replicates

The inference cache serves a repeated request without calling the model again, and a re-run of a study is expected to hit it. For a call sampled at temperature above zero, a cached response is one fixed sample. If replicate seeds shared that cache, every replicate would receive identical answers, the spread between seeds would collapse to zero, and the anomaly thresholds built on that spread would flag nothing or everything. A sampled call's cache key therefore includes a **sample key** derived from the replicate seed, the persona and the tick; a call at temperature zero is keyed without one and may be shared.

## Considered options

Caching only temperature-zero calls was rejected as discarding the re-run savings the cache exists for, since most persona turns are sampled. Keying on the whole run was rejected because a re-run of the same seed would then never hit. Disabling the cache across replicates by configuration was rejected as a correctness property left to a setting.

## Consequences

Re-running the same seed reproduces its samples from the cache; a new seed draws new ones. The cache is persistent, lives in the user cache directory, and is keyed by served model, template id and hash, the exact request bytes and the sample key, so a changed model or template never serves an old answer. Replay reads the trace, never the cache (ADR 0011), so an evicted or deleted cache costs money and never changes a result.
