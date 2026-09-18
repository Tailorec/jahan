# Plan: M8 `runner` — running a study to completion inside a budget

> Source PRD: `docs/prd/M8-runner.md`
> Binding decisions: ADR 0033 (a tick is recorded whole, or not at all), ADR 0035 (run state is derived from the trace), ADR 0036 (a resume refuses a run whose inputs or engine moved), ADR 0037 (a rung belongs to the run and is replayed), ADR 0011 (a world resumes by replay; no world state crosses the boundary), ADR 0030 (persona state travels with its job), ADR 0031 (the agent answers in batches), ADR 0023 (batches in request order, failures as outcomes), ADR 0005 (world identity and seeds), ADR 0032 (an unscorable reaction keeps its verbatim), ADR 0008 (trust stays uncalibrated). `CONTEXT.md` (Rung, Cost Ledger, Discarded Tick, Sweep, Tick Closed, World, Study, Degradation). Where `FINAL_ARCH.md` §5.8 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **One interface** — `run(config: RunConfig) -> RunResult`: one outcome per world, and the run's status computed from them, never asserted.
- **One writer** — the runner assigns every `event_id` and `seq`, buffers a tick, and writes it with its `tick_closed` in one call. A crash leaves no fragment.
- **The plan, not the config** — each tick `world` and `agent` receive a frozen plan (activation rate, tier routing, tier-B enabled). Degradation is a different plan, never a mutated object shared across parallel worlds, and neither module learns that budgets exist.
- **One enforcement point** — the ladder is decided and applied here. 80% warn, 95% freeze optional tier-B work, 100% subsample activation, beyond that pause; rung thresholds and the subsample are configuration, not code.
- **A rung belongs to the run** — every live world takes it at its next tick and records it; a resume applies the recorded rung rather than recomputing it.
- **Nothing is checkpointed authoritatively** — persona state is rebuilt from the trace, worlds by `reset` and replay, the ledger by summing recorded costs. A checkpoint may exist as a cache and must agree with the record.
- **The ledger is a floor** — unknown costs stay unknown, and a discarded tick's spend is unknown but not zero, so the ladder is enforced against recorded spend plus an estimate per discarded tick.
- **A partial result is a result** — a paused or failed world keeps what it completed, labelled partial.
- **Sweep is not a second concept** — scenarios × seeds expand into worlds of one run sharing one budget, with ids derived from scenario, replicate seed and population hash.
- **Test posture** — boundary tests through `run`, with a fake trace writer, `FakeChat`/`FakeEmbed`, and a synthetic cost stream. The suite reaches no network.

---

## Phase 1: The tick loop, one world end to end

**User stories**: 1, 2, 3, 4

### What to build

The loop made true on the narrowest path: one world, one scenario, a handful of personas, the survey room. The runner asks `world` for a delta, turns its presentations into `TurnJob`s carrying each persona's state, hands them to `agent` as one batch, feeds the completed turns back into `world`, and writes the tick's events with its `tick_closed` through the trace port. Sequence numbers, event ids and the tick boundary are settled here and never revisited.

### Acceptance criteria

- [x] A run drives a world from `reset` to its horizon and returns a `RunResult` with one outcome per world
- [x] Each tick's events are handed to the trace in one call, with `tick_closed` last
- [x] The runner assigns every `event_id` and `seq`, and a tick's sequence numbers are gapless
- [x] Nothing of an unfinished tick reaches the trace, asserted by interrupting a tick
- [x] Each persona's state is carried tick to tick and never shared between personas
- [x] A turn failure is recorded and the tick still closes

---

## Phase 2: Resume from the record

**User stories**: 12, 15

### What to build

Continuing a run that stopped. State comes from the record: personas rebuilt from their memory events, belief snapshots and turns; each world by `reset` and replaying its recorded turns to the last closed tick. The run then proceeds as if it had never stopped, and the proof is that it produces what an uninterrupted run produces.

### Acceptance criteria

- [x] A run killed mid-tick and resumed produces a result identical to an uninterrupted run
- [x] Persona state rebuilt on resume equals the state the run carried
- [x] A world resumed at tick N continues identically to one that never stopped
- [x] Resume needs nothing but the trace and the registry entry
- [x] A checkpoint, if present, is validated against the record and discarded when it disagrees
- [x] Completed ticks are never re-run

---

## Phase 3: Refusing the wrong resume

**User stories**: 13, 14

### What to build

The guard that keeps one trace from holding two experiments. Resume compares the run's inputs against the registry entry — brief, ontology, population, graph, scenario, pins and engine version — and refuses when any moved, naming the one that did. A forced resume is possible, records that it was forced, and marks the run's results as spanning versions.

### Acceptance criteria

- [x] Each of brief, ontology, population, graph, scenario, pins and engine version, moved alone, refuses resume
- [x] Every refusal names the thing that moved and what it moved from
- [x] A forced resume proceeds, is recorded in the registry, and marks the run's results
- [x] An unforced resume under identical inputs proceeds silently
- [x] The engine version comes from the registry entry, not from the running process's assumption about itself

---

## Phase 4: The cost ledger

**User stories**: 9, 10

### What to build

What the run has spent, derived rather than remembered. The ledger sums the `cost` events the run recorded, including what failed and discarded calls billed; an unknown cost stays unknown. On resume it is rebuilt by summing. A tick the run discarded is recorded as discarded, and its unknown spend is estimated from the ticks that completed, so the figure the ladder tests is pessimistic.

### Acceptance criteria

- [x] The ledger equals the sum of the run's recorded `cost` events, rebuilt by summing on resume, with each unpriced call charged at the mean of the priced ones — **amended in review**: counting an unknown cost as zero meant a run whose gateway quoted no prices spent its whole horizon with no rung firing, and a run where nothing carries a price now stops rather than spending blind
- [x] An unknown cost stays unknown and never becomes zero
- [x] Costs from failed and discarded calls are counted
- [x] A discarded tick is recorded before anything else on resume, and counted in the registry
- [x] The figure the ladder tests is recorded spend plus an estimate per discarded tick
- [x] A run that lost a tick stops earlier than one that lost none, on the same budget

---

## Phase 5: The degrade ladder

**User stories**: 6, 7, 8, 11

### What to build

The budget as behaviour. A synthetic cost stream pushes the ledger past each threshold, and each rung has an observable effect: a warning recorded, optional tier-B work frozen in the plan handed to `agent`, the activation rate lowered in the plan handed to `world`, and finally the run paused with its completed worlds kept and labelled partial. Every rung is recorded in each live world at the tick it takes effect, and a replay applies the recorded rung.

### Acceptance criteria

- [x] Each threshold produces its observable effect: tier-B calls stop, the activation rate handed to `world` drops, the run pauses
- [x] Rung thresholds and the activation subsample are configuration a study can change
- [x] Every live world records a `degraded` event at the tick a rung took effect, with the rate and freeze in force
- [x] A replay applies the recorded rung rather than recomputing it from the ledger
- [x] A paused run keeps every completed world, labelled partial
- [x] `world` and `agent` receive plans and never learn that a budget exists, asserted over their inputs

---

## Phase 6: A world that fails

**User stories**: 5, 19

### What to build

Isolation. A world that raises — a provider outage, a corrupt scenario, an exhausted circuit — is recorded as `partial` or `not_started` with its last closed tick and the rungs it saw, and the rest of the run continues. The run's status is computed from its worlds.

### Acceptance criteria

- [x] One world raising leaves every other world running
- [x] A failed world's outcome records its status and last closed tick
- [x] The run's status is computed from its worlds and refuses a contradicting stated value
- [x] A world that never started is recorded as such rather than omitted
- [x] A run where every world failed returns a result rather than raising

---

## Phase 7: Sweep

**User stories**: 16, 17, 18

### What to build

Many worlds, one run, one budget. A grid of scenarios and replicate seeds expands into worlds whose ids derive from the scenario, the seed and the population hash, so the same grid run twice addresses the same cells and "have I run this?" needs no registry query. Worlds run in parallel, one process each, against a shared ledger.

### Acceptance criteria

- [x] A grid of scenarios × seeds expands into one world per cell, with ids derived per ADR 0005
- [x] The same grid run twice produces identical world ids
- [x] One budget covers the whole sweep, and a grid cannot spend a multiple of its ceiling
- [x] Worlds run in parallel and a single world's content is reproducible — **amended in review**: a thread per world rather than a process. The work is model calls, so it is I/O-bound and the interpreter lock costs nothing; each world owns its own SQLite connection and its own seeds. The trade is isolation: a world's exception is caught and recorded (phase 6), but a hard interpreter crash takes the run down, where separate processes would not
- [x] A cell that ran at a different rung than another is marked, so the comparison is not drawn silently
- [x] Resuming a sweep re-runs only the cells that had not completed

---

## Phase 8: Reconciliation

**User stories**: —

### What to build

The real trace writer in place of the fake, and the documents in step. The runner is pointed at `trace`'s write port and registry, a full run is recorded and read back through `TraceView`, and the architecture, salvage inventory and glossary are checked against what was built.

### Acceptance criteria

- [x] A full run writes through the real trace writer and reads back identically through `TraceView`, and a world that reaches its horizon is finalized — **added in review**: nothing asked the trace to finalize, so a finished study stayed in its live store and the Parquet path never ran outside the trace's own tests
- [x] A recorded run's events validate as a `TracePartition` against its header
- [x] `FINAL_ARCH.md` §5.8, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
- [x] Any defect the integration exposes is fixed with a test that fails on the old code
- [x] The engine's first end-to-end run — brief to recorded trace — is captured as a short evaluation with its cost
