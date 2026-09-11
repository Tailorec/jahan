# World identity derives from the whole scenario, not the variant

Amends ADR 0001. A world's identity is now `h(canonical_hash(scenario), replicate_seed, population_hash)` rather than `h(variant_id, replicate_seed, population_hash)`. Price, audience weights and interventions all live on the scenario, not the variant, so keying identity on the variant collapsed distinct cells: a price sweep over one concept at two prices produced two worlds for four cells, and resume would have treated the second price point as already computed.

The world *seed* keeps ADR 0001's derivation, `h(replicate_seed, variant_id)`. Worlds of one variant therefore share their random draws across prices and conditions, so comparing two price points isolates the price effect instead of mixing it with sampling noise.

## Consequences

A run or grid refuses repeated replicate seeds, repeated scenarios, one variant identifier naming two different concept cards, and scenarios with differing tick units — each of which would otherwise produce colliding or incomparable worlds. Changing the canonical form of a scenario changes every world identity; as with ADR 0001, treat the derivation as frozen once traces exist.
