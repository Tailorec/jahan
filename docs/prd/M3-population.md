# PRD — M3 `population`: who is in the study

## Problem Statement

The engine can read a brief and has contracts for everyone a study contains, but it cannot produce a single persona. `Population`, `Persona`, `GateReport`, `SocialGraph` and `Community` are defined, validated and pinned; nothing constructs them. Every downstream module — agent, world, runner, analysis — is blocked on a population it cannot obtain.

The risk here is not that the module is hard to write. It is that the module decides, quietly, what a study measured. Four choices inside it determine whether a finding means anything: who was eligible to be sampled, what happened when too few of them existed, which fields a model was allowed to invent, and how the social structure formed. Get any of them wrong and the engine still produces confident numbers — a population that looks representative because it was silently topped up, a polarization figure that is an artifact of how aggressively ties were rewired, an audience that quietly excluded half the people its name implies.

This module is also where the engine's second contract lives: dataset facts and model-invented facts never mix silently. The test that proves it — no demographic or psychographic field is ever synthesized — is only expressible here.

## Solution

One module answering one question, behind two functions.

`assess(pack, n, population_seed, *, coreset) -> GateReport` resolves who is eligible, draws the sample, and gates its distributions. It calls no model and costs nothing, so a user can ask "can this study be sampled at all, and is the sample sound?" before spending anything.

`build(...) -> BuiltPopulation` does that and continues: projects each row into a persona, fills sparse fields through a constrained model call, applies patches, generates the social graph, detects communities, and returns the validated `Population` alongside the embedding array when embeddings are enabled.

Around those, four commitments: eligibility is decided before sampling and never traded away for a quota; a shortfall climbs a recorded ladder rather than being dropped or invented over; a model may only choose values the corpus already contains; and the social structure is built from attributes that can explain themselves rather than from an opaque vector.

## User Stories

**Choosing who is studied**

1. As a study author, I want to declare audiences with shares that sum to one, so the population reflects the market I mean rather than whatever the data happens to hold.
2. As a study author, I want ranges and one-of sets in audience filters, so "trains at least weekly" and "18–34" are expressible rather than collapsed to a single band.
3. As a study author, I want an audience that matches nothing refused with its counts, so an unexpressible audience fails while I am still authoring.
4. As a study author, I want a thin audience widened along a fixed ladder, so a shortfall never silently becomes a different study.
5. As an analyst, I want every relaxation recorded with its rung and its before-and-after counts, so I can see what was actually sampled.
6. As an analyst, I want the requested mix recorded beside the achieved mix, so a shortfall is legible without rerunning anything.

**Grounding**

7. As a methodologist, I want rows lacking any conditioning attribute excluded before sampling, so the population does not skew toward the dataset's complete synthetic rows.
8. As a maintainer, I want the conditioning set never loosened to fill a quota, so the invariant the module rests on cannot be traded for coverage.
9. As an analyst, I want the population's source mix reported, so any skew the conditioning filter induced is visible.
10. As a methodologist, I want a completed field to be one of the values the corpus already contains, so completion cannot introduce vocabulary the gates and filters do not know.
11. As a maintainer, I want no demographic or psychographic field ever synthesized, so grounded and invented facts never mix.
12. As an auditor, I want the manifest to record which model completed fields, under which template, and what share of fields was synthesized, so the provenance of invented data survives without the personas.

**Judging the sample**

13. As a methodologist, I want categorical marginals tested against category targets, and ordinal attributes tested on their own band scale.
14. As a maintainer, I want gates to run on grounded attributes only, so completion cannot be judged against the distribution it was chosen to match.
15. As a maintainer, I want any failing gate to reject the population, so a bad sample cannot reach a run.
16. As an analyst, I want the graph judged too — degree shape, clustering, connectivity — and its results carried in the same report.
17. As a methodologist, I want the measured attribute assortativity reported, so how much attributes shaped the structure is a number rather than an assumption.

**Structure**

18. As an engine developer, I want ties generated from clustering, hubs and attribute homophily, so diffusion behaves like a social network rather than a random graph.
19. As an analyst, I want a tie's strength explainable from the attributes that produced it.
20. As a maintainer, I want tie strengths quantised before they become edges, so a graph's identity is its structure and not the floating-point path that produced it.
21. As an analyst, I want communities discovered from the graph rather than declared, so a split that cuts across declared audiences is findable.
22. As an analyst, I want a population that forms no communities reported as not measurable for polarization, never as zero.

**Using the module**

23. As a CLI developer, I want a gate report without any model call, so checking a cohort is fast and free.
24. As an engine developer, I want the same seed to produce an identical population under a deterministic port, so a study can be reproduced.
25. As an engine developer, I want the embedding array returned beside the population rather than inside it, so the contract stays pure and hashable.
26. As a maintainer, I want the quickstart to build 2,000 personas in under five seconds with no network and no dataset.

## Implementation Decisions

**The interface.** Two public functions, `assess` and `build`, and nothing else. `build` returns a `BuiltPopulation` — the validated `Population` plus a `float32` array whose rows are indexed by `EmbeddingRef.index` — because `schemas` is a leaf package that can never hold numpy. `PersonaPatchSource` stays in the signature with a no-op default: fifteen lines now against a breaking signature change later, and it is the seam through which externally derived corrections would arrive.

**The corpus seam.** `CoresetSource` yields decoded rows, not packed bytes: `matching(equals, present)` for index-only resolution, `rows(ids)` for fetching, `values(attribute)` for the codebook's value set. The packed format, the mapping from ontology vocabulary to dataset codes, and the value sets are all the adapter's knowledge — dataset facts belong beside the thing that speaks to the dataset, and a synthetic source that had to pack nibbles purely so the module could unpack them would be exercising a codec no real path uses. `matching`'s signature carries ADR 0002: you cannot ask for rows without saying which attributes must be populated.

**Audiences.** The brief declares audiences with shares, all-or-nothing, summing to one — the study author chooses who is studied and in what proportion, and the brief precedes the population, which resolves the ordering problem that scenario weights could not. Filters become predicates: exact value, one-of set, or range over an ordinal attribute's declared bands. Scenario weights keep their separate job of reweighting at analysis time and default to the brief's shares.

**The relaxation ladder.** A quota that cannot be filled climbs a fixed ladder, each rung recorded as a `Relaxation`: widen an ordinal predicate by one band, nearest first; then drop the least relevant non-conditioning filter, using the ontology's own `relevance_order`; then accept the shortfall so the achieved mix tells the truth; and fail only when an audience matches nothing at all. The conditioning set is never a rung — trading it for coverage would undo ADR 0002. A relaxation caveats a population; it does not fail it.

**Gates.** Categorical marginals by chi-squared, ordinal attributes by KS similarity on their band scale, and the graph by degree shape, clustering and connectivity — one report, one computed verdict, any failure rejecting the population. Gates read grounded attributes only. `scipy` supplies the chi-squared survival function and the power-law reference; hand-rolling special functions whose failure mode is silent tail error is not a saving in the part of the engine that exists to catch silent error.

**Projection and completion.** The ontology's relevance order selects fields, the conditioning set lands in `Persona.conditioning` and the rest in `Persona.attributes`, and every projected field states its origin. Completion is a constrained choice from the corpus's own value set — classification, not generation — batched per audience, retried once, and left absent rather than accepting an off-list answer. A persona missing a non-conditioning attribute is valid; an invented vocabulary is not.

**Structure.** A Watts–Strogatz ring supplies clustering and preferential attachment supplies a hub tail; a homophily pass then rewires a fraction of edges toward attribute-similar partners, with similarity computed in attribute space and weighted by relevance order. Embeddings become an optional secondary term rather than the primary signal: attribute homophily explains itself — "tied because both train three times a week" — where cosine over a mean-pooled blur cannot, and dropping it from the default path removes an embedding call per persona and a port from the common case. Homophily strength, ring degree and hub attachment are study parameters, and the structural gate floors, community thresholds and distribution gate thresholds are quality thresholds: all are `PopulationParameters` a user may tune, defaulting to the engine's own values, recorded in the manifest and never read from the environment. The environment configures how a run executes, never what it measured, and operational constants that never change a result stay internal. Similarity is computed over sampled candidates, not all pairs, because all-pairs is 2.5 billion comparisons at fifty thousand personas.

**Communities.** Leiden over the weighted graph across a γ search, selecting the qualifying partition with the highest modularity, with the size floor expressed as a share of the population so small studies are not structurally doomed. A population that forms no qualifying partition is still valid: polarization is then reported as not measurable, because reporting a measured zero for an unmeasured quantity is the dishonesty this engine exists to avoid.

**Determinism.** Three streams spawned from the population seed — sampling, rewiring, community detection — because Leiden is randomised too. Tie strengths are quantised before becoming edges, since the graph hash covers them as floats and a different BLAS build would otherwise change a population's identity. Every tie-break is explicit. Determinism is promised under a deterministic inference port; against a live model a population is built once and carried, never rebuilt.

**Contracts amended.** Module 1 gains: `Relaxation` and `GateReport.relaxations`; a third gate kind for graph results and a report keyed by subject rather than attribute; a `Population` invariant that every persona has at least one tie when a graph is present; manifest fields for the requested mix, completion provenance and synthesized share, and the full tunable `PopulationParameters` a population was built with; `Audience.share`; predicates in `attribute_filters`; an `OutcomeDigest` that can say polarization is not measurable; an optional `Persona.embedding`; and hash-excluded drafting provenance on `CategoryOntology` (ADR 0014). Module 2 gains a slice: the YAML speaks shares and predicates, the example declares them, and the pinned identities are re-pinned under 1.0.0, which remains unreleased.

## Testing Decisions

Boundary tests through `assess` and `build` only, against a shape-driven `SyntheticCoresetSource` and `FakeInference`. The shape declares, per attribute, its value set, its distribution and how often it is populated — so every scenario is data rather than a flag: skew a value to fail a gate, starve a band to climb the relaxation ladder, drop a conditioning attribute's coverage to prove those rows never enter the pool, flatten every attribute to produce a graph with no communities. A small hand-written fixture source covers the cases where a human should read input and expectation side by side.

The tests that carry the most weight are the ones that are only expressible here: no demographic or psychographic field is ever synthesized; a row missing a conditioning attribute never reaches the candidate pool; the source mix reflects what the conditioning filter did; the same seed builds an identical population twice; graph gates hold across twenty seeds; and a completion that answers off-list leaves a gap rather than inventing a value.

Perf gates from §11 apply to the synthetic path: `build()` for n=2,000 under five seconds, which the candidate-sampled rewiring exists to protect.

## Out of Scope

The packed 4-bit decoder and `HfCoresetSource`, deferred with return criteria in §12 — the format is documented in a schema this repository has never seen, and a fixture cut from real rows would redistribute dataset content whose terms are unresolved. Corpus-grounded authoring of ontologies and audiences (ADR 0014), which is blocked on the same dependency and becomes its own module. Persisting a population and its embedding array, which belongs to whoever owns durable state and is recorded as a requirement against `trace` and `runner`. `calibration_targets.json`, so a brief declaring no audiences samples the dataset's composition rather than a category's, and says so.

## Further Notes

`FINAL_ARCH.md` §5.3 needs three corrections: `Population` cannot carry the embedding array, `gate_report.degradations` is now `relaxations`, and the four graph gates become three results plus an invariant. ADR 0001 says two seed streams and should say three. A new ADR records that a population is built once and carried rather than rebuilt, and that determinism is promised only under a deterministic inference port.
