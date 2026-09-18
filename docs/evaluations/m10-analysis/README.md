# Evaluation: M10 reconciled against a regenerated study

*2026-09-18 · offline, deterministic, no network · `regen_study.py` beside this file is the script*

The first real study's trace is gone — only its reports were kept — so this phase
regenerates a small study and digests it end to end: 40 synthetic personas, one
scenario, two replicate seeds, three ticks in a survey room, run through the real
`runner` and the real trace store, then read back through finalized views.

## What ran

| | |
|---|---|
| Brief | `examples/protein_water.yaml` |
| Population | synthetic stand-in rows, 40 personas, seed 4021 |
| Worlds | `a00631e91974` (seed 4021), `4ecd96cdea45` (seed 917731) |
| Turns | stub survey answers — even personas scored for purchase intent, odd ones kept as recorded elicitation failures |
| Embeddings | stub vectors for clustering; the intent masses are recorded stub distributions, not elicitation output |

`partitions/world-<id>.json` are the two worlds as validated `TracePartition`s;
`population.json` is the population they ran over; `digest-report.json` is the
analysis output. Rerunning the script reproduces the same world ids and the same
digest report; only non-canonical JSON ordering varies.

## What the digest says

| | seed 4021 | seed 917731 |
|---|---|---|
| Turns | 80 | 80 |
| Scored for intent | 42 | 42 |
| Adoption | 0.65 | 0.65 |
| Findings | 1 objection, 2 belief-shift | 1 objection, 2 belief-shift |
| Anomalies | 2 (herding rule, see below) | 2 |
| Word of mouth | 0 deliveries (survey room) | 0 |

Spread across seeds is 0.0, reported as such rather than omitted; no world ran
degraded. Trust is `UNCALIBRATED`.

Two notes on the numbers. The adoption of 0.65 is a plumbing check, not a finding:
the masses behind it are stub-recorded, and the stub scored only half the turns.
The herding flags fire because the replicate spread is 0.0 — the two worlds agree
exactly, so twice the spread is 0 and any window movement is beyond it. That is the
rule as specified (`|mean| > 2σ`), applied literally; a zero yardstick measures
nothing, and the flags say so with their carried threshold of 0.

## What reconciling exposed

**A two-seed run could not validate a report.** `Report` held one digest per
scenario, so the two digests of this study's single scenario were refused as
"digested more than once". A digest is one world's (ADR 0039) yet named no world,
so per-world digests were indistinguishable. `OutcomeDigest` now names its world —
scenario hash, replicate seed and derived world id, checked against the world the
view read — `ScenarioSummary` entries must agree with the digest they carry, and a
report holds one digest per world of the run. Fixed with the test that digests this
very study and validates its report, which fails on the old shapes.

**Finalization validates, and it bit the regen script twice.** Duplicate impression
and reaction ids in the stub world were refused at read-back with the exact sequence
numbers — the partition guard working as designed, not an engine defect.

## Caveats, stated plainly

- The models are stubs: turn counts and belief moves exercise derivation, not behaviour.
- Purchase intent was recorded, not elicited: adoption demonstrates the digest, not demand.
- The trust level stays `UNCALIBRATED` (ADR 0008).
