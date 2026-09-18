# Plan: M12 `cli` — the way in

> Source PRD: `docs/prd/M12-cli.md`
> Binding decisions: ADR 0038 (a study with no measurable adoption still reports), ADR 0042 (a report carries what produced it), ADR 0037 (a paused run keeps its completed worlds), ADR 0036 (a resume refuses by name), ADR 0029 (anchors are a study input), ADR 0016 (no corpus rows committed). `CONTEXT.md` (Study, World, Sweep, Rung, Unmeasured). Where `FINAL_ARCH.md` §5.12 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Plumbing only** — the CLI wires modules together, formats errors and writes files. It derives nothing, renders nothing and decides nothing a study did not already state.
- **Every command prints its run id**, and the path it wrote to, so artefacts can be found again.
- **Exit codes come from the exception class**, mapped in one place: `SimError` 1, `GateFailure` 2, `BudgetExhausted` 3, `SchemaVersionError` 5. A study's verdict is never mistaken for a defect.
- **`--fake` is a first-class target** — `FakeInference` and a synthetic coreset, no key, no dataset, no network, exercised in CI. It is the first thing a stranger runs.
- **A study that measured no adoption still reports** — refusing would make the engine unusable in exactly the state it is in.
- **Artefacts land in a run-named directory**, never in whatever directory the user happened to be in.
- **Test posture** — commands invoked in-process against temporary directories; the fake end-to-end run is one of the tests. The suite reaches no network.

---

## Phase 1: `concepts run --fake`

**User stories**: 1, 7, 10

### What to build

The path from a clean checkout to a report, with nothing required. `concepts run brief.yaml --fake` builds a synthetic population, runs the study on `FakeInference`, records a trace, digests it, renders it, and writes `report.md` and `report.json` beside the run id it prints. It runs in CI, because the first thing a stranger runs should be the thing we test most.

### Acceptance criteria

- [x] `concepts run brief.yaml --fake` writes `report.md` and `report.json` into a run-named directory
- [x] It needs no API key, no corpus download and no network, asserted by the suite's own network refusal
- [x] It prints the run id, and the id matches the artefacts and the registry entry
- [x] The whole pipeline runs — population, world, agent, runner, trace, analysis, report — with no module stubbed
- [x] The command is a CI target rather than a manual step
- [x] Two fake runs under one seed produce identical reports

---

## Phase 2: Exit codes

**User stories**: 3, 4

### What to build

The mapping a shell can branch on, in one place. A failed gate exits 2, an exhausted budget exits 3 with its partial results kept, a contract mismatch exits 5, anything else the engine raises exits 1 — and an unexpected exception exits 1 rather than something arbitrary.

### Acceptance criteria

- [x] Each mapped exception class produces its documented exit code
- [x] An unmapped exception exits 1 and prints what happened
- [x] A failed gate exits 2 and writes the gate report that explains it
- [x] An exhausted budget exits 3 and leaves every completed world's artefacts in place
- [x] The mapping lives in one place, and a new exception class without a mapping is caught by a test

---

## Phase 3: `coreset-gate` and `ssr-replica`

**User stories**: 5, 6

### What to build

The two pre-flight commands. `coreset-gate` draws a population and reports its gates and manifest without running a study, so a doomed study costs nothing. `ssr-replica` runs the anchor check on a named anchor set against the pinned embedding model and reports its diagnostics, so a supplied scale is judged before a study depends on it.

### Acceptance criteria

- [x] `coreset-gate` writes a gate report and a population manifest, and starts no world
- [x] Its exit code distinguishes a failed gate from a crash
- [x] `ssr-replica` reports the ladder, rank stability and non-collapse for a named anchor set
- [x] A version that fails its check is reported as failing and is not pinned
- [x] Both commands print the run id and the path they wrote

---

## Phase 4: `concepts run` against a real endpoint

**User stories**: 2, 9

### What to build

The same command without `--fake`: a real population from the corpus, a real endpoint from the environment, artefacts in a run-named directory. Where the study could not measure adoption — every study until an anchor version passes — the report says so and the command still exits 0.

### Acceptance criteria

- [x] A real run writes its trace, digest and both report formats, and prints the run id
- [x] A study with no measurable adoption exits 0 and reports why
- [x] The report's method disclosure names the pins, seeds and engine commit that produced it
- [x] A resume refused by changed inputs exits with the refusal naming what moved
- [x] The command passes the environment's endpoint configuration through without reinterpreting it

---

## Phase 5: `sweep run`

**User stories**: 8

### What to build

A grid of scenarios and seeds run as one study under one budget, with per-cell summaries written out. Cells that ran at different degradation rungs are marked rather than silently compared, and a budget that stops the sweep leaves what completed.

### Acceptance criteria

- [x] `sweep run --grid grid.yaml --budget 42` runs the grid as one run under one budget
- [x] Per-cell summaries are written, carrying each cell's seeds and their spread
- [x] A cell that ran degraded is marked in the output
- [x] A budget exhausted mid-sweep exits 3 and keeps the completed cells' artefacts
- [x] Re-running an interrupted sweep completes only the cells that had not finished
- [x] `FINAL_ARCH.md` §5.12, `SALVAGE.md` and `CONTEXT.md` describe what was built
