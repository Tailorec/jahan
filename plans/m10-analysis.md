# Plan: M10 `analysis` — deriving meaning from a trace

> Source PRD: `docs/prd/M10-analysis.md`
> Binding decisions: ADR 0038 (a digest reports what a run measured), ADR 0039 (a digest is one world's; a scenario carries its spread), ADR 0040 (anomalies are rules over what was measured), ADR 0041 (objection clusters are deterministic and quoted), ADR 0042 (a report is derived from the record), ADR 0034 (one trace view, closed read shapes), ADR 0029 (anchors are a study input), ADR 0032 (an unscorable reaction keeps its verbatim), ADR 0008 (trust stays uncalibrated), ADR 0007 (adoption is share-weighted). `CONTEXT.md` (Digest, Unmeasured, Replicate Spread, Objection Cluster, Anomaly, Finding, Disconfirming Test, Adoption, Polarization, Trust Level). Where `FINAL_ARCH.md` §5.10 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Everything is derived, nothing is judged** — every number a reader sees can be recomputed from the trace. The only model call in the module is embedding verbatims, through the run's own pinned embedding model, so a digest is never computed in a different embedding space from the study it describes.
- **Read through the five shapes** — `events`, `beliefs`, `edges`, `verbatims`, `resolve`, and nothing else. No path to storage, no second way in.
- **A digest is one world's** — it names its scenario; a scenario's worlds are aggregated separately, carrying each seed's value beside the spread the anomaly thresholds depend on.
- **Unmeasured is a value** — adoption, polarization and divergence are `None` with a recorded reason when a run scored no intent, never zero and never omitted.
- **Findings resolve at authorship** — a finding is constructed with its evidence ids already resolved against the view, so one whose evidence does not exist fails where it was written.
- **Deterministic by construction** — clustering, ordering and tie-breaking derive from the trace and recorded parameters; two runs over one trace produce one answer.
- **The trust guard lives here** — one statement per run, and a level above `UNCALIBRATED` is refused without a calibration reference nothing in this repository can produce.
- **Contract amendments come first** — `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities are re-pinned rather than migrated.
- **Test posture** — boundary tests through `digest`, `spread` and `findings` over fixture traces with planted patterns, plus a real recorded trace in the last phase. `FakeEmbed` for clustering; the suite reaches no network.

---

## Phase 1: The contracts

**User stories**: 2, 3, 4

> This phase lands on `master` before the module is built, since `report` and `cli` read these shapes too.

### What to build

The shapes a digest needs once intent is optional. `OutcomeDigest` carries response masses where a run scored them and reports adoption, polarization and audience divergence as not measurable where it did not, with the count of unscored turns and the reason. It gains the measures every run produces — the action mix, belief movement, word-of-mouth reach — so a run without ratings still reports what happened. `ScenarioSummary` is new: a scenario's worlds, per seed, with their spread.

### Acceptance criteria

- [ ] A digest validates with no response masses, and its adoption, polarization and divergence are `None`
- [ ] A digest with masses computes adoption from them as before, and a stated value contradicting the masses is refused
- [ ] A digest records how many turns went unscored and why, and cannot report unmeasured adoption without a reason
- [ ] A digest carries the action mix, belief movement and word-of-mouth reach of the world it describes
- [ ] `ScenarioSummary` holds one entry per seed and the spread across them, and refuses worlds from different scenarios
- [ ] Pinned identities are re-pinned, with the change recorded in the commit that moves them

---

## Phase 2: A digest of one world

**User stories**: 1, 2, 3, 4, 5

### What to build

`digest(view) -> OutcomeDigest` over one world. It reads turns for the action mix and belief movement, belief histories for where personas ended, edges for word-of-mouth reach, and intent where any exists — reporting masses per audience and per community with their shares and sizes when it does, and the unmeasured reason when it does not.

### Acceptance criteria

- [ ] A digest of a real recorded world names its scenario and its tick unit
- [ ] A world with scored intent reports masses per audience and per community, with shares and sizes
- [ ] A world with no scored intent reports adoption as not measurable, naming the count of unscored turns
- [ ] The action mix, belief movement and word-of-mouth reach match the same quantities recomputed from raw events
- [ ] A persona counted in an audience mass is counted in exactly one audience
- [ ] Digesting the same view twice produces an identical digest

---

## Phase 3: The scenario's spread

**User stories**: 6, 7

### What to build

`spread(digests) -> ScenarioSummary`: a scenario's worlds gathered, each seed's values kept, and the spread between them computed — the yardstick every anomaly threshold is measured against. Comparing digests whose tick units differ is refused.

### Acceptance criteria

- [ ] A scenario's digests aggregate into one summary carrying each seed's values
- [ ] The spread is computed between worlds, never within one, asserted against a hand-worked fixture
- [ ] One seed yields a spread of zero, reported as such rather than omitted
- [ ] Digests from different scenarios are refused
- [ ] Digests with differing tick units are refused
- [ ] A cell whose worlds ran at different degradation rungs is marked (ADR 0037)

---

## Phase 4: Objection clusters

**User stories**: 8, 9

### What to build

What personas objected to, grouped. Verbatims are embedded once through the run's pinned model and grouped by cosine similarity at a recorded threshold, with ties broken from a derived seed. Each cluster is labelled by its medoid — the verbatim nearest the centre, quoted as written.

### Acceptance criteria

- [ ] Clustering the same verbatims twice produces identical clusters, in identical order
- [ ] A cluster's label is a verbatim that appears in the trace, never generated text
- [ ] The threshold is a recorded parameter, reported wherever clusters are
- [ ] Verbatims saying the same thing in different words group together, on a fixture built for it
- [ ] Verbatims embedded once per run, never re-embedded per cluster
- [ ] A run with no verbatims produces no clusters and no error

---

## Phase 5: Findings

**User stories**: 10, 11, 12, 13

### What to build

Findings authored by extraction, not generation: objection clusters become objection findings, belief histories become belief-shift findings, edges become word-of-mouth path findings. Each is constructed with its evidence ids resolved against the view it came from, and each carries the disconfirming test that would show it wrong.

### Acceptance criteria

- [ ] Every finding resolves its evidence ids against the view at authorship, and an unresolvable id raises there
- [ ] A finding cannot be constructed without evidence or without a disconfirming test
- [ ] Objection, belief-shift and word-of-mouth findings are authored from a fixture trace holding each
- [ ] Two runs of `findings` over one trace produce the same findings in the same order
- [ ] No finding states calibration; the run's trust statement carries it once
- [ ] A finding's confidence reflects the evidence behind it, and is independent of the engine's calibration

---

## Phase 6: Anomalies

**User stories**: 14, 15, 16

### What to build

Three rules over recorded numbers. Herding: belief movement beyond twice the replicate spread on a trailing window. Backlash: a split in the sign of belief moves past a threshold. Flop: needs adoption, so it reports as not measurable until intent exists. Thresholds are configuration with documented defaults, recorded wherever an anomaly is reported.

### Acceptance criteria

- [ ] A fixture trace with a planted herding pattern produces exactly one herding anomaly, at the right tick
- [ ] A planted sign split produces backlash; a quiet trace produces neither anomaly
- [ ] Flop reports as not measurable with its reason, on any run without adoption
- [ ] Thresholds are configuration, and the applied values travel with the anomaly
- [ ] Detection is arithmetic over recorded numbers, recomputable by hand on the fixture
- [ ] The replicate spread, not within-world variation, is what a threshold is measured against

---

## Phase 7: The trust guard

**User stories**: 17, 18

### What to build

The refusal that keeps the engine from overclaiming. A run's `TrustStatement` is stated once and is `UNCALIBRATED`; `CATEGORY_BENCHMARKED` or above requires a `CalibrationRef` pinning a benchmark and human study by hash, which nothing in this repository can produce. And the module's own discipline: no chat model anywhere in it.

### Acceptance criteria

- [ ] A trust level above `UNCALIBRATED` without a calibration reference raises
- [ ] A run's calibration is stated once and no finding carries one
- [ ] No path in the package calls a chat model, asserted over the package
- [ ] The only model call is embedding, through the run's pinned embedding model
- [ ] A digest or finding built from a trace whose embedding model differs from the run's pin is refused

---

## Phase 8: Reconciliation

**User stories**: —

### What to build

The module against a real trace, and the documents in step. A recorded study — regenerated, since the first one's trace is gone — is digested end to end, and the evaluation's numbers are recomputed as a digest rather than gathered beside it. Architecture, salvage inventory and glossary are checked against what was built.

### Acceptance criteria

- [ ] A real recorded trace digests without error, and its numbers match the first study's recorded report where both measured the same thing
- [ ] The evaluation's figures are produced by `digest`, not by a script gathering them separately
- [ ] `FINAL_ARCH.md` §5.10, `SALVAGE.md` and `CONTEXT.md` describe what was built
- [ ] Any defect the real trace exposes is fixed with a test that fails on the old code
- [ ] The regenerated trace is kept somewhere durable, not in a temporary directory
