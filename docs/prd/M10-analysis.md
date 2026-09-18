# PRD — M10 `analysis`: deriving meaning from a trace

## Problem Statement

The engine records everything and interprets nothing. A real study now produces a few thousand events —
turns, verbatims, belief snapshots, word-of-mouth deliveries, costs — and every question a user would ask of
it is answered today by writing a throwaway script. That is not a gap in convenience; it is the arrangement
that the architecture says caused the previous design's worst duplication, where objection clusters were
computed in the sweep's digest builder and again in the report builder from the same verbatims, with no
stated owner and a guarantee of divergence.

The engine's own first evaluation demonstrated the same failure in miniature. Its report was a dictionary
assembled beside the trace rather than derived from it, so the facts that mattered — word of mouth firing 113
times, every turn moving a belief, turns splitting across two channels — stayed in the trace and never reached
the report, while a number the report did carry overstated what it measured.

Three risks are specific to this module.

A derived number that cannot be recomputed from the record is an opinion. Everything here must be arithmetic a
reader can repeat from the trace, which rules out a judge model anywhere in the path.

A finding that cannot be traced back is worse than no finding. `Finding` already refuses construction without
evidence ids, and this module is where that refusal has to bite — at authorship, where the evidence can still
be checked, not at rendering.

And a run that measured something real can be made to look like it measured nothing. No anchor version passes
its check (ADR 0029), so no trace carries purchase intent; a module that refuses to digest such a run would
declare the engine's only working studies empty.

## Solution

Two calls, both pure functions of a trace view.

`digest(view) -> OutcomeDigest` describes one world (ADR 0039), naming the scenario it belongs to. It carries
response masses where the run scored them and reports adoption, polarization and audience divergence as `None`
where it could not, recording how many turns went unscored and why (ADR 0038). Beside those it reports what
every run produces: the action mix, belief movement and word-of-mouth reach. What personas said is grouped
beside the digest rather than inside it, as `ObjectionCluster`s (ADR 0041), since a cluster is one scenario's
verbatims and a digest is one world's.

`spread(digests) -> ScenarioSummary` aggregates a scenario's worlds, carrying each seed's values beside their
spread, because that spread is the yardstick every anomaly threshold is measured against.

`findings(views, digests) -> list[Finding]` authors findings by deterministic extraction — objection clusters
from verbatim embeddings (ADR 0041), belief-delta chains from belief histories, word-of-mouth paths from
edges — each constructed with its evidence trace ids already resolved against the view it came from, and each
carrying the disconfirming test that would show it wrong.

Anomalies are rules over recorded numbers (ADR 0040): herding and backlash read belief movement against the
replicate spread, and flop reports as not measurable until adoption exists.

The trust guard runs here. The run's `TrustStatement` is `UNCALIBRATED`; anything higher needs a
`CalibrationRef` that nothing in this repository can produce, so the engine cannot overclaim by construction.

## User Stories

**The digest**

1. As an analyst, I want one digest per world, naming its scenario, so a sweep's cells stay distinguishable.
2. As an analyst, I want a digest of a run that scored no intent, reporting what it did measure, so the
   engine's current studies are readable at all.
3. As a researcher, I want adoption, polarization and divergence reported as not measurable when they are,
   with the reason, so absence is never read as zero.
4. As an analyst, I want response masses per audience and per community, with shares and sizes, so adoption and
   polarization can never contradict the masses they come from.
5. As an analyst, I want the action mix, belief movement and word-of-mouth reach in every digest, so a run
   without ratings still reports what happened.
6. As a researcher, I want a scenario's worlds aggregated with their spread, so a heatmap cell shows how far
   its seeds disagreed.
7. As a researcher, I want comparing digests with different tick units refused, so an axis never mixes hours
   with weeks.

**Findings**

8. As an analyst, I want objection clusters from verbatim embeddings, reproducible across two runs over one
   trace, so a finding can be cited.
9. As an analyst, I want each cluster labelled by the verbatim nearest its centre, quoted, so no label claims
   more than a persona said.
10. As a researcher, I want every finding to resolve to trace ids at authorship, so a finding whose evidence
    does not exist fails where it was written.
11. As a researcher, I want every finding to carry a disconfirming test, so a reader knows what would falsify
    it.
12. As an analyst, I want belief-delta chains and word-of-mouth paths authored from the record, so the
    engine's social claims rest on recorded deliveries rather than on inference.
13. As a maintainer, I want findings authored deterministically, so two runs of analysis over one trace produce
    the same set.

**Anomalies and trust**

14. As an analyst, I want herding detected as belief movement beyond twice the replicate spread on a trailing
    window, so attention converging is visible without ratings.
15. As an analyst, I want backlash detected as a split in the sign of belief moves past a threshold.
16. As a researcher, I want flop reported as not measurable until adoption exists, rather than as absent.
17. As a maintainer, I want no model call anywhere in this module except embedding verbatims, so every number
    is recomputable from the trace.
18. As a researcher, I want the run's calibration stated once as a trust statement, and a level above
    `UNCALIBRATED` refused without a calibration reference.

## Implementation Decisions

**Interfaces.** `digest(view) -> OutcomeDigest`, `spread(digests) -> ScenarioSummary`,
`findings(views, digests) -> tuple[Finding, ...]`. All read through `TraceView`'s five shapes and nothing else.

**Contract amendments.** `OutcomeDigest` gains optional intent and the measures every run produces;
`ScenarioSummary` is new; `SCHEMA_VERSION` stays 1.0.0 and unreleased, so identities re-pin.

**Clustering.** Cosine similarity over embeddings from the run's pinned embedding model, a recorded threshold,
deterministic tie-breaking, medoid labels. No k-means, no generated summaries.

**Anomaly thresholds.** Configuration with documented defaults, recorded wherever an anomaly is reported.

**Embedding is the one model call**, and it is the same pinned model the run used, so a digest cannot be
computed in a different embedding space from the study it describes.

**Test posture.** Boundary tests through the three calls against fixture traces with planted patterns, plus
the real trace shape the first study produced. `FakeEmbed` for clustering; the suite reaches no network.

## Testing Decisions

- A fixture trace with a planted herding pattern produces exactly one herding anomaly, at the right tick.
- A planted sign split produces backlash; a quiet trace produces neither.
- Identical verbatims cluster identically across two runs; cluster labels are verbatims that appear in the trace.
- Constructing a finding without evidence raises; every finding from a fixture trace resolves against it.
- A trust level above `UNCALIBRATED` without a calibration reference raises.
- A digest of a trace with no intent reports adoption as not measurable, with the count of unscored turns.
- A digest's adoption never contradicts its masses, and digests with differing tick units refuse comparison.
- A scenario's spread over seeds that disagree is non-zero; over one seed it is zero and says so.
- No module path calls a chat model, asserted over the package.

## Out of Scope

Rendering (`report`, module 11) and entrypoints (`cli`, module 12). Writing anything to the trace — this
module only reads. Deciding what a study should have measured; it reports what the record holds. The
calibration benchmark itself, which is deferred (§12) and which nothing here can produce.

## Further Notes

The first real study's report is the worked example of what this module exists to replace: `run_study.py`
gathered numbers beside the trace, and the evaluation's own README had to state facts the report did not
carry. When this module lands, that evaluation's numbers should come from a digest.
