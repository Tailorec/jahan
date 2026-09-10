# Exclude unconditionable personas at the index, not after sampling

The persona dataset is sparse by design — `synthetic`-sourced rows are complete while `gss`-sourced rows average around twelve populated attributes out of 1,290 — and the elicitation method depends on demographic conditioning, which the completion policy forbids synthesizing. Each category's ontology therefore declares a **conditioning set**, and the postings index requires those attributes to be populated before a row can enter the candidate pool.

The filter runs before sampling rather than as a post-hoc rejection because dropping sparse rows *after* sampling systematically over-selects the only rows guaranteed to be complete — the synthetic ones — producing a population that becomes more synthetic the stricter the grounding requirement gets, which inverts the engine's central claim while appearing to enforce it.

## Consequences

The conditioning filter changes which sources are reachable, so the gate report states the population's source mix against the pool's natural mix; a skew is a visible output rather than a hidden one. `Persona` cannot be constructed without a non-empty conditioning map, so the conditioning invariant is structural and `agent` needs no runtime check for it.
