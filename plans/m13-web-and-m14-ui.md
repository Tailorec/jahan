# Plan: M13 `web` and M14 `ui` — the engine with a face on it

> Source PRD: `docs/prd/M13-web-and-M14-ui.md`
> Binding decisions: ADR 0043 (single-operator local application), ADR 0044 (an ontology is an immutable versioned study input), ADR 0045 (the web layer derives nothing), ADR 0046 (a prompt is reconstructed and verified, never stored), ADR 0034 (one trace view, five closed read shapes), ADR 0038 (unmeasured is stated with its reason), ADR 0041 (clusters are quoted, never generated), ADR 0042 (a report is derived from the record), ADR 0021 (one OpenAI-compatible endpoint), ADR 0016 (research instrument, research-only corpus), ADR 0008 (trust stays uncalibrated). `CONTEXT.md` (Population, Audience, Community, Category Ontology, Conditioning, Digest, Unmeasured, Trust Level, Finding, Disconfirming Test). The mockups at `~/jahan_sim/mockups` describe the flow; where they disagree with the glossary or an ADR, the glossary and the ADRs win.

## Architectural decisions

Durable across every phase:

- **Two modules, one product** — `simcore/web/` (M13) serves the engine over HTTP; `frontend/` (M14) is the Next.js interface. `ui` holds no engine logic and is the only module not written in Python.
- **The web layer derives nothing** — it serialises, filters, pages and streams. Every number it returns is a field of something `analysis`, `trace` or a contract produced. A panel wanting an underived number is blocked until `analysis` derives it.
- **One implementation, two delivery paths** — a derived shape is computed once in Python; the CLI writes it into the run directory at the end of a run, and the API serves the same function live. Neither path recomputes what the other computes.
- **The five shapes are the way in** — `events`, `beliefs`, `edges`, `verbatims`, `resolve`, plus `analysis`'s digest, findings, clusters and anomalies. Nothing reaches storage another way, and no endpoint returns a row, a frame or a path.
- **Routes** — `/api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/summary`, `/api/runs/{run_id}/events`, `/api/runs/{run_id}/worlds/{world_id}/{beliefs|edges|verbatims|resolve}`, `/api/runs/{run_id}/{digest|findings|clusters|anomalies|report}`, `/api/codebook`, `/api/ontologies`, `/api/ontologies/{category}/{version}`, `/api/briefs`, `/api/workspace`, `/api/health`. Run lifecycle is `POST /api/runs`, `DELETE /api/runs/{run_id}`, `POST /api/runs/{run_id}/resume`.
- **Runs are subprocesses** — the registry is authoritative for what happened, the process table only for whether it is still running. Orphans from a killed session are swept on server start. Progress is polled; a tick takes tens of seconds and streaming buys nothing.
- **Execution configuration stays in the environment** — base URL, key, concurrency and rate limits are the server's, never hashed, never rendered, never accepted in a browser. Model pins and prices are study inputs, recorded and hashed.
- **`simcore[web]` extra** — the core keeps its ten runtime dependencies, as telemetry already does.
- **The interface speaks the glossary** — Population, not cohort. Audience and Community, never segment.
- **Test posture** — the API is exercised in-process against temporary directories with the fake backend, and the suite reaches no network. The interface is exercised against the real artefacts of a recorded run, never against fixtures invented for it.

---

## Phase 1: `TraceSummary`, and the file the frontend is waiting for

**User stories**: 12, 14, 17

### What to build

The frontend already reads `ui-trace.json`, and nothing writes it. What it wants — belief histories, the word-of-mouth edges, verbatims grouped, events counted by kind, costs by role — is what the five shapes already answer, so this phase computes it once, in the module that owns derivation, and writes it where a finished run keeps its artefacts.

`trace_summary(view) -> TraceSummary` joins the five shapes into one frozen model. The CLI writes it beside `report.json` at the end of a run. The existing run, trace and report pages light up against real recorded studies without a server existing yet.

### Acceptance criteria

- [ ] `trace_summary(view)` returns a frozen model carrying belief histories, edges, grouped verbatims, event counts per kind and costs per role, each from the shape that owns it
- [ ] Every quantity in it matches the same quantity recomputed from raw events on a fixture trace
- [ ] It reaches storage only through the five shapes — no path, no frame, no second way in, asserted over the module
- [ ] A study writes it into the run directory beside the other artefacts, and a paused run writes what it has
- [ ] The interface renders a real recorded study's trace, beliefs and verbatims with no mock state
- [ ] Two summaries of one trace are identical, so a diff means a difference in the record

---

## Phase 2: The `web` module

**User stories**: 21, 22

### What to build

The server, and the discipline that keeps it thin. `simcore/web/` serves the five shapes, `TraceSummary`, the digest, findings, clusters, anomalies and the report — live, from a running or finished study, with the registry deciding which backend a view opens. The interface's own API routes become proxies to it rather than readers of disk, so there is one path to every number.

### Acceptance criteria

- [ ] Each of the five shapes has an endpoint returning frozen models, with a typed filter rather than free keyword arguments
- [ ] A live run and a finished run answer identically through the same endpoints
- [ ] The package performs no arithmetic over what it serves, asserted over the module in the shape `report`'s discipline test already uses
- [ ] No endpoint returns a filesystem path, a cursor or a frame
- [ ] The API is exercised in-process against temporary directories with the fake backend, and reaches no network
- [ ] The server ships as the `simcore[web]` extra, and the core's runtime dependencies are unchanged
- [ ] The interface reads every engine number through the API, and its direct filesystem reads are gone

---

## Phase 3: Trust, stated once

**User stories**: 16, 18, 19, 20

### What to build

The page the mockups call calibration, told honestly. The run's `TrustStatement` appears once and is `UNCALIBRATED`; the ladder shows what would earn the next rung — a `CalibrationRef` pinning a benchmark report and a human study by hash, both clearing the floors — and nothing in the interface can adjust it. Where a digest could not measure a quantity, the reason it carries is shown in the place the number would have been.

### Acceptance criteria

- [ ] Every study view states the run's calibration exactly once, and no finding carries one
- [ ] The trust page shows the ladder and what a level above `UNCALIBRATED` requires, without displaying an accuracy number the engine has not earned
- [ ] A quantity reported as not measurable renders its reason where the number would have appeared
- [ ] A run forced across engine versions or past moved inputs says so
- [ ] Nothing in the interface writes or overrides a trust level
- [ ] A finding's own confidence renders beside it and is never presented as the engine's calibration

---

## Phase 4: Launching a fake study, and watching it

**User stories**: 7, 8, 9, 10, 11

### What to build

A study started from the interface, running as a subprocess, watched while it works. The runner publishes its progress — status, recorded cost, ticks closed — to the registry entry as it goes, so spend is something a person can act on rather than read afterwards. Cancelling ends the process and loses at most the tick in flight; resuming is a re-run with the same id.

The first study anyone runs is `--fake`: no key, no corpus, no network, a real report in minutes, marked as fake wherever it appears.

### Acceptance criteria

- [ ] A study starts from the interface and its run id, artefacts and registry entry agree
- [ ] Recorded cost and ticks closed are readable while the run is going, not only when it ends
- [ ] The interface shows ticks closing, turns landing, spend against the budget and the rung in force
- [ ] Cancelling stops the run, loses at most the tick in flight, and the trace stays valid
- [ ] A cancelled run resumes and completes, skipping the worlds that reached their horizon
- [ ] A run outlives a restart of the server, and orphans are swept into a truthful status on start
- [ ] A fake run needs no key, no corpus and no network, and is marked as fake in every view of it

---

## Phase 5: The population page

**User stories**: 6, 15

### What to build

Who was drawn and whether the draw was sound. The gate report's per-attribute results with their statistics and thresholds, requested against achieved audience mix, the source mix and attribute origins, the synthesized share and the completion policy that allowed it, and a sample of real personas. Audiences appear as audiences; communities, when the graph forms any, appear separately.

### Acceptance criteria

- [ ] Every gate result shows its statistic, its threshold and its verdict, so a reader can recompute the call
- [ ] Requested and achieved audience mix are shown together, and a relaxation that was applied is visible
- [ ] The synthesized share and which domains may be completed are stated
- [ ] Sample personas render from the population's own records, with each attribute's origin
- [ ] Audiences and communities are presented as different things, and a population that formed no communities says so with the reason
- [ ] A failed gate is readable, since a study that never ran is the case the page most needs to explain

---

## Phase 6: The ontology builder

**User stories**: 1, 2, 3, 4, 5

### What to build

The screen that decides what can be studied. The codebook's attributes are browsable and searchable with their real value sets; a draft is assembled from them; every name is checked against the codebook as it is typed. Ordinal scales are built from the codebook's own labels in their own order. Saving produces a new version rather than changing a file, and a draft that has never been validated against a present codebook cannot become one.

The conditioning set is presented as what it is: the field that decides whether personas differ from one another at all.

### Acceptance criteria

- [ ] The codebook's attributes are searchable with their declared value sets, from the corpus rather than from a copy
- [ ] An attribute the corpus does not carry is refused as it is entered, naming what the codebook does have that resembles it
- [ ] An ordinal scale is built from the codebook's own labels, in the order the codebook states them
- [ ] Saving an edited ontology creates a new version and leaves every existing version untouched
- [ ] A study names the version it ran on, and that version resolves for as long as the study exists
- [ ] A draft may be authored without the corpus present and cannot be pinned until it validates against one
- [ ] The conditioning set is explained where it is chosen, with what it costs to leave an attribute out

---

## Phase 7: Intake, and a real study

**User stories**: 6, 11

### What to build

The brief and the scenario, configured in the engine's own words: product, claims with their sources and evidence, price, competitors, audiences and their shares, assumptions. Then the study itself — variants, environment, horizon and tick unit, elicited task, replicate seeds, budget — and the pins a real run needs. The endpoint is reported as configured or not; no key is ever asked for in a browser.

### Acceptance criteria

- [ ] A brief is authored and validated against the engine's own contracts before a run can start
- [ ] Every term the form uses is the glossary's, with its definition available where it is set
- [ ] The assumption ledger is assembled from what the brief states and what it leaves unstated
- [ ] A study states what its personas are asked, and a purchase-intent study names the anchor version that scores it
- [ ] The interface reports whether an endpoint is configured and never accepts or displays a key
- [ ] A real study runs from the interface end to end and writes the same artefacts the command line does

---

## Phase 8: One persona's whole history

**User stories**: 12, 13, 14

### What to build

The unit the engine actually records. One persona's timeline — what it was shown, what it said, how its beliefs moved tick by tick, which memories it wrote, who it heard from and who heard from it. And the prompt behind any turn, rebuilt from the recorded parts and checked against the hash the turn carries before it is shown.

### Acceptance criteria

- [ ] A persona's events, beliefs and verbatims are shown in one timeline, and none of another persona's appear in it
- [ ] Belief movement is shown per dimension and per claim, before and after, from the recorded snapshots and turns
- [ ] The influence neighbourhood is drawn from the recorded edges, naming the channel and how often
- [ ] A turn's prompt is reconstructed from the record and displayed only when it matches the turn's recorded hash
- [ ] A prompt that cannot be reconstructed says so and why, rather than showing an approximation
- [ ] Nothing in the interface stores a prompt, asserted over what it persists

---

## Phase 9: The atlas

**User stories**: 15, 17

### What to build

A study's shape rather than one persona's. Adoption against polarization across a scenario's worlds; per-tick trajectories for audiences and, separately, for communities; the replicate spread that says whether an ordering survives; and two finding kinds the engine declares but has never authored — `ranking` over a scenario's replicates and `risk` from the anomalies already detected.

### Acceptance criteria

- [ ] Trajectories per audience and per community per tick are a derived shape in `analysis`, matching the same quantities recomputed from raw events
- [ ] `ranking` findings are authored by extraction from a scenario's digests, carrying the spread that says whether the order survives its replicates
- [ ] `risk` findings are authored from recorded anomalies, each with its evidence and its disconfirming test
- [ ] A cell whose worlds ran at different degradation rungs is marked rather than silently compared
- [ ] A quantity no world measured is stated as unmeasured with its reason, never drawn as zero
- [ ] Nothing generated appears as a finding, asserted over what the atlas renders

---

## Phase 10: The workspace, and reconciliation

**User stories**: 21, 22

### What to build

The first screen, and the documents in step. A workspace summary over registry entries — studies run, spend against budget, personas simulated, reports written — derived in `analysis` and read from entries rather than by walking partitions. Then the discipline check over the whole of `web`, and the architecture and glossary brought level with what was built.

### Acceptance criteria

- [ ] A workspace summary is a derived shape over registry entries, and computes nothing from a trace
- [ ] `RunRegistryEntry` carries what a rollup needs, so no total walks a partition
- [ ] The whole of `web` performs no arithmetic over what it serves, asserted over the package
- [ ] Every number the interface displays is traceable to the shape that produced it, asserted on a real recorded study
- [ ] `FINAL_ARCH.md` §5.13 and §5.14, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
- [ ] Any defect the interface exposes is fixed with a test that fails on the old code
