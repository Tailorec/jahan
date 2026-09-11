# Derive the world seed instead of authoring it on the scenario

> Amended by ADR 0005: world *identity* now derives from the scenario's content hash. The world *seed* derivation below stands.

A scenario describes conditions, not a particular random draw, so it carries no seed. Replicate seeds live on the run, and each world's seed is derived as `h(replicate_seed, variant_id)` — because the earlier shape, with `world_seed` on the scenario *and* a list of seeds on the run, silently produced identical worlds for every replicate and made the variance estimate that anomaly detection thresholds on come out as zero.

The population has its own single seed; sampling and graph generation draw from independent streams spawned from it (`SeedSequence(seed).spawn(2)`) rather than from two separately authored seeds, which would invite correlated draws if anyone set them equal.

## Considered options

Authoring one scenario per replicate (fully explicit, no derivation) was rejected as unusably verbose in sweep files. An optional `world_seed` override on the scenario was rejected because two code paths for `world_id` breaks the idempotent-resume property that makes "have I already run this cell?" answerable without a registry query.

## Consequences

`world_id` is a pure function of `(variant_id, replicate_seed, population_hash)`, so changing the derivation invalidates the identity of every stored run. Treat it as frozen once traces exist.
