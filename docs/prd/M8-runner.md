# PRD — M8 `runner`: running a study to completion inside a budget

## Problem Statement

Every part of a study now exists except the thing that runs it. `population` builds who is in it, `world` decides
what they see, `agent` produces what they do, `elicitation` scores it, `inference` pays for it and `trace` records
it — and nothing drives the loop, spends against a ceiling, survives an interruption or expands a sweep.

The budget is the reason this module owns more than a loop. An earlier design had a governor decide
`allow | degrade | halt` and left three modules to interpret that decision: `agent` freezing tier B, `world`
subsampling activation, a scheduler pausing. Three enforcement points for one policy means no single place can
answer *"does the budget actually stop spending?"*, and a misinterpretation changes fidelity mid-run and corrupts a
study without failing it. The governor applies degradation itself, by handing the other modules a different plan
between ticks, and they never learn that budgets exist.

Four risks belong here.

A run that cannot be resumed wastes model calls that were already paid for — the most expensive failure available.
A run that can be resumed *wrongly* is worse: continuing a study under changed inputs or changed engine code
produces one trace holding two experiments, with nothing saying so (ADR 0036).

A budget enforced against an invented number is not enforced. Costs arrive from `inference` as records with a
source, and an unknown cost stays unknown rather than becoming zero. A crash also loses the spend of the tick it
interrupted (ADR 0033), so the ledger is a floor, not a total.

A sweep that degrades unevenly produces cells nobody may compare. If one cell freezes reflections while another
keeps them, the difference between them is no longer the scenario.

And `trace` does not exist yet, so this module is built against the write port with a fake and meets the real one
at merge — the pattern `agent` already uses.

## Solution

`run(config: RunConfig) -> RunResult`, driving one tick at a time per world.

**The tick loop** — the runner asks `world` for a delta, turns its presentations into `TurnJob`s carrying each
persona's state, hands them to `agent` as one batch, feeds the completed turns back into `world`, and writes the
tick's events with its `tick_closed` in one transaction (ADR 0033). It assigns every `event_id` and `seq`; nothing
else writes.

**The plan, not the config** — each tick the runner hands `world` and `agent` a frozen per-tick plan: activation
rate, tier routing, whether tier-B work is enabled. Degradation is a different plan, not a mutated object shared
across parallel worlds.

**The ledger** — summed from the `cost` events the run recorded, kept as a running total while it works and
rebuilt by summing on resume (ADR 0035). The ladder is enforced against the pessimistic figure: recorded spend plus,
for each discarded tick, the mean cost of the ticks that completed.

**The ladder** — 80% warn, 95% freeze optional tier-B work, 100% subsample activation, beyond that pause. A rung
belongs to the run: every live world takes it at its next tick, records it as a `degraded` event, and on resume
applies the rung from the record rather than recomputing it (ADR 0037). A paused run keeps its completed worlds,
labelled partial.

**Resume** — state comes from the trace: personas rebuilt from their memory events, belief snapshots and turns;
worlds by `reset` and replaying recorded turns. A resume refuses when the brief, ontology, population, scenario,
pins or engine version moved, naming the one that moved, and a forced resume is recorded (ADR 0036).

**Sweep** — a grid of scenarios × seeds expanded into worlds of one run, sharing one budget, each world's id
derived from its scenario, replicate seed and population hash (ADR 0005). There is no separate sweep result.

## User Stories

**The loop**

1. As a researcher, I want a study run to completion from one configuration, so a result is reproducible from it.
2. As a runner, I want a tick's events written whole with their `tick_closed`, so an interrupted run leaves no
   fragment.
3. As a maintainer, I want the runner to assign every event id and sequence number, so a partition has one writer.
4. As a researcher, I want each persona's state carried between ticks and never shared, so a worker can take any
   persona.
5. As an operator, I want a world's failure to leave the rest of the run alive, so one provider error does not end
   a sweep.

**Budget**

6. As an operator, I want one place that decides and applies degradation, so "does the budget stop spending?" has a
   single answer.
7. As an operator, I want the observable effects at each rung — tier-B calls stop, activation actually drops, the
   run pauses — so a rung is a behaviour and not a log line.
8. As a researcher, I want every rung recorded in each live world at the tick it took effect, so a degraded world is
   never compared silently with a full one.
9. As an operator, I want spend summed from the recorded calls rather than a number the runner kept, so the ledger
   is auditable.
10. As an operator, I want a discarded tick's unknown spend treated as spent, so a crash makes a run stop earlier
    rather than overspend.
11. As a researcher, I want a paused run to keep every completed world, labelled partial, so partial results are
    still results.

**Resume**

12. As a researcher, I want resume to continue from the last closed tick and produce what an uninterrupted run
    would have, so an interruption costs time and not validity.
13. As a researcher, I want resume refused when the brief, ontology, population, scenario, pins or engine version
    moved, named explicitly, so two experiments never share one trace.
14. As a maintainer, I want a forced resume recorded and its results marked, so a deliberate exception is visible.
15. As a runner, I want resume to rebuild persona state and world state from the record, so no second copy can
    drift.

**Sweep**

16. As a researcher, I want a grid of scenarios and seeds expanded into worlds of one run, so a sweep is not a
    second concept.
17. As a researcher, I want the same grid run twice to produce identical world ids, so cells are addressable.
18. As a researcher, I want one budget across a sweep, so a grid cannot spend N times its ceiling.
19. As an analyst, I want a result that carries one outcome per world — status, last closed tick, rungs applied —
    so the run's status is computed rather than asserted.

## Implementation Decisions

**Concurrency** — one process per world; inside a world, one thread driving ticks. The parallelism that pays is in
`inference`'s batching and in running worlds at once; threads inside a world would add concurrent writers to the
world's own store for no gain.

**The per-tick plan** — a frozen object per tick: activation rate, tier routing, tier-B enabled. `WorldConfig`
gains an activation-rate multiplier to receive it; `AgentConfig` already takes a routing table.

**Cost** — the ledger sums `cost` events; `CostSource.UNKNOWN` stays unknown and never becomes zero. The
pessimistic figure is what the ladder tests.

**Discarded ticks** — on resume, the tick thrown away is recorded before anything else, and the registry states how
many were lost.

**Resume refusals** — compared against the registry entry: brief, ontology, population, graph, scenario, pins,
engine version. Each refusal names the moved thing; `--force` records itself.

**Sweep** — `world_seed = h(replicate_seed, variant_id)`,
`world_id = sha256(canonical_hash(scenario), replicate_seed, population_hash)[:12]` (ADR 0005), so "have I run this
cell?" is answerable without a registry query.

**Trace** — written through a port with a fake in this module's tests; the real writer arrives at merge.

**Salvage** — ASAL `main_sweep_gol.py` for the sweep pattern and `rollout.py` for the run-then-score shape;
MatrAIx `llm_usage.py`, `budget.py`, `jobs.py` and `job_aggregation.py` for accounting and aggregation plumbing.

## Testing Decisions

Boundary tests through `run`, with in-memory adapters and a synthetic cost stream; the suite reaches no network.

- Feeding a cost stream past each threshold produces the observable effect: tier-B calls stop, the activation rate
  handed to `world` actually drops, the run pauses.
- A paused run retains every completed world, labelled partial.
- Killing a run mid-tick and resuming produces a result identical to an uninterrupted run, and the trace holds no
  fragment of the interrupted tick.
- A degraded world's partition records every rung applied, and a replay applies the recorded rung rather than
  recomputing it.
- The same sweep grid run twice produces identical world ids.
- A moved brief, ontology, population, scenario, pin or engine version each refuse resume, naming what moved; a
  forced resume is recorded.
- A discarded tick is recorded, and the budget's pessimistic figure includes it.
- One world raising leaves the others running and the run's status computed from its worlds.
- Persona state rebuilt on resume equals the state the run carried.

## Out of Scope

Trace storage, the read views and finalization internals (`trace`, module 9). Digests, findings and anomalies
(`analysis`, module 10). Rendering (`report`, module 11) and entrypoints (`cli`, module 12). Anything that decides
what a persona sees or says — that is `world` and `agent`, and this module only hands them a plan.

## Further Notes

`TraceView` lands on `master` before this branch begins, together with the trace write port, so both modules build
against the same seam.

The architecture's degrade rungs use activation 0.62 → 0.40 as an example. Those numbers are configuration here,
not code, because the right subsample depends on how many personas a study drew.
