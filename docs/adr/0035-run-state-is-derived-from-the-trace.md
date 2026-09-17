# Run state is derived from the trace, and a checkpoint is only ever a cache

A resumed run needs three things: what each persona carries, where each world stands, and how much has been spent.
All three are already in the trace, and each is derived from it rather than read back from a second record.

- **Persona state** is rebuilt from memory events, belief snapshots and turns — the round-trip `agent` already
  implements and tests (ADR 0030).
- **A world** resumes by `reset` and replaying its recorded turns (ADR 0011).
- **The cost ledger** is the sum of the partition's `cost` events. The runner keeps a running total while it works
  and, on resume, rebuilds it by summing rather than trusting a number it wrote down.

A checkpoint may exist to make any of this faster, and it is never authoritative: it must agree with the trace or
be discarded. The reason is uniform across all three — a checkpoint is a second record of a fact the trace already
holds, and second records drift. The version that drifts silently is worse than the slow one, because a study's
numbers would then depend on which record was read.

This also makes the round-trip property load-bearing instead of decorative: if state rebuilt from a trace did not
equal the state a run carried, resume would produce a different study, so the property is tested where the state is
produced.

## Considered options

Checkpointing persona state authoritatively was rejected for drift, and because it would make the trace's
completeness untested — nothing would read the memory events back. Checkpointing the cost total was rejected for
the same reason and one more: a ledger that disagrees with the billed events is exactly the number nobody can
audit. Reconstructing nothing and simply starting a fresh run after an interruption was rejected as the most
expensive option available, since the discarded work is model calls that were already paid for.

## Consequences

A resume costs a trace scan per world — seconds at 500k events, once per interruption. Every number a resumed run
carries is derivable from the record, so a reader can recompute it. Checkpoints become an optimisation the engine
may add without changing any contract, and must validate against the trace when it does.
