# One trace view over two backends, and one implementation of every derived shape

A trace lives in SQLite while its run is live and in Parquet once the run closes. `analysis` must not know which:
it asks for a run's view and reads the same five shapes either way — `events(filter)`, `beliefs(persona_id)`,
`edges()`, `verbatims(grouping)`, `resolve(trace_ids)`. The registry's status decides which backend answers.

A view opens on a live or paused run, not only a finished one. A paused run keeps its completed worlds and partial
results are valid results; if views needed finalization first, those kept worlds would be unreadable by the module
whose job is to interpret them, no run could be watched while it ran, and the only code path tests exercised would
be the one a long study never uses. Because a tick is recorded whole (ADR 0033), a live view is always consistent —
it is merely behind.

The binding property: **the same view answers identically before and after finalization.** Take every read shape on
a live world, finalize it, take them again, compare. A digest computed at one moment and at the next must not
differ because the storage changed underneath it.

`beliefs.parquet` and `edges.parquet` are derived shapes, not separate records: beliefs come from belief snapshots
and turns, edges from word-of-mouth deliveries and follows. Their derivation lives in the view and nowhere else,
and the Parquet files hold exactly what the view would have computed, written by that same code. A second
implementation on the finalized side is how the two backends would come to disagree, and re-creates the leak
`TraceView` exists to prevent: the previous design passed trace views as an undefined wide interface, and
derivation logic ended up in two consumers.

## Considered options

Views only on finalized runs was rejected: it makes a paused run's kept worlds unreadable, blocks progress
reporting, and leaves the live path untested. Handing `analysis` a Parquet path or a DataFrame was rejected because
an open handle is not a closed set — anything the caller can reach past becomes an interface nobody owns.
Materialising the derived shapes with their own writer was rejected for the disagreement it invites.

## Consequences

`trace` carries two read implementations behind one protocol and a test that holds them to the same answers. The
derived shapes cost computation on the live path, which is acceptable because a live read is for watching and for
partial results, not for the hot loop. `analysis` is written once, against a protocol, and never against storage.
