# PRD — M12 `cli`: the way in

## Problem Statement

Every module works and none of them can be reached. Running a study today means writing a script that wires
population, world, agent, runner, trace and analysis together by hand — which is exactly what the first real
study did, and that script is 300 lines of plumbing a user should never see. There is no path from a clean
checkout to a report, and no way for a new reader to satisfy themselves that the engine does anything at all
without an AWS account and a 4 GB download.

Two risks. A study that fails for a legitimate reason — a gate the population could not pass, a budget that
ran out — must be distinguishable from a crash by a shell script, or automation cannot tell "the study says
no" from "the engine broke". And a first run that requires credentials and a corpus is a first run most people
never take, which for an open research instrument is the difference between reproducible and merely published.

## Solution

Four commands, each printing the `run_id` that names what it produced.

| Command | What it does |
|---|---|
| `coreset-gate --brief b.yaml --n 1500 --seed 4021` | gate report and population manifest, no model calls beyond completion |
| `ssr-replica --anchors <set> --population manifest.json` | the anchor check and its distribution diagnostics |
| `concepts run brief.yaml [--fake]` | the whole study: `report.md`, `report.json`, and the run id |
| `sweep run --grid grid.yaml --budget 42` | a sweep and its per-cell summary |

`--fake` runs the entire pipeline on `FakeInference` and a synthetic coreset: no API key, no dataset, no
network. It is the path a new user hits first, so it runs in CI as a first-class target rather than as a debug
flag.

Exit codes come from the exception class, so a shell can branch on them: `SimError` 1, `GateFailure` 2,
`BudgetExhausted` 3, `SchemaVersionError` 5.

Where a study could not measure adoption — which is every study until an anchor version passes its check
(ADR 0029) — the command still runs and the report says so. A tool that refused to produce a report without
ratings would be unusable in precisely the state the engine is in.

## User Stories

1. As a new user, I want `concepts run brief.yaml --fake` to produce a report from a clean checkout, with no
   key and no download, so I can see what the engine does before committing anything to it.
2. As a user, I want every command to print its run id, so the artefacts it wrote can be found again.
3. As an operator, I want a failed gate to exit 2 and a crash to exit 1, so automation can tell a study's
   verdict from a defect.
4. As an operator, I want an exhausted budget to exit 3 with the partial results kept, so a stopped run is not
   a lost one.
5. As a researcher, I want `coreset-gate` to report a population's gates without running a study, so a doomed
   study costs nothing.
6. As a researcher, I want `ssr-replica` to run the anchor check on a named anchor set, so a supplied scale
   can be judged before a study depends on it.
7. As a user, I want `concepts run` to write `report.md` and `report.json` side by side, so both audiences are
   served by one command.
8. As a researcher, I want `sweep run` to take a grid and a budget and return per-cell summaries, so scenarios
   can be compared.
9. As a user, I want a study that could not measure adoption to still produce a report that says so, so the
   engine is usable today.
10. As a maintainer, I want the fake path exercised in CI, so the first thing a stranger runs is the thing we
    test most.

## Implementation Decisions

**Argument plumbing only.** The CLI wires modules together and formats errors; it computes nothing and decides
nothing a study did not already state.

**Exit codes from the exception class**, mapped in one place, with every mapped class covered by a test.

**`--fake` is a target, not a flag**: `FakeInference` plus `SyntheticCoresetSource`, asserted in CI to produce
a report end to end.

**Artefacts** go to a run-named directory, and the command prints the path and the run id rather than assuming
a working directory.

**Test posture.** Boundary tests invoke the commands in-process with temporary directories; the suite reaches
no network. The fake end-to-end run is one of them.

## Testing Decisions

- `concepts run --fake` produces `report.md` and `report.json` from a clean temporary directory, with no key
  and no corpus.
- Each mapped exception class produces its documented exit code, and an unmapped exception produces 1.
- Every command prints a run id that matches the artefacts it wrote.
- A study whose adoption is unmeasured still exits 0 and writes a report that says so.
- `coreset-gate` writes a gate report and a manifest and makes no study run.
- A budget exhausted mid-sweep exits 3 and leaves the completed cells' artefacts in place.

## Out of Scope

Anything a module already owns: the CLI does not derive, render, or decide. A web interface or API. Scheduling
and orchestration beyond what `runner` provides. Client-specific report templates.

## Further Notes

`--fake` matters more than its size suggests: it is the only claim the project can make that a reader can
check in one command, and for an open research instrument that is the difference between reproducible and
merely published.
