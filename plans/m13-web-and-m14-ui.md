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

- [x] `trace_summary(view)` returns a frozen model carrying belief histories, edges, grouped verbatims, event counts per kind and costs per role, each from the shape that owns it
- [x] Every quantity in it matches the same quantity recomputed from raw events on a fixture trace
- [x] It reaches storage only through the five shapes — no path, no frame, no second way in, asserted over the module
- [x] A study writes it into the run directory beside the other artefacts, and a paused run writes what it has
- [x] The interface renders a real recorded study's trace, beliefs and verbatims with no mock state
- [x] Two summaries of one trace are identical, so a diff means a difference in the record

---

## Phase 2: The `web` module

**User stories**: 21, 22

### What to build

The server, and the discipline that keeps it thin. `simcore/web/` serves the five shapes, `TraceSummary`, the digest, findings, clusters, anomalies and the report — live, from a running or finished study, with the registry deciding which backend a view opens. The interface's own API routes become proxies to it rather than readers of disk, so there is one path to every number.

### Acceptance criteria

- [x] Each of the five shapes has an endpoint returning frozen models, with a typed filter rather than free keyword arguments
- [x] A live run and a finished run answer identically through the same endpoints
- [x] The package performs no arithmetic over what it serves, asserted over the module in the shape `report`'s discipline test already uses
- [x] No endpoint returns a filesystem path, a cursor or a frame
- [x] The API is exercised in-process against temporary directories with the fake backend, and reaches no network
- [x] The server ships as the `simcore[web]` extra, and the core's runtime dependencies are unchanged
- [x] The interface reads every engine number through the API, and its direct filesystem reads are gone

---

## Phase 3: Trust, stated once

**User stories**: 16, 18, 19, 20

### What to build

The page the mockups call calibration, told honestly. The run's `TrustStatement` appears once and is `UNCALIBRATED`; the ladder shows what would earn the next rung — a `CalibrationRef` pinning a benchmark report and a human study by hash, both clearing the floors — and nothing in the interface can adjust it. Where a digest could not measure a quantity, the reason it carries is shown in the place the number would have been.

### Acceptance criteria

- [x] Every study view states the run's calibration exactly once, and no finding carries one
- [x] The trust page shows the ladder and what a level above `UNCALIBRATED` requires, without displaying an accuracy number the engine has not earned
- [x] A quantity reported as not measurable renders its reason where the number would have appeared
- [x] A run forced across engine versions or past moved inputs says so
- [x] Nothing in the interface writes or overrides a trust level
- [x] A finding's own confidence renders beside it and is never presented as the engine's calibration

---

## Phase 4: Launching a fake study, and watching it

**User stories**: 7, 8, 9, 10, 11

### What to build

A study started from the interface, running as a subprocess, watched while it works. The runner publishes its progress — status, recorded cost, ticks closed — to the registry entry as it goes, so spend is something a person can act on rather than read afterwards. Cancelling ends the process and loses at most the tick in flight; resuming is a re-run with the same id.

The first study anyone runs is `--fake`: no key, no corpus, no network, a real report in minutes, marked as fake wherever it appears.

### Acceptance criteria

- [x] A study starts from the interface and its run id, artefacts and registry entry agree
- [x] Recorded cost and ticks closed are readable while the run is going, not only when it ends
- [x] The interface shows ticks closing, turns landing, spend against the budget and the rung in force
- [x] Cancelling stops the run, loses at most the tick in flight, and the trace stays valid
- [x] A cancelled run resumes and completes, skipping the worlds that reached their horizon
- [x] A run outlives a restart of the server, and orphans are swept into a truthful status on start
- [x] A fake run needs no key, no corpus and no network, and is marked as fake in every view of it

---

## Phase 5: The population page

**User stories**: 6, 15

### What to build

Who was drawn and whether the draw was sound. The gate report's per-attribute results with their statistics and thresholds, requested against achieved audience mix, the source mix and attribute origins, the synthesized share and the completion policy that allowed it, and a sample of real personas. Audiences appear as audiences; communities, when the graph forms any, appear separately.

### Acceptance criteria

- [x] Every gate result shows its statistic, its threshold and its verdict, so a reader can recompute the call
- [x] Requested and achieved audience mix are shown together, and a relaxation that was applied is visible
- [x] The synthesized share and which domains may be completed are stated
- [x] Sample personas render from the population's own records, with each attribute's origin
- [x] Audiences and communities are presented as different things, and a population that formed no communities says so with the reason
- [x] A failed gate is readable, since a study that never ran is the case the page most needs to explain

---

## Phase 6: The ontology builder

**User stories**: 1, 2, 3, 4, 5

### What to build

The screen that decides what can be studied. The codebook's attributes are browsable and searchable with their real value sets; a draft is assembled from them; every name is checked against the codebook as it is typed. Ordinal scales are built from the codebook's own labels in their own order. Saving produces a new version rather than changing a file, and a draft that has never been validated against a present codebook cannot become one.

The conditioning set is presented as what it is: the field that decides whether personas differ from one another at all.

### Acceptance criteria

- [x] The codebook's attributes are searchable with their declared value sets, from the corpus rather than from a copy
- [x] An attribute the corpus does not carry is refused as it is entered, naming what the codebook does have that resembles it
- [x] An ordinal scale is built from the codebook's own labels, in the order the codebook states them
- [x] Saving an edited ontology creates a new version and leaves every existing version untouched
- [x] A study names the version it ran on, and that version resolves for as long as the study exists
- [x] A draft may be authored without the corpus present and cannot be pinned until it validates against one
- [x] The conditioning set is explained where it is chosen, with what it costs to leave an attribute out

---

## Phase 7: Intake, and a real study

**User stories**: 6, 11

### What to build

The brief and the scenario, configured in the engine's own words: product, claims with their sources and evidence, price, competitors, audiences and their shares, assumptions. Then the study itself — variants, environment, horizon and tick unit, elicited task, replicate seeds, budget — and the pins a real run needs. The endpoint is reported as configured or not; no key is ever asked for in a browser.

### Acceptance criteria

- [x] A brief is authored and validated against the engine's own contracts before a run can start
- [x] Every term the form uses is the glossary's, with its definition available where it is set
- [x] The assumption ledger is assembled from what the brief states and what it leaves unstated
- [x] A study states what its personas are asked, and a purchase-intent study names the anchor version that scores it
- [x] The interface reports whether an endpoint is configured and never accepts or displays a key
- [x] A real study runs from the interface end to end and writes the same artefacts the command line does

---

## Phase 8: One persona's whole history

**User stories**: 12, 13, 14

### What to build

The unit the engine actually records. One persona's timeline — what it was shown, what it said, how its beliefs moved tick by tick, which memories it wrote, who it heard from and who heard from it. And the prompt behind any turn, rebuilt from the recorded parts and checked against the hash the turn carries before it is shown.

### Acceptance criteria

- [x] A persona's events, beliefs and verbatims are shown in one timeline, and none of another persona's appear in it
- [x] Belief movement is shown per dimension and per claim, before and after, from the recorded snapshots and turns
- [x] The influence neighbourhood is drawn from the recorded edges, naming the channel and how often
- [x] A turn's prompt is reconstructed from the record and displayed only when it matches the turn's recorded hash
- [x] A prompt that cannot be reconstructed says so and why, rather than showing an approximation
- [x] Nothing in the interface stores a prompt, asserted over what it persists

---

## Phase 9: The atlas

**User stories**: 15, 17

### What to build

A study's shape rather than one persona's. Adoption against polarization across a scenario's worlds; per-tick trajectories for audiences and, separately, for communities; the replicate spread that says whether an ordering survives; and two finding kinds the engine declares but has never authored — `ranking` over a scenario's replicates and `risk` from the anomalies already detected.

### Acceptance criteria

- [x] Trajectories per audience and per community per tick are a derived shape in `analysis`, matching the same quantities recomputed from raw events
- [x] `ranking` findings are authored by extraction from a scenario's digests, carrying the spread that says whether the order survives its replicates
- [x] `risk` findings are authored from recorded anomalies, each with its evidence and its disconfirming test
- [x] A cell whose worlds ran at different degradation rungs is marked rather than silently compared
- [x] A quantity no world measured is stated as unmeasured with its reason, never drawn as zero
- [x] Nothing generated appears as a finding, asserted over what the atlas renders

---

## Phase 10: The workspace, and reconciliation

**User stories**: 21, 22

### What to build

The first screen, and the documents in step. A workspace summary over registry entries — studies run, spend against budget, personas simulated, reports written — derived in `analysis` and read from entries rather than by walking partitions. Then the discipline check over the whole of `web`, and the architecture and glossary brought level with what was built.

### Acceptance criteria

- [x] A workspace summary is a derived shape over registry entries, and computes nothing from a trace
- [x] `RunRegistryEntry` carries what a rollup needs, so no total walks a partition
- [x] The whole of `web` performs no arithmetic over what it serves, asserted over the package
- [x] Every number the interface displays is traceable to the shape that produced it, asserted on a real recorded study
- [x] `FINAL_ARCH.md` §5.13 and §5.14, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
- [x] Any defect the interface exposes is fixed with a test that fails on the old code

---

## Review: what the ticked criteria hid

Every box above was ticked and 1,798 tests passed. A review that exercised the running stack found these; each is fixed, with a test that fails on the old code (`tests/boundary/web/test_restart.py`, `test_hardening.py`, `test_interface.py`, `test_suggest.py`, `frontend/test/`).

- **Phase 2 — the interface still read the disk.** Every route kept a second implementation behind `SIMCORE_WEB_URL`-unset: its own launcher, cancel marker, run-id minter (16 characters where the engine mints 26), a Python-in-TypeScript events reader, a hard-coded `runs/run-ssrv2` on the calibration page. Removed: the interface is proxy-only, asserted over its source.
- **Phase 2 — refusals lost their reason.** `engineFetch`/`api` threw `"<path>: 422"`, and every proxy turned it into a bare `502`, so "an attribute the corpus does not carry, naming what resembles it" never reached a screen. The status and the engine's sentence now travel end to end; every server refusal is one `{detail}` shape.
- **Phase 2 — `/api/ontologies` changed shape at the proxy**, so the intake page could not load its own category list.
- **Phase 4 — a run did not outlive a server restart.** The sweep at start marked any study the new server had no handle for `partial` while its process was alive. Launches now record their pid; survivors are adopted (checked against the run id in the process's argv, so a recycled pid is not mistaken for it) and only dead runs are swept. A study that died mid-session now reads partial rather than running forever, a live process is not reported finished, and a study that dies before it records anything says why (`launch.log`) instead of returning 404.
- **Phase 4 — the Run page crashed on every study** (`pins.safety` is `null`). Found only by rendering in a browser.
- **Phase 5 — a failed gate was unreadable.** `run-gate200` failed its gate and wrote no manifest; the page rendered its "never ran" callout and none of the gate statistics it points at, because every panel required a manifest. Reading a gate-only run also 500ed on `/summary` and *created* a `trace/registry.db` inside it (`TraceStore` mkdirs on open); a read no longer writes.
- **Phase 6 — the "resembles" suggestions resembled nothing** (`income` → `ind_e_commerce`, `age` → nothing). Suggestions now rank by shared words in the codebook's compound names.
- **Phase 7 — the intake form changed the study it loaded.** It dropped competitors, rewrote every assumption as `user_asserted`, truncated a list filter to its first value, turned a range filter into `[object Object]`, flattened a nested audience filter into a sibling key, and broke on a description containing a line break. It could only launch `fake: true`, ignored the tick unit, and could not select an ontology version. Fixed on js-yaml under the YAML 1.1 schema; a real study now pins its models against a configured endpoint, and never asks for a key.
- **Phase 7 — the request was unvalidated.** Run ids climbed out of the runs root; `n=0`, a negative budget or unknown keys started a process that died silently. `StudyRequest` is a closed model; a run id must be one the trace accepts.
- **Phase 9/10 — evidence resolved one world at a time**, and a world's `resolve` refuses a sibling's ids, so a multi-replicate study lost every citation. `/api/runs/{id}/resolve` resolves across the run.
- **Phase 10 — the shell wrapped every page in invented state**: three made-up studies, "Engine v0.4.1", "$412 / $1,500", "Team plan", an avatar — against ADR 0043 and "no mock state". It now shows the engine's own.
- **Phase 10 — the discipline test was too lax.** `web` computed a `max` and counted in `_live_progress`; the test forbade only `sum` and a few statistics names. Progress is now `analysis.world_progress`, and the test forbids what `report`'s does. `reports_written` counted completed runs, not reports.
- **Trust page** hard-coded the 0.80 floors; `/api/trust` serves the schema's own.
- **The suite's "surface" tests asserted that strings exist in the TSX** and so could not fail. They stay for the markers they check; the checks that matter now start the stack and render the pages.

Not changed, and worth a decision: the recorded study `run-5t329fy3ct04k2tht5714ahms8` reports `$0.00` recorded cost across 1,804 priced calls (607,080 in / 173,881 out tokens at $0.035 / $0.14 per million pin prices, roughly $0.05) — the interface shows what the record says; whether cost accounting recorded a price-table cost there is an engine question, not an interface one.

## Amendment, 2026-09-20: the real study from the interface

The Phase 7 box "a real study runs from the interface end to end" was ticked while it was untrue on any machine that does not hold all ten corpus shards. The launch route passed the model pins but not `--shards`, `--sources` or the prices, so a real launch demanded every shard and died on the first missing one; the gate route could only draw the fake corpus; the intake page hard-coded the gate's seed and defaulted to a scale (`purchase_intent` v1) that fails its own check. Found by trying to run a real study through the interface.

Fixed: `StudyRequest` and `GateRequest` carry the corpus choices (shards, sources, population seed), the prices and the pins; `/api/corpus` and `/api/anchors` tell the form what is cached and which scale versions passed; the request is built by `frontend/lib/study.ts` and unit-tested (`frontend/test/study.test.mts`); server side in `tests/boundary/web/test_launch_any_study.py`. A community-detection defect the new seeds exposed (`OverflowError` for a `spawn` seed above 2^63) is fixed in `simcore/population/_communities.py` without changing any partition a fitting seed already produced.

Still not expressible from the interface: sweeps, `--force` resume, cache path, corpus coverage in the ontology builder. The run page shows the first world's id for a seed whose world has not finished (`frontend/app/run/page.tsx`).

Two engine defects surfaced while the study ran, both of the kind "a status that says something untrue":

* `finalize_world` marked the whole run `completed` as soon as *one* world was written to parquet. A study with replicate seeds reads `completed` from the end of its first world until the runner writes the true status; the Overview and `/api/runs/{id}` said so while the second world was running. Finalizing a world no longer decides the run's status; the runner's closing update does (`tests/boundary/trace/test_registry.py`).
* `progress.json` was last written by a tick, so a finished CLI study kept saying `running`. The CLI now writes the closing status (`tests/boundary/web/test_lifecycle.py`).

Verified end to end through the interface (headless Chrome, the real corpus, the real gateway): the Intake page picked the education brief, pinned Nova Micro and Titan v2, chose shards 0004/0005 and only the stackoverflow/gss sources, and launched; the engine ran the argv the form built, the gate passed, and the run completed with all artefacts (`runs/run-0dvscy7mf2b2ft3s2edx6c7ady`, `runs/run-1j2kbd0g9ypvvwnvp9r8e8tsxt`). Both are 30-persona runs, and most of their calls were served from the response cache (cost recorded as `cache`, $0.00 and $0.00016), so they prove the launch path and not the models' behaviour.
