# Plan: M9 `trace` — the append-only record and the questions that can be asked of it

> Source PRD: `docs/prd/M9-trace.md`
> Binding decisions: ADR 0033 (a tick is recorded whole, or not at all), ADR 0034 (one trace view over two backends, one implementation of every derived shape), ADR 0035 (run state is derived from the trace), ADR 0036 (a resume refuses a run whose inputs or engine moved), ADR 0037 (a rung belongs to the run and is replayed), ADR 0011 (no world state crosses the boundary), ADR 0010 (within-tick independence), ADR 0006 (a turn carries the impression it saw), ADR 0009 (the header derives the world id), ADR 0001/0005 (world identity). `CONTEXT.md` (Partition, Tick Closed, Trace View, Finalization, Cost Ledger, Discarded Tick, Rung, Sweep). Where `FINAL_ARCH.md` §5.9 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Whole ticks only** — the runner hands over a tick's events with its `tick_closed` in one call; `write` is one transaction and refuses a `(world_id, seq)` it already holds. Nothing is ever deleted to make a resume possible.
- **One writer** — the runner assigns every `event_id` and `seq`. This module refuses what does not fit and invents nothing.
- **Five read shapes, closed** — `events(filter)`, `beliefs(persona_id)`, `edges()`, `verbatims(grouping)`, `resolve(trace_ids)`, each returning frozen models from `schemas`; never rows, frames or an open handle, and a typed filter rather than keyword arguments.
- **Two backends, one protocol** — SQLite while a run is live or paused, Parquet once it is finished; the registry's status decides and the caller is never told which.
- **Derived shapes have one implementation** — beliefs and edges are computed in the view, and Parquet holds exactly what the view would compute, written by that code.
- **Identical before and after** — every shape answers the same on a live world and on the same world finalized. This is the property the lifecycle lives or dies by.
- **Context is never stored whole** — only its parts and hashes. There is deliberately no field a prompt fits in.
- **Versions are handled now** — a newer contract is refused, an older one migrated forward then validated strictly; the contract version is written once per partition, never per event.
- **The world's store is not ours** — `state.db` living beside a partition is filesystem convenience; nothing here reads it (ADR 0011).
- **Test posture** — boundary tests through `write`, `view`, `finalize` and the registry, with a temporary directory per test. The suite reaches no network.

---

## Phase 1: The shared contracts

**User stories**: 6, 7, 8, 15, 16

> This phase lands on `master` before either parallel branch begins. It carries what `runner` needs as well, and no behaviour.

### What to build

The seam both modules build against. `TraceView` becomes a real protocol with a typed filter and typed results, the trace write port gets a shape a fake can satisfy, and the registry entry gains the facts a resume must check and a report must quote: the engine version, the recorded cost, and how many ticks were discarded.

### Acceptance criteria

- [x] `TraceView` is a protocol naming exactly the five read shapes, with a typed filter object and frozen return models
- [x] No read shape returns a row, a mapping, a frame or a path, asserted over the protocol's annotations
- [x] A trace write port exists that a fake can satisfy, taking payload models rather than mappings
- [x] The registry entry pins the engine version and carries recorded cost and discarded-tick count
- [x] Pinned identities are re-pinned if any hashed contract moved, with the change recorded in the commit
- [x] The existing suite passes unchanged in behaviour

---

## Phase 2: The write path

**User stories**: 1, 2, 3

### What to build

Events on disk, for a run that is still going. A tick arrives as one call and lands in one SQLite transaction or not at all; a re-sent tick is refused rather than duplicated, so a retry after an ambiguous crash is safe. The hot path takes payload models and builds events without revalidating them, while the same records are validated strictly in CI.

### Acceptance criteria

- [x] A tick's events and its `tick_closed` are written in one transaction
- [x] A transaction that fails part-way leaves nothing of that tick behind
- [x] A `(world_id, seq)` already held is refused, and an identical re-send is a no-op rather than a duplicate
- [x] The write path takes payload models; a mapping is refused
- [x] Events written under the hot path validate strictly when read back
- [x] A partition's events remain gapless and ordered by `(persona_id, tick, seq)` on read

---

## Phase 3: Reading a live run

**User stories**: 6, 7, 8, 9, 11

### What to build

The first three read shapes over SQLite, answering while a run is still going. `events(filter)` takes a typed filter; `verbatims(grouping)` returns what personas said grouped as asked; `resolve(trace_ids)` returns exactly the events a finding cites, or fails. A view opens on a live or paused run, and sees only ticks that closed.

### Acceptance criteria

- [x] `view(run_id)` opens on a live run and on a paused one, and `view(run_id, world_id)` scopes it to one world — **added in review**: a digest names one scenario, so a sweep's cells have to be readable apart
- [x] A live view shows every closed tick and nothing from an unclosed one — **amended in review**: a tick's *content* appears when the tick closes, and a world's own records (lifecycle, a degradation rung) appear as soon as they are written, because a paused run's reason for stopping is not a tick's content. Both backends apply the rule, so the identical-answers property holds for a paused run (`test_a_paused_world_answers_the_same_live_and_finalized`)
- [x] `events(filter)` accepts a typed filter and refuses anything outside it
- [x] `verbatims(grouping)` returns frozen models grouped as asked
- [x] `resolve(trace_ids)` returns exactly the referenced events, and raises when one is absent
- [x] Nothing in the returned models exposes storage — no paths, no cursors, no frames

---

## Phase 4: The derived shapes

**User stories**: 12

### What to build

Beliefs and edges, computed from the record rather than stored beside it. `beliefs(persona_id)` reads belief snapshots and the turns between them; `edges()` reads word-of-mouth deliveries and follows into `(u, v, channel, count, last_tick)`. Both are computed here and nowhere else, so the finalized path can reuse them rather than reimplement them.

### Acceptance criteria

- [x] `beliefs(persona_id)` reconstructs a persona's belief history from snapshots and turns
- [x] `edges()` returns one row per pair, channel and direction, with count and last tick
- [x] Both match the same quantities recomputed from raw events in a fixture
- [x] Neither reaches another persona's records when asked for one persona's
- [x] The derivation has exactly one implementation, asserted over the module

---

## Phase 5: Finalization

**User stories**: 10, 13, 14

### What to build

A finished world's lasting record. The payload union fans out into typed Parquet columns; the derived shapes are written by the same code that computes them live; the contract version goes into the Parquet metadata and the registry. Finalization is idempotent and a finalized world is read-only. The phase's real deliverable is the property: every read shape answers identically before and after.

### Acceptance criteria

- [x] `finalize(world_id)` writes events, beliefs and edges as Parquet, sorted by `(persona_id, tick)`
- [x] Every read shape answers identically before and after finalization, on the same world
- [x] Finalization is idempotent, and calling it twice changes nothing
- [x] A finalized world refuses further writes
- [x] The contract version is written once into the partition metadata and the registry entry
- [x] Parquet columns are typed per payload kind rather than a JSON blob

---

## Phase 6: The registry

**User stories**: 15, 16

### What to build

One entry per run, holding everything a replay needs to be set up from the registry alone: the configuration, brief, ontology, population and graph hashes, the seeds, the pins, the engine version, the recorded cost, the discarded ticks and the status. The registry is also what tells a view which backend to use.

### Acceptance criteria

- [x] A registry entry pins every hash, seed and pin a replay needs, plus the engine version
- [x] Recorded cost and discarded-tick count are readable from the entry
- [x] A run's status is readable and decides which backend a view opens
- [x] An entry for a run that already exists is refused rather than silently replaced, and `update` moves a run's progress without rewriting what a replay pins — **added in review**: a run's status and spend change as it works, and only `record` was on the port
- [x] A replay can be configured from the registry entry alone, asserted by round-tripping one

---

## Phase 7: Version-aware reads

**User stories**: 17, 18, 19

### What to build

The path that keeps stored runs readable. A migration registry applies every registered migration newer than a partition's own contract, in order, then validates strictly. A partition from a newer contract is refused rather than half-read. The tests carry a synthetic next version so the path is exercised before a real schema change needs it.

### Acceptance criteria

- [x] A partition written under 1.0 loads under a synthetic 1.1 through a registered migration
- [x] A partition from a contract newer than the engine's is refused, naming both versions
- [x] Migrations apply in order, and a missing migration in the chain fails loudly
- [x] A migrated partition is validated strictly after migration, not before
- [x] The contract version appears once per partition and on no event

---

## Phase 8: Scale and reconciliation

> Scale measurement (2026-09-18, `tests/boundary/trace/test_scale.py`): 500,032 events
> (500k billed calls across 30 ticks) round-trip with identical ordering; the world
> finalizes in ~30 s into ~5 MB of Parquet (cost-shaped events — turn-heavy worlds will be
> larger, per the 100–200 MB sizing in `FINAL_ARCH.md` §5.9).

**User stories**: 4, 5

### What to build

Proof it holds at the size a study reaches, and the documents in step. 500k events round-trip with their ordering intact; the module's types are checked for anywhere a whole prompt could hide; the architecture, salvage inventory and glossary are reconciled with what was built.

### Acceptance criteria

- [x] 500k events round-trip through write and read with identical ordering by `(persona_id, tick, seq)`
- [x] A world of that size finalizes within a bounded time and its Parquet size is recorded in the plan
- [x] No type in the module can hold a whole prompt, asserted over the module's annotations
- [x] `FINAL_ARCH.md` §5.9, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
- [x] Any defect this phase exposes is fixed with a test that fails on the old code
