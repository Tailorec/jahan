# A population is built once and carried, never rebuilt

A population is an artifact, not a recipe. Replay loads the one that was built; it does not re-derive it from its seed. Determinism is promised only under a deterministic inference port — the fake, or a cache warm enough to answer every completion — because building a population calls a model to fill sparse fields, and those values land in the personas the population hash covers.

The architecture reads as though `build(brief, n, population_seed)` were a pure function, and the boundary test "same inputs, identical population hash, twice" reinforces that. It is true under `FakeInference` and false against a live provider. Since `RunConfig` pins `population_hash`, `PartitionHeader` verifies it, and every `world_id` derives from it, the difference decides what "reproduce this run from its recorded inputs" actually means: load the population that was used, or rebuild an equivalent one. Only the first is honest.

## Considered options

Forcing determinism by requiring a persistent completion cache for every real build was considered. It works while the cache lives, which makes reproducibility a property of a retention policy rather than of an artifact on disk — a much weaker promise, and one that fails silently long after the run it would have protected.

Excluding synthesized fields from the population hash would make rebuilds hash-identical, and was rejected outright: two populations whose invented attributes differ are different populations, and a hash that says otherwise is worse than no hash.

Refusing to complete sparse fields at all keeps builds pure, at the cost of the sparse-completion capability the dataset's ~656-of-1,290 average population makes necessary.

## Consequences

Whoever owns durable state — `trace` and `runner` — must be able to store a population and its embedding array and load them back; without that the engine cannot replay a study that used a live model, and this is recorded as a requirement against those modules rather than solved here. The reproducibility boundary test states its condition in its name, so nobody reads it as a general guarantee. The manifest records which model completed fields and under which template, so a population that cannot be rebuilt can still be accounted for: what was invented, by what, and when.
