# PRD — M1 `schemas`: the engine's contracts

## Problem Statement

Nothing in the engine exists yet, and eleven other modules are about to be written against a specification that describes their inputs and outputs in prose. Prose does not stop anyone from building the wrong thing.

A grilling session against the architecture found nine defects in the type design before a line of code existed — a single provenance vocabulary meaning three unrelated things, a replicate-seed field that silently produced identical worlds, a distribution-gate threshold whose pass direction was ambiguous, a belief model that made the engine's most valuable finding unrepresentable. Every one of those would have compiled, run, and produced plausible-looking numbers.

That is the real risk this module addresses. This engine's entire value rests on four claims: that a number can be traced to the events that produced it, that dataset facts and model-invented facts never mix silently, that a run can be reproduced from its recorded inputs, and that nothing is presented as proven. Each of those is currently a sentence in a document. A sentence in a document is enforced by whoever remembers to read it. When a contributor adds a field, a maintainer reviews a pull request at speed, or a module is written six months from now by someone who never read the architecture, the claims survive only if the types refuse to express their violation.

Without this module, each of the eleven others invents its own shapes at its own boundary, the four contracts degrade into review comments, and the engine's central selling point — auditability — becomes an aspiration.

## Solution

A single leaf package that defines every structure crossing a module boundary, and encodes the engine's invariants as validation rather than convention.

It holds no logic, performs no I/O, and imports nothing from the project — so every other module can depend on it and it can depend on nothing. Its only executable code is validators, and those may only assert things true of the data by definition. Whether a population passes a distribution gate is a question for the population module; whether a probability mass function sums to one is a question the type answers by itself.

Concretely, after this module exists:

- A finding cannot be constructed without the trace records supporting it and the real-world test that would falsify it. Unprovenanced claims stop being a policy and become a type error.
- A persona field always states where it came from, rather than being assumed grounded because a dictionary key is absent.
- A run configuration refuses an unpinned model identifier, so a run whose results cannot be reproduced cannot be started.
- A report cannot claim calibration, because the evidence a calibrated claim requires has no producer anywhere in the repository.

The module also fixes the vocabulary. A companion glossary now distinguishes an audience from a community, a tick from a horizon, an exposure from an impression, a trust level from a confidence — distinctions that were previously collapsed into overloaded words and were the direct cause of several of the nine defects.

## User Stories

**Building other modules**

1. As an engine developer, I want every structure that crosses a module boundary defined in one place, so that I never have to guess what shape another module will hand me.
2. As an engine developer, I want to import types from a single curated surface rather than reaching into internal files, so that names can be deprecated later without breaking every caller.
3. As an engine developer, I want the contracts package to import nothing from the project, so that I can depend on it from anywhere without creating a cycle.
4. As an engine developer, I want unknown fields rejected rather than ignored, so that a typo in a field name fails loudly instead of silently defaulting.
5. As an engine developer, I want every boundary type frozen, so that a structure cannot be mutated after its hash has been recorded.
6. As an engine developer, I want infinities and not-a-number rejected on every float, so that a poisoned aggregate fails at the boundary rather than surfacing as a null in a report.
7. As an engine developer, I want closed enumerations for every closed set, so that a mistyped string cannot invent a new category at runtime.
8. As an engine developer, I want error types that carry their own exit codes, so that the command line can distinguish a failed gate from a crash without a lookup table.

**Provenance and grounding**

9. As an engine developer, I want separate vocabularies for where a brief statement came from and where a persona field came from, so that a type cannot express a combination that means nothing.
10. As an engine developer, I want every projected persona field to state its origin explicitly, so that "this value is grounded" is an assertion rather than an inference from a missing key.
11. As a maintainer, I want a persona to be unconstructible without the attributes its category requires for conditioning, so that the elicitation method's core requirement is guaranteed by the type rather than checked at simulation time.
12. As an analyst, I want a population's source mix reported alongside its distributions, so that I can see whether the conditioning requirement skewed the sample toward the dataset's complete synthetic rows.
13. As a maintainer, I want distribution gates to refuse attributes whose values were synthesized, so that the engine cannot validate its own output against a target it also produced.

**Authoring a study**

14. As a study author, I want to name audiences in my brief and refer to them by name when weighting a scenario, so that I can write a sweep file before any population exists.
15. As a study author, I want discovered communities to appear only in results and never in inputs, so that I am never asked to reference an identifier that does not exist yet.
16. As a study author, I want a scenario to describe conditions only, so that I can re-run the same scenario under a different random draw without editing it.
17. As a study author, I want to declare how many replicates to run in one place, so that I do not author near-identical scenarios by hand.
18. As a study author, I want the price under test to live in exactly one place, so that a sweep cannot disagree with itself about what it is testing.
19. As a study author, I want prices to carry their currency, so that a number cannot be silently reinterpreted.
20. As a study author, I want to declare what a tick means in real time and how many of them a world runs, so that scheduling a promotion at a given tick is unambiguous.
21. As a study author, I want claims automatically identified and their order pinned, so that reordering them is caught rather than silently invalidating comparability.

**Simulating**

22. As a study author, I want a persona to react to everything it saw on a channel in one tick, so that social proof works through juxtaposition rather than being reduced to a counter on an isolated post.

**Reproducing and auditing a run**

23. As an engine developer, I want a run configuration to reject unpinned or wildcard model identifiers, so that an unreproducible run cannot be started at all.
24. As a maintainer, I want hashing to be canonical and order-independent, so that a dictionary's insertion order never changes a run's identity.
25. As a maintainer, I want the schema version folded into the run hash, so that a change to the contracts invalidates cross-run comparability rather than producing a false match.
26. As a maintainer, I want outputs like observed cost and wall-clock timestamps excluded from hashes, so that identical inputs hash identically regardless of when they ran.
27. As an engine developer, I want a world's identity derived from its variant, replicate and population, so that resuming a crashed run is idempotent and I can tell whether a sweep cell has already been computed.
28. As an engine developer, I want trace event payloads typed per event kind, so that the writer can fan events into typed columns instead of an opaque blob.
29. As a maintainer, I want traces written under an older contract version to remain readable under a newer one, so that replaying an old run is a real capability rather than a claim.
30. As an engine developer, I want the version recorded once per partition rather than on every event, so that a constant fact is not stored hundreds of thousands of times on the hottest write path.

**Reporting honestly**

31. As an analyst, I want every finding to carry the trace records supporting it, so that I can walk from any statement back to the events that produced it.
32. As an analyst, I want every finding to carry the real-world test that would disprove it, so that I am never handed a result nobody could challenge.
33. As an analyst, I want calibration status stated once per run rather than repeated on every finding, so that I am not misled into thinking findings differ in how well the engine has been validated.
34. As an analyst, I want per-finding confidence kept separate from run-level calibration, so that "this segment was small" is not confused with "this engine has never been benchmarked".
35. As a maintainer, I want a calibrated claim to require evidence that nothing in the repository can produce, so that the engine cannot overclaim even if someone tries.
36. As an analyst, I want beliefs recorded per individual claim rather than as one aggregate, so that a report can identify which specific claim moved people and which was the liability.

**Contributing and testing**

37. As a contributor, I want the project's vocabulary written down with the words to avoid, so that I use the same term the existing code uses.
38. As a contributor, I want a test that fails if the contracts package gains a project or heavy numeric dependency, so that the rule that keeps it a leaf is enforced rather than remembered.
39. As a contributor, I want committed fixtures pinning known structures to known hashes, so that an accidental change to field order or serialization is caught immediately.
40. As a contributor, I want round-trip tests over generated values, so that serialization is verified against the space of valid inputs rather than a handful of examples.
41. As an engine developer, I want documented escape hatches for the three high-volume paths, so that validation guards boundaries without making the hot paths unusably slow.
42. As a maintainer, I want the whole test suite to run with no API key and no dataset download, so that a first-time contributor can verify their change immediately.

## Implementation Decisions

### Shape and constraints

The module is organized one file per domain — the shared base and identifier types, enumerations, errors, and then one file each for the brief, the persona, the population, the simulation, the run, the trace, and the report. A curated export surface is the only import path other modules use.

It imports nothing from the project and only the validation library plus the standard library from outside. No numeric or dataframe libraries. A test enforces this by inspecting imports directly, because it is the rule most likely to erode under pressure.

Every model rejects unknown fields, is frozen, rejects non-finite floats, and strips surrounding whitespace on strings. Container fields are tuples, frozensets or `FrozenDict` — list, dict and set annotations are refused when a class is defined, because freezing a model does not freeze a container inside it. Copying a model with updates re-validates the updates.

### The nine decisions from the grilling session

**Provenance splits into two vocabularies.** One describes where a statement in the brief came from — asserted by the user, drawn from a public source, or assumed. The other describes where a persona field came from — the dataset row, a model completion, or an external correction. The second includes an explicit "grounded" value, so the engine's central invariant is a stated value rather than an absent dictionary key. Findings lose their provenance field entirely: a finding's evidence is always simulation output, so the field was a constant.

**Audience and community replace "segment".** An audience is declared in the brief, named, and referenced by name in scenario inputs; when a brief declares none, audiences derive from the dataset's calibration targets. A community is discovered in the generated social graph and appears only in outputs. "Stratum" leaves the vocabulary; the population manifest records an achieved mix keyed by audience. Outcome digests carry both audience-level and community-level distributions, with polarization defined over communities.

**Scenarios lose their seed.** Replicate seeds live on the run configuration; a world's seed is derived from the replicate seed and the variant identifier, and its identity from those plus the population hash. The population carries one seed, from which sampling and graph generation draw independent spawned streams. Trace events lose their seed field, since the world identifier already resolves it and the registry records every seed. Recorded as ADR 0001.

**Personas require a conditioning set.** A category's ontology declares the attributes a persona must have populated to be usable. The persona type separates that required conditioning mapping from its remaining attributes, so an unconditionable persona cannot be constructed. The gate report gains a source mix so any skew this induces is visible. Recorded as ADR 0002.

**Gate results become a tagged union.** A categorical arm carries a chi-squared statistic, degrees of freedom and a p-value; an ordinal arm carries both the raw statistic and a similarity value derived from it, named so the pass direction cannot be misread. The overall status is computed from the results rather than settable. Ordinal attributes and their band scales are declared in the ontology, so nothing is treated as ordered by guess. A validator refuses gate results over synthesized attributes.

**Time is declared.** A scenario states its tick unit and horizon in ticks. Outcome digests carry the unit forward so a report can label an axis and analysis can refuse to compare digests across differing units. The second, undefined "world-day" unit is removed.

**Impressions replace per-stimulus reactions.** An impression is everything one persona sees on one channel in one tick, holding one or more exposures. Exposures keep their per-stimulus shape, so recommender scoring, attention and drop reasons are unchanged — they are grouped, not flattened. A reaction references the impression it saw and, separately, the stimulus it is about, since intent is directed at a specific proposition even when several things were on screen. A survey-room impression holds exactly one exposure, giving both environments one code path. Recorded as ADR 0003.

**Beliefs gain per-claim resolution.** A closed enumeration covers value, personal fit, and trust; alongside it, a credence value per brief claim. Levels are bounded to the unit interval and deltas to the signed unit interval. A validator enforces that credence keys match the brief's claims exactly. Reflection triggers on the largest movement across dimensions and claims together, so flipping on one specific claim triggers reflection even when aggregate belief barely moves.

**Trust moves to the run.** A trust statement sits on the report, carrying a level, an optional calibration reference, and caveats. The ladder has three levels: uncalibrated, category-benchmarked, and prospectively validated. The commercial "customer-calibrated" level is removed as having no referent. Any level above uncalibrated requires a calibration reference, and nothing in the repository produces one. Findings keep only what genuinely varies per finding: kind, statement, evidence identifiers, confidence, and a disconfirming test.

### Supporting decisions

Price is typed rather than a bare float and lives only on the scenario; the brief's price seeds the first scenario. The persona source is a validated string against a known-value set rather than a strict enumeration, because the dataset's actual values are unverified and a strict enumeration would fail on first contact with real data; it is promoted to an enumeration once the dataset card is read. The contract version is recorded in partition metadata and the run registry, not on every event. Persona identifiers are `p-` followed by the dataset row identifier, so cross-run joins need no lookup table; run and stimulus identifiers are `run-` and `st-` followed by a lowercase ULID, so they sort by creation time.

### Hashing

Canonical serialization sorts keys, uses compact separators, rejects non-finite values, and serializes enumerations by value so member renames do not move hashes. Each type declares which of its fields are excluded — outputs like observed cost and timestamps — and the declaration holds wherever the type is nested. Set-valued fields are sorted, negative zero is normalised, and the contract version is folded under a reserved key that no field can occupy. Four hashes exist: one pinning the brief and its claim order, one pinning the population, one pinning the run configuration including the contract version, and one pinning the generated graph.

### Performance

Validation guards boundaries, not inner loops. Three paths use unvalidated construction and are fully validated only in continuous integration: trace writes, graph adjacency, and per-row dataset decode. Embeddings never live inside a model; a reference locates a row in a contiguous array owned by the population, which also keeps the numeric library out of the contracts package.

## Testing Decisions

A good test here asserts observable behaviour through the public surface: that a structure round-trips, that an invalid structure is refused, that a known input produces a known hash. It does not assert how a validator is implemented, does not reach into private helpers, and survives a refactor of the module's internals. A test that breaks when a field is reordered but nothing observable changed is a test that will be deleted rather than fixed.

This is the first module in the repository, so there is no prior art. The patterns established here set the precedent for the other eleven, which makes getting the style right more valuable than usual.

Five classes of test, all of which run with no API key, no network, and no dataset download:

**Round-trip tests** over every type, using generated values rather than hand-picked examples, verifying that serializing and reparsing yields an equal structure. Property-based generation matters because hand-written examples systematically miss the boundary values that break serialization.

**Hash stability fixtures**, committed to the repository, pinning a known brief and a known run configuration to their expected hashes. These protect every downstream reproducibility claim; a diff here is a deliberate decision, never an accident.

**Invariant tests**, one per validator, each asserting the refusal rather than the acceptance: a mass function containing a zero, a non-finite value, or an incorrect sum; a wildcard model identifier; a finding without evidence; a finding without a disconfirming test; a trust level above uncalibrated with no calibration reference; belief credence whose keys do not match the brief's claims; a gate result over a synthesized attribute; a persona missing a conditioning attribute.

**A dependency test** that inspects the module's imports and fails on any project import or any heavy numeric dependency.

**A forward-compatibility test** confirming that a trace partition written under one contract version is readable under a later one.

Every other module in the engine will be tested at its own boundary rather than internally; this module's tests are the foundation that makes those boundary tests meaningful, because they guarantee the shapes those tests assert on.

## Out of Scope

This module performs no input or output, makes no model calls, reads no files, and consults no clock. It does not decode the dataset, sample a population, generate a graph, run a simulation, compute a digest, or render a report — it only defines the shapes those operations exchange.

Specifically excluded:

- Business rules of any kind. Whether a population passes its gates, whether a budget is exhausted, whether a finding is interesting — all belong to the modules that own those questions.
- The port protocols and their adapters. Those live alongside the adapters rather than in the contracts.
- Category ontologies and anchor sets as content. The module defines their shape; the files themselves are authored separately.
- Verifying the dataset's actual source values, which requires the dataset and is tracked as a follow-up before the source type is frozen into an enumeration.
- Any type whose only consumer is a deferred capability — the calibration reference exists as a shape so the trust guard can refer to it, but the benchmark harness that would produce one is out of scope.
- Reconciling the architecture document with the nine decisions above. That is a separate task and currently outstanding.

## Further Notes

The architecture document still describes the pre-grilling design in roughly eleven places — the single provenance vocabulary, the sampling-strata language, the gate shape and the build signature, the exposure-driven turn, the removed second time unit, the world identity formula, the per-event version field, and the per-finding trust tier. Implementing against the document as it stands would reproduce the defects this work removed. Either reconcile the document first or treat this PRD and the three architecture decision records as authoritative and update the document afterwards.

One dependency sits outside this module but constrains it: the persona dataset's actual source values are unverified, which is why that field is a validated string rather than an enumeration. Freezing it is a small follow-up once the dataset card can be read, and it should not block this work.

The glossary is a living document. Terms resolved while building later modules belong there as they are settled, not batched at the end — and the words listed under each term as ones to avoid are as load-bearing as the definitions, because most of the nine defects found were caused by one word quietly meaning several things.
