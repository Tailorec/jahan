# A budget rung belongs to the run, and a world replays the rung it ran under

A sweep is one run over many worlds sharing one budget, so the degrade ladder is the run's, not each world's. When
spend crosses a rung, every live world runs at that rung from its next tick: tier-B work freezes together,
activation subsamples together, and the pause stops them all. Each world records the rung as a `degraded` event at
the tick it took effect, and any cell that ran degraded marks the comparison it takes part in.

The alternative — a rung per world — would let one cell of a sweep freeze reflections while another kept them,
and the two would then be compared as if only the scenario differed. That is the failure the architecture's budget
section is built to avoid: a degraded world must never be compared silently with one that ran in full.

Worlds may run in parallel, so *when* a rung fires depends on how the pool interleaved them. This is inherent to a
shared budget: the only way to make the timing reproducible is to run worlds one at a time, which throws away the
throughput a sweep exists for. What is made reproducible instead is the content of each world: the rung is recorded
and, on resume or replay, **applied from the record rather than recomputed from the ledger**. A world therefore
reproduces exactly, even though a fresh run of the same sweep may degrade at a different tick.

## Considered options

A rung per world, applied from that world's own spend, was rejected for the incomparability above. Recomputing the
rung on resume from the ledger was rejected because the ledger at resume time is not the ledger the world ran
under, so a replay would diverge from the record it is meant to reproduce. Running worlds sequentially to make rung
timing deterministic was rejected: sweeps exist for throughput, and a sweep of forty cells run one at a time is a
different product.

## Consequences

Two fresh runs of the same sweep under the same budget may degrade at different ticks, and the results say so —
each world carries the rungs it ran under, and a comparison across cells that ran at different rungs is marked
rather than quietly drawn. A single world, replayed, is bit-identical. The budget has exactly one enforcement
point, which is the property that made it testable at all.
