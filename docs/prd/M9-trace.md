# PRD — M9 `trace`: the append-only record and the questions that can be asked of it

## Problem Statement

Five modules now produce records that nothing stores. `agent` returns turns, memories, belief snapshots, probe
results and cost records; `world` returns published stimuli, drops and interventions; `inference` bills every call.
All of it is written through a port with a fake, and when the fake is taken away there is nowhere for it to go.

The contracts are already here — `TraceEvent`, its ten payload kinds, `PartitionHeader` and `TracePartition`
validate themselves in `simcore/schemas/trace.py`, and `read_partition` exists. What is missing is everything
around them: where a partition lives while its run is alive, what happens when the run finishes, how a reader asks
it anything, and what happens when the schema moves under a trace that is already on disk.

Three risks are specific to this module.

A record that can be mutated is not an audit spine. Resume discards whatever followed the last closed tick
(ADR 0011), and if that discarding is a deletion, then the trace is a file the engine edits — and every claim that
rests on replay rests on nothing. ADR 0033 settles this by making a tick atomic, which this module must implement
rather than assume.

An open read path leaks derivation. `TraceView` is named in the architecture as a closed set of five shapes
precisely because the previous design passed "trace views" as an undefined wide interface and the same derivation
ended up in two consumers. If this module hands out a Parquet path, a DataFrame or a `**kwargs` filter, that
happens again, and `analysis` becomes the second place beliefs are computed.

A trace that cannot be read under a newer schema makes replay a lie. `SCHEMA_VERSION` is 1.0.0 and unreleased
today, so migrations cost nothing to build and everything to retrofit once real runs exist.

## Solution

One module owning the record and the questions, with two storage backends behind one protocol.

**Write** — `write(events)` is one transaction per call and refuses a `(world_id, seq)` it already holds, so a
retry after an ambiguous crash is safe. The runner hands over a whole tick at a time, its events plus the
`tick_closed` that marks it (ADR 0033); nothing else may write.

**Read** — `view(run_id)` returns a `TraceView`: exactly `events(filter)`, `beliefs(persona_id)`, `edges()`,
`verbatims(grouping)` and `resolve(trace_ids)`, each returning frozen models from `schemas`. A live or paused run
is answered from SQLite, a finished one from Parquet, and the caller is never told which. The derived shapes —
beliefs and edges — are computed in the view, and the Parquet files hold exactly what the view would compute,
written by that code (ADR 0034).

**Finalize** — `finalize(world_id)` turns a finished world's live record into its lasting one, idempotently,
writing the contract version into the Parquet metadata and the registry. What can be read does not change; where
it is read from does.

**Registry** — one entry per run pinning everything replay needs: config, brief, population and graph hashes,
seeds, pins, engine version, recorded cost, discarded ticks and status.

**Migrate** — a partition from a newer contract is refused; an older one is migrated forward through every
registered migration and then validated strictly.

## User Stories

**Writing**

1. As a runner, I want a tick's events written in one transaction, so a crash leaves whole ticks and nothing else.
2. As a runner, I want a re-sent write refused rather than duplicated, so retrying after an ambiguous crash is safe.
3. As a maintainer, I want the write path to take payload models rather than mappings, so the hot path stays
   `model_construct` while CI validates the same records strictly.
4. As a researcher, I want 500k events to round-trip with identical ordering by persona, tick and sequence, so the
   record I read is the record that was written.
5. As a methodologist, I want no field anywhere that can hold a whole prompt, so context is never stored and always
   re-derivable from the pins.

**Reading**

6. As an analyst, I want exactly five read shapes and no way past them, so derivation cannot leak into the modules
   that read.
7. As an analyst, I want each shape to return frozen models, never rows or frames, so a reader cannot reach into
   storage.
8. As an analyst, I want a filter that is a typed object, so the closed set stays closed.
9. As a researcher, I want to read a run that is still going or paused, so partial results are usable.
10. As a maintainer, I want the same view to answer identically before and after finalization, so a number does not
    change because storage did.
11. As an analyst, I want `resolve(trace_ids)` to return exactly the events referenced or fail, so a finding can
    cite its evidence.
12. As an analyst, I want beliefs and edges derived in one place, so the live and finalized paths cannot disagree.

**Lifecycle and registry**

13. As a runner, I want finalization to be idempotent, so calling it twice after a retry is harmless.
14. As a researcher, I want a finalized world to be read-only, so a finished study cannot be edited.
15. As a researcher, I want one registry entry per run pinning every hash, seed, pin and the engine version, so a
    replay can be set up from the registry alone.
16. As an operator, I want the registry to carry recorded cost and discarded ticks, so a quoted total can say what
    is known and what is not.

**Versions**

17. As a maintainer, I want a partition written under one contract to load under the next, so a stored run survives
    a schema change.
18. As a maintainer, I want a partition from a newer contract refused rather than half-read, so a downgrade fails
    loudly.
19. As a maintainer, I want the contract version written once per partition rather than per event, so 500k rows
    carry no redundancy.

## Implementation Decisions

**Layout** — this module owns it: `registry.db` for the run registry, and per world `events.parquet` sorted by
`(persona_id, tick)`, `beliefs.parquet`, `edges.parquet`, plus the live SQLite record. The world's own `state.db`
sits in the same directory for convenience and is **not** part of the trace: the runner tells the world where to
put it and nothing here reads it, because no world state crosses that boundary (ADR 0011).

**Two backends, one protocol** — `TraceView` is a `Protocol` in `ports`; the SQLite and Parquet implementations
live here, and a test holds them to identical answers.

**Parquet fan-out** — the payload union is what allows typed columns instead of a JSON blob; the writer fans out
per kind and the reader dispatches on the partition's version.

**Migrations** — a registry of `ContractMigration`s, applied in order for any partition older than the current
contract, with a synthetic next version in the tests so the path is exercised before it is needed.

**Sizing** — roughly 500k events per world at study scale, 100–200 MB of Parquet; batched writes, and no index that
is not read.

**Salvage** — OASIS `database.py` and `channel.py`, which are already trace-shaped.

## Testing Decisions

Boundary tests through `write`, `view` and `finalize`; the suite reaches no network.

- 500k events round-trip with identical ordering by `(persona_id, tick, seq)`.
- Every read shape answers identically before and after finalization, on the same world.
- A duplicate `(world_id, seq)` is refused; a retried identical write is a no-op.
- A partition written under 1.0 loads under a synthetic 1.1; one written under a newer contract is refused.
- An event whose payload kind disagrees with its declared type is refused.
- `resolve(trace_ids)` returns exactly the referenced events or raises.
- A registry entry pins every hash, seed and pin a replay needs, including the engine version.
- Beliefs and edges from the view match the same quantities recomputed from raw events in a fixture.
- No schema field anywhere can hold a whole prompt, asserted over the module's types.

## Out of Scope

Orchestration, budget and resume (`runner`, module 8) — this module stores what it is given and refuses what it
should. Digests, findings and anomaly detection (`analysis`, module 10). The `exports/{study_id}/` client
deliverable, which is a delivery format rather than part of the spine and belongs with `report`/`cli`; deferred
deliberately. The world's platform state, which stays internal to `world`.

## Further Notes

`TraceView` does not exist in `simcore/schemas` yet and is the one thing both this module and `runner` need, so it
lands on `master` before either branch begins — the same sequencing that worked for M6's contracts.
