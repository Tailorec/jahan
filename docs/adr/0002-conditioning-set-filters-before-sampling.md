# Exclude unconditionable personas at the index, not after sampling

The persona dataset is sparse by design — `synthetic`-sourced rows are complete while `gss`-sourced rows average around twelve populated attributes out of 1,290 — and the elicitation method depends on demographic conditioning, which the completion policy forbids synthesizing. Each category's ontology therefore declares a **conditioning set**, and the postings index requires those attributes to be populated before a row can enter the candidate pool.

The filter runs before sampling rather than as a post-hoc rejection because dropping sparse rows *after* sampling systematically over-selects the only rows guaranteed to be complete — the synthetic ones — producing a population that becomes more synthetic the stricter the grounding requirement gets, which inverts the engine's central claim while appearing to enforce it.

## Consequences

The conditioning filter changes which sources are reachable, so the gate report states the population's source mix against the pool's natural mix; a skew is a visible output rather than a hidden one. `Persona` cannot be constructed without a non-empty conditioning map, so the conditioning invariant is structural and `agent` needs no runtime check for it.

## Amendment (M3.5, ADR 0020) — the coverage consequence

Reading the real shards made the failure mode concrete: the reason a conditioning set is unsatisfiable is almost always *absent coverage*, not *absent matches*, and the two look identical as a zero until a denominator is stated. A `gss` row carries `exercise_frequency` on none of its rows and a `stackoverflow` row on barely any — not because no developer exercises, but because no one asked them that question. A post-hoc rejection would have surfaced this only at the end of authoring as a bare count of zero. So the pre-flight gained a first stage, `preview`, that answers a conditioning set's *coverage* from the index before any draw — matched, carrying and existing per source, each tier named, each denominator kept — and the ontology's conditioning set became checkable against a source at authoring time rather than only at build time. This ADR's rule is unchanged: eligibility is still enforced before sampling. What changed is that "can this study be conditioned at all" is now answerable while it is still cheap to edit the ontology, which is the whole reason the exclusion lives at the index.
