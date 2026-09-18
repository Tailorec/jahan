# A digest is one world's, and a scenario carries the spread between its worlds

A scenario runs once per replicate seed, and the spread between those worlds is the study's variance estimate —
`CONTEXT.md` says so, and it is the only reason a scenario is run more than once. So a digest describes one
world and names the scenario it belongs to, and a separate shape aggregates a scenario's digests, carrying the
per-seed values beside their spread rather than a mean alone.

The distinction is not presentational. The architecture sets the herding threshold at `|Δ mean| > 2σ`, and σ
must be the variation between replicates. A digest that pooled seeds internally would leave anomaly detection
computing σ from tick-to-tick variation inside one world instead — a different quantity, silently substituted,
which would make every anomaly threshold wrong in a way nobody could see from the output.

It also keeps the signature honest: one view, one world, one digest. A view is already scoped to a world, so a
digest over several would have to decide for itself which worlds belonged together.

## Considered options

Digesting a whole scenario, pooling its seeds inside, was rejected for the σ substitution above and because it
discards the plainest thing a reader of a stochastic simulation should be told: that two seeds disagreed.
Reporting only the mean across seeds was rejected for the same reason. Leaving aggregation to `report` was
rejected because the spread would then be computed by a module whose whole purpose is that it introduces no
claims, and a variance estimate is a claim.

## Consequences

A heatmap cell is an aggregate, not a digest, and it names the seeds it pooled. A cell whose worlds ran at
different degradation rungs is marked rather than quietly averaged (ADR 0037). The common case — one scenario,
one seed — carries a spread of zero and says so, which is honest about how little one replicate establishes.
