# Fallback models are pinned, and every model call records the route that served it

The inference module may fall back to another model when a provider keeps failing, but only to a fallback pinned in the run configuration for that role, and every cost event records whether the primary model, the pinned fallback, or the cache served it. The embedding role can never have a fallback, because anchors and responses scored with different embedding models are not comparable.

ADR 0009 made a partition refuse any billed model other than the pinned one, which would have failed every trace containing a fallback; allowing unpinned fallbacks instead would let a world's turns switch model mid-run, confounding it and making replay call a model the configuration never named.

## Considered options

Forbidding fallbacks entirely is the most reproducible choice, but turns a provider outage into a failed run rather than a recorded, bounded substitution.
