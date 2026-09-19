# The web layer derives nothing

The HTTP module reads through `TraceView`'s five closed shapes and `analysis`, and serialises, filters and
pages what they return. It computes no statistic of its own. Any number the interface needs that nobody
derives yet becomes a new derived shape in `analysis`, with tests, and the command line gets it for free.

## Considered options

Serving the interface from Next.js alone — API routes shelling out to the CLI and reading run directories —
was rejected because the aggregates the mockups need (runs this month, spend against budget, per-tick
trajectories per audience, sweep health) would then be written in TypeScript. `FINAL_ARCH.md` §5.10 records
that this architecture exists because the previous design computed objection clusters in two places from the
same verbatims with no stated owner: one concept, two implementations, guaranteed to diverge. Rebuilding
that with a language boundary through the middle would make it harder to see, not easier.

## Consequences

Two processes run locally instead of one, and every panel wanting an underived number requires a small
`analysis` change before it can be drawn. That friction is the point: the interface cannot invent a
statistic. Cross-run workspace totals read registry entries rather than scanning traces, which means a
figure like "personas simulated" needs a field on the entry rather than a walk over every partition.
