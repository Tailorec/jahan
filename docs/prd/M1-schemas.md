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
11. As a maintainer, I want a population to refuse any persona lacking the attributes its category requires for conditioning, so that the elicitation method's core requirement is guaranteed by the type rather than checked at simulation time.
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
27. As an engine developer, I want a world's identity derived from its whole scenario, replicate and population, so that resuming a crashed run is idempotent and I can tell whether a sweep cell has already been computed.
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

**Scenarios lose their seed.** Replicate seeds live on the run configuration; a world's seed is derived from the replicate seed and the variant identifier, so price points of one variant share their random draws, while its identity derives from the scenario's full content, the replicate seed and the population hash (ADR 0005), so every distinct cell is a distinct world. The population carries one seed, from which sampling and graph generation draw independent spawned streams. Trace events lose their seed field, since the world identifier already resolves it and the registry records every seed. Recorded as ADR 0001.

**Personas require a conditioning set.** A category's ontology declares the attributes a persona must have populated to be usable. The persona type separates that required conditioning mapping from its remaining attributes, but carries no copy of the conditioning set or field domains: a population aggregate joins personas with the brief pack and checks every persona against the ontology, so neither invariant can be satisfied by a persona labelling itself. The gate report gains a source mix so any skew this induces is visible. Recorded as ADR 0002.

**Briefs reference their ontology.** A brief names the ontology version it is read against and takes its category from the product; a brief pack joins the brief with that ontology and refuses a mismatch. The ontology declares a field domain for every attribute it uses — including category behaviour, which the conditioning set depends on — so demographic fields can be recognised when personas are built. Audience filters are checked against the ontology at pack time. Recorded as ADR 0004.

**Gate results become a tagged union.** A categorical arm carries a chi-squared statistic, degrees of freedom and a p-value; an ordinal arm carries both the raw statistic and a similarity value derived from it, named so the pass direction cannot be misread. Each result carries its threshold and computes its verdict; the overall status is computed from those verdicts. Both serialize, and a supplied verdict that contradicts the computation is refused, so a stored report cannot claim a failing statistic passed. Ordinal attributes and their band scales are declared in the ontology, so nothing is treated as ordered by guess. The population refuses gates over attributes that are not grounded for every persona carrying them.

**Time is declared.** A scenario states its tick unit and horizon in ticks. Outcome digests carry the unit forward so a report can label an axis and analysis can refuse to compare digests across differing units. The second, undefined "world-day" unit is removed.

**Impressions replace per-stimulus reactions.** An impression is everything one persona sees on one channel in one tick, holding one or more exposures. Exposures keep their per-stimulus shape, so recommender scoring, attention and drop reasons are unchanged — they are grouped, not flattened. A reaction references the impression it saw and, separately, the stimulus it is about, since intent is directed at a specific proposition even when several things were on screen. A survey-room impression holds exactly one exposure, giving both environments one code path. Recorded as ADR 0003. A turn joins an impression with its reaction and refuses a reaction about anything the impression did not show; the trace records whole turns, so the grouping survives into the record (ADR 0006). Identity hashes are derived rather than stated wherever their object is present, and a trace partition carries its run configuration and population manifest so every pin is verified against what it pins (ADR 0009).

**Beliefs gain per-claim resolution.** A closed enumeration covers value, personal fit, and trust; alongside it, a credence value per brief claim. Levels are bounded to the unit interval and deltas to the signed unit interval. Beliefs carry no claim list of their own: a persona's baseline beliefs are checked by the population against the brief's claims, and belief changes in the trace are checked by the partition against the brief it carries. Reflection triggers on the largest movement across dimensions and claims together, so flipping on one specific claim triggers reflection even when aggregate belief barely moves.

**Trust moves to the run.** A trust statement sits on the report, carrying a level, an optional calibration reference, and caveats. The ladder has three levels: uncalibrated, category-benchmarked, and prospectively validated. The commercial "customer-calibrated" level is removed as having no referent. Any level above uncalibrated requires a calibration reference pinning its benchmark and human study by content hash, with measured similarity and rank attainment both at or above 0.80 (ADR 0008); nothing in the repository produces one. Outcome digests compute adoption — top-two-box intent — and normalized polarization and audience divergence from the shares and sizes they carry (ADR 0007). Findings keep only what genuinely varies per finding: kind, statement, evidence identifiers, confidence, and a disconfirming test.

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

---

# Addendum — Phase 8: the remaining boundary contracts

## Problem Statement

Phases 1–7 delivered every contract their plan named, but a completeness check against the architecture found that module 1 still does not own every type crossing a module boundary. The inference, world and runner modules cannot be built against a contract, because what a model call returns, what a persona may see of the world, what a world step produces, and what a run returns were never designed. Two ontology fields the architecture relies on were also missing: an order of attribute relevance, and which anchor set a category uses for each construct.

Designing those types exposed three places where the engine would already have produced a trace it cannot defend. Fallback models would have failed every trace under the pin check, or silently switched a world's model mid-run. Budget degradation changed a world's fidelity mid-run without leaving any record, making degraded and full worlds look comparable and making replay impossible. Guardrail retries and violations had nowhere to go, so "never silently kept" held only by convention.

## Solution

Eight decisions, reached in a grilling session and recorded in ADRs 0010–0012 and the glossary, close the gap.

A persona's **view** is the public context of exactly what it is shown — engagement counts, reply ancestry, and its relationship to each author — never another persona's private state or any aggregate outcome. The view is recorded with the turn and verified against the trace, and engagement becomes visible only from the tick after it happens.

A **world step** takes the previous tick's turns and returns a delta built from the trace's own vocabulary, plus a presentation for each activated persona. The runner is the only writer of a partition. No world state crosses the boundary: a world resumes by replaying its recorded turns up to the last closed tick, and budget **degradation** is recorded so replay reproduces it and degraded worlds are never compared silently with full ones.

A **model call** returns its text, prompt hash, latency and the exact cost event it produced. Fallback models must be pinned, every call records whether the primary model, the fallback or the cache served it, and embedding never falls back. **Guardrail** retries are recorded on the turn they rescued, and a turn that fails its retry is recorded as a violation in place of a reaction.

A **run** returns its registry entry and one outcome per world, with the run's status computed from its worlds; a sweep is a plan expanded into a run, not a separate result. The **category ontology** ranks its attributes with the conditioning set first and names the anchor set for each construct.

## User Stories

**What a persona sees**

43. As an agent developer, I want a persona's view to cover exactly the stimuli it is shown, so that "context" for the guardrail is closed and well defined.
44. As a methodologist, I want no view ever to reveal another persona's attributes, beliefs or private reactions, so that one persona's behaviour is never conditioned on another's private data.
45. As a methodologist, I want no view to reveal an aggregate outcome such as running adoption, so that herding emerges from the simulation rather than being built in by showing personas the result being measured.
46. As an analyst, I want the social proof each persona saw recorded with its turn, so that a reaction to a post with 400 likes is distinguishable from one to a post with 3.
47. As a maintainer, I want a recorded view whose counts or thread disagree with the trace to be refused, so that the counting rule lives in one place and "what did this persona see" has one answer.
48. As a methodologist, I want engagement to become visible only from the tick after it happens, so that the order of turns within a tick never changes what a persona sees.
49. As an analyst, I want upvotes and downvotes counted separately, so that forum ranking and its herding can be reconstructed.
50. As a methodologist, I want a view to record the viewer's tie strength and shared community with each author, verified against the population, so that word-of-mouth effects can be attributed to real ties.

**What a world step produces**

51. As a world developer, I want a step to take the previous tick's turns and return a delta in the trace's own vocabulary, so that no translation layer can make the trace and the world disagree.
52. As a runner developer, I want to be the only writer of a partition, so that one gapless sequence covers world events, turns and costs without two writers coordinating.
53. As a runner developer, I want each activated persona's impression and view delivered together as one presentation, so that an agent always receives both halves of its context.
54. As a maintainer, I want a crashed world to resume by replaying its recorded turns, so that no second copy of world state can disagree with the trace.
55. As a maintainer, I want every fully recorded tick marked as closed, so that resume can tell a complete tick from a crash partway through one.
56. As an analyst, I want budget degradation recorded in every affected world at the tick it applies, so that a world that ran half its horizon at reduced activation is never compared silently with one that ran in full.
57. As a maintainer, I want degradation to only escalate and a pause to follow the pause rung, so that the recorded ladder is the one the runner can actually apply.

**What a model call returns**

58. As a runner developer, I want a model call to return the exact cost event it produced, so that cost has one source and is appended without translation.
59. As a maintainer, I want fallback models pinned in the run configuration, so that a provider outage substitutes a model the configuration names rather than failing the trace or switching silently.
60. As an analyst, I want every cost event to record whether the primary model, the pinned fallback or the cache served it, so that turns served by a fallback can be found and set aside.
61. As a methodologist, I want the embedding role never to fall back, so that anchors and responses are always compared in one embedding space.
62. As an analyst, I want a turn accepted on a guardrail retry to record the prompt it rejected, so that a stricter retry instruction's influence on the answer is visible.
63. As a maintainer, I want a turn whose retry also fails recorded as a guardrail violation in place of a reaction, so that violations are counted from the trace rather than kept only in logs.

**What a run returns**

64. As a CLI developer, I want a run to return its registry entry and one outcome per world, so that a paused budget run reports exactly which worlds are complete and which are partial.
65. As a maintainer, I want a run's status computed from its worlds and a completed world to have closed every tick of its horizon, so that a run cannot claim completion it did not reach.
66. As an engine developer, I want a sweep to be an ordinary run over an expanded plan, so that there is one result type and one code path for both.

**The category ontology**

67. As an agent developer, I want the ontology to rank every attribute by relevance with the conditioning set first, so that a tight token budget cuts only non-conditioning attributes.
68. As a methodologist, I want the ontology to name the anchor set for each construct, and every elicitation to be scored against it, so that a beverage study cannot be scored against another category's anchors.
69. As a maintainer, I want the run to pin every anchor set its ontology names, so that the anchors a study depends on are part of what replay reproduces.

## Implementation Decisions

**The view.** A view names its impression and maps each shown stimulus — exactly those, no more and no fewer — to its public context: like, repost, reply, upvote and downvote counts; the reply ancestry from nearest parent to root; the viewer's tie strength to the author; and whether the two share a community. Reposts count both reposts and quotes; replies count published replies. Tie strength and shared community are absent for study-authored stimuli and for the viewer's own; tie strength is zero where no tie exists; shared community is absent when the population has no communities. Counts include only engagement recorded at earlier ticks. The vote action splits into upvote and downvote. The turn record carries its view, and a new guardrail-violation record carries one too. A partition verifies each recorded view's keys, counts and ancestry against its own earlier events. Tie strength and community are verified by a new join of a world's partition with its population, which also checks that the partition's population manifest is that population's.

**The world step.** A world delta names its tick and carries the stimuli published, the interventions applied, the exposures dropped with the persona each was dropped for, and one presentation — an impression with its view — per activated persona and channel. Every dated element of a delta shares the delta's tick; a presentation's view must match its impression. There is no world-state type; the opening delta is tick zero. A new tick-closed record marks each fully recorded tick: a partition refuses any record for a tick after that tick is closed, and requires ticks to close in order. A new degraded record carries the rung applied — warn, freeze optional tier-B work, subsample activation, pause — with the activation rate and tier-B freeze now in force; a partition requires rungs to escalate, and a paused lifecycle record to follow the pause rung.

**Model calls.** A completion carries its text, the template it rendered, its prompt hash, its latency and the cost record it produced. The cost record gains its route — primary, fallback or cache — and whether the cache served it becomes computed from the route rather than stated alongside it. Model pins gain an optional pinned fallback per role; a fallback for the embedding role, or a fallback identical to its primary, is refused. A partition accepts a billed model only if it is the primary for its role on the primary route, the pinned fallback on the fallback route, or either of the two on the cache route.

**Guardrails.** A turn record lists at most one prompt hash it rejected before accepting, distinct from the accepted one. A guardrail-violation record carries the impression, the view, the two rejected prompt hashes and the rule broken, and no reaction; it belongs to the impression's persona and tick, and its impression may not also appear in a turn. Rules are a closed set, starting with references to an unshown stimulus.

**Run results.** A run result carries the registry entry and one outcome per world. An outcome states its world, its status — completed, partial or not started — the last tick it closed, and the degradation rungs applied. Outcome world ids must be exactly the registry's; a not-started world has closed no tick and applied no rung; a completed world has closed the final tick of its scenario's horizon; rungs escalate. The run's status is computed — completed only when every world completed, partial otherwise — and the registry entry's status must agree. There is no sweep result.

**The ontology.** The ontology gains an attribute relevance order listing every declared attribute exactly once, with the conditioning set occupying the leading positions, and a mapping from each construct to its anchor set. A partition refuses an elicitation scored against any anchor set other than the one its ontology names for that construct, and refuses a run configuration that does not pin every anchor set the ontology names. The architecture's per-category stimulus types are dropped; stimulus kinds remain one closed set.

**Contract version.** Contract 1.0.0 has not been released: no trace or registry entry has been stored. Phase 8 lands within it and re-pins the representative identities under 1.0.0. The first stored run releases the contract, after which ADR 0009's rule binds — a hashed shape change requires a version bump and new pins.

## Testing Decisions

The same posture holds: assert refusals and observable behaviour through the public surface, with builders producing valid data and each test breaking one thing. Prior art now exists for every shape these contracts take — the study builders, the partition tests' single-change mutations, computed-value round-trips, and the per-version replay pins.

The representative partition grows to exercise each new record: views with non-zero counts drawn from its own earlier turns, a reply thread, a closed tick, a degradation rung, a guardrail retry and a violation, and a fallback-routed cost. Refusal tests cover each verification — a view counting a same-tick like, an ancestry skipping a parent, a record after its tick closed, a rung de-escalating, a billed fallback that is not pinned, an embedding fallback, a violation reusing a turn's impression, a completed world short of its horizon, a relevance order with a conditioning attribute outranked, and an elicitation scored against another construct's anchors. The replay pins are regenerated deliberately under 1.0.0 as the contract is still unreleased.

## Out of Scope

The world, runner and inference implementations themselves: recommender ranking, activation, the resume procedure, the cost ledger and degrade ladder's triggering, provider routing and caching. Expanding a sweep plan into a run configuration. How a view is rendered into a prompt, and how a relevance order is cut to a token budget — only the order and the guarantee that conditioning attributes lead it are contracts.

## Further Notes

Three ADRs record the decisions most likely to be questioned later: 0010 (recorded, verified views with next-tick visibility), 0011 (replayed resume, the runner as sole writer, and recorded degradation) and 0012 (pinned fallbacks and recorded routes). The glossary gained View, Social Proof, Presentation, Degradation, Guardrail Violation, Construct and Anchor Set.

