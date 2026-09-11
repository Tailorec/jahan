# Plan: M1 `schemas` — the engine's contracts

> Source PRD: `docs/prd/M1-schemas.md`
> Binding decisions: `CONTEXT.md` (glossary), `docs/adr/0001`–`0003`. Where `FINAL_ARCH.md` disagrees with either, those win — the architecture document has not yet been reconciled.

## Architectural decisions

Durable across every phase:

- **Leaf rule** — the package imports nothing from the project, and only the validation library plus the standard library from outside. No numeric or dataframe dependency, ever. Enforced by a test, not by convention.
- **File organization** — one file per domain (base/identifiers, enumerations, errors, brief, persona, population, simulation, run, trace, world, report), with a single curated export surface as the only import path other modules use.
- **Model defaults** — every model rejects unknown fields, is frozen, rejects non-finite floats, and strips surrounding string whitespace. Container fields are tuples, frozensets or `FrozenDict` — list, dict and set annotations are refused when a class is defined, because freezing a model does not freeze a container inside it. Copying a model with updates re-validates the updates.
- **Canonical hashing** — sorted keys, compact separators, enumerations serialized by value, non-finite values rejected, per-class exclusion of outputs (observed cost, wall-clock timestamps), exclusions and version folding honoured at every nesting level, including inside sequences and mappings; set-valued fields sorted so hash-seed iteration order never leaks in; negative zero normalised so structures that compare equal hash equally; the contract version folded under a reserved key no field can occupy; misspelled or mistyped exclusions refused when a class is defined. Four hashes exist: brief, population, run configuration (which folds in the contract version), and graph.
- **Identity** — persona identity derives from the dataset row so cross-run joins need no lookup table; persona identity is `p-` followed by the dataset row identifier; run and stimulus identities are `run-` and `st-` followed by a lowercase ULID, so they sort by creation time; world identity derives from the scenario's full content, replicate seed and population hash (ADR 0005), while worlds of one variant share their seed so price points share random draws.
- **Two provenance vocabularies** — one for where a brief statement came from, one for where a persona field came from. The second carries an explicit grounded value; grounding is never inferred from an absent key.
- **Audience versus community** — audiences are declared in inputs and referred to by name; communities are discovered and appear only in outputs. "Segment" and "stratum" are not used.
- **Ontology is referenced, not embedded** — a brief names its ontology version and takes its category from the product; a brief pack joins the two and refuses a mismatch (ADR 0004). Every attribute the ontology or an audience uses declares its field domain.
- **Instants are timezone-aware** — bare datetime annotations are refused when a class is defined, and instants render in UTC before hashing.
- **Validation guards boundaries, not inner loops** — three documented unvalidated-construction paths (trace writes, graph adjacency, per-row decode), fully validated only in continuous integration.
- **Errors carry exit codes** — the command line distinguishes a failed gate from a crash by exception class, not by string matching.
- **Views are recorded and verified** — a persona sees the public context of exactly what it is shown, recorded with its turn and checked against the trace; engagement is visible only from the next tick (ADR 0010).
- **The runner is a partition's only writer; worlds replay** — world steps return deltas in the trace's own vocabulary, no world state crosses the boundary, and degradation is recorded so replay reproduces it (ADR 0011).
- **Fallbacks are pinned and routes recorded** — a fallback model must be pinned for its role, every cost records its route, and embedding never falls back (ADR 0012).
- **Contract 1.0.0 is unreleased until phase 8 lands** — identities are re-pinned under 1.0.0; the first stored run releases it, after which a hashed shape change needs a version bump.
- **Test posture** — assert refusals and observable behaviour through the public surface; never reach into private helpers. Whole suite runs with no API key, no network, no dataset download.

---

## Phase 1: The spine

**User stories**: 1, 2, 3, 4, 5, 6, 8, 24, 25, 26, 38, 39, 40, 42

### What to build

The foundation every later phase is built from, proven end-to-end on a single throwaway model: the shared base configuration, the bounded numeric and constrained string primitives, identifier and hash types, the contract version constant, canonical serialization and hashing with per-class exclusions, and the error hierarchy carrying exit codes.

The demonstration is deliberately narrow — one small model defined purely to exercise the machinery — but it cuts the whole depth of the module: definition, validation, serialization, hashing, fixture pinning, and the dependency guard. If this phase is right, every later phase is additive.

### Acceptance criteria

- [x] A model built on the shared base rejects an unknown field, refuses mutation after construction, and rejects a non-finite float
- [x] Bounded primitives reject values outside their range, and constrained strings reject the empty case
- [x] The same structure hashes identically across two processes, and identically when its dictionary fields are built in a different insertion order
- [x] A field marked as excluded from hashing can change without moving the hash
- [x] The contract version is folded into the run-configuration hash and absent from the brief hash
- [x] A committed fixture pins a known structure to a known hash, and fails loudly if serialization changes
- [x] Round-trip holds over generated values, not only hand-written examples
- [x] Each error class exposes a distinct exit code, and a failed gate is distinguishable from a crash
- [x] A test inspects the package's imports and fails on any project import or heavy numeric dependency
- [x] The suite runs with no API key, no network access, and no dataset present, and a guard refuses network connections and hides credentials rather than relying on none being used
- [x] Hash exclusions hold at every nesting level — inside nested models, sequences and mappings
- [x] Set-valued fields hash identically across processes regardless of hash seed
- [x] Structures that compare equal hash equally, including negative and positive zero
- [x] Container field contents cannot be mutated after construction, and mutable container annotations are refused when a class is defined
- [x] A misspelled or mistyped hash exclusion, or a field that could displace the folded contract version, is refused or made impossible
- [x] Copying a model with updates re-validates those updates
- [x] Run, stimulus and persona identifiers enforce their documented prefixed formats
- [x] Unvalidated construction refuses raw mappings wherever a field expects a model
- [x] The representative study's population, graph and configuration hashes and world ids are pinned per contract version, so a hashed shape cannot change without a version bump

---

## Phase 2: The brief

**User stories**: 4, 7, 14, 18, 19, 21, 24, 37

### What to build

Everything needed for a real study brief to validate: claim sources, claims with evidence references, product information, price with currency, competitors, target market, named audience declarations, assumptions, and the category ontology that travels with them — the conditioning set, the completion policy, and the ordinal attribute scales.

At the end of this phase an actual brief file parses, and reordering its claims is caught rather than silently invalidating comparability.

### Acceptance criteria

- [x] A representative brief file validates, and one with an unknown key is refused
- [x] Claim identifiers are assigned automatically, are contiguous, and duplicates are refused
- [x] Reordering claims changes the brief hash; reformatting whitespace or comments does not
- [x] Price carries its currency and refuses a non-positive amount
- [x] Audiences are declared by name and can be referenced by name without a population existing
- [x] A brief declaring no audiences is valid, and the type records that audiences will be derived
- [x] The category ontology declares its conditioning set, its completion policy, and its ordinal scales, and refuses a completion policy that lists a demographic attribute
- [x] Evidence references carry a fetched-at time and content hash when present, and are optional when absent
- [x] Re-fetching unchanged evidence does not move the brief hash; a changed content hash does
- [x] Fetch times without a timezone are refused, and the same instant in any offset hashes identically
- [x] A brief names its ontology version rather than embedding an ontology, and a brief pack refuses an ontology of another category or version
- [x] Every attribute in the conditioning set or an ordinal scale declares a field domain, so a demographic attribute can be recognised downstream
- [x] Ordinal scales accept real-unit midpoints, and refuse duplicate band labels or a second scale for the same attribute
- [x] Audience filters are refused when they name an attribute the ontology does not declare, or a value outside an ordinal attribute's bands
- [x] Competitors may carry their own claims as text

---

## Phase 3: The population

**User stories**: 9, 10, 11, 12, 13, 15

### What to build

The contract for who is in a study: field origin stated on every projected field, persona source as a validated value, the persona split between the conditioning attributes its category requires and everything else, the distribution gate as a tagged union over categorical and ordinal tests, the gate report with its source mix, the population manifest, the graph with its discovered communities, and the population that joins them with the brief and ontology they were built for.

This is the phase where the engine's central invariant becomes structural: a persona that cannot be conditioned, or one whose demographics were invented, cannot be constructed.

### Acceptance criteria

- [x] A persona conditioned on anything other than its category's conditioning set is refused when the population is joined with the ontology
- [x] A persona whose field origin marks a demographic or psychographic as synthesized is refused, judged by the ontology's field domains — a persona carries no domain labels of its own to relabel
- [x] Every projected field states an origin; grounding is never represented by an absent key
- [x] A gate result declares which test produced it rather than leaving the other test's fields null
- [x] The ordinal gate exposes both the raw statistic and the similarity derived from it, named so the pass direction cannot be misread
- [x] A gate over an attribute that is not grounded for every persona carrying it is refused, as is a gate on an undeclared attribute, on an attribute no persona carries, or of the wrong kind for the ontology's scales
- [x] Each gate's verdict is computed from its statistic and its carried threshold, and the overall status from those verdicts; both serialize, and a supplied verdict that contradicts the computation is refused
- [x] A gate report needs at least one result and at most one per attribute
- [x] The gate report carries the population's source mix, which must match the personas' own sources; sources are a validated string that warns on unrecognised corpora rather than refusing them
- [x] The population manifest records an achieved mix keyed by audience, and carries no stratum concept
- [x] Communities appear only in output types and cannot be referenced from any input type
- [x] Persona embeddings are referenced by position rather than stored inline, keeping the numeric library out of the package; positions are distinct and share one model and dimension
- [x] Personas are exactly the manifest's persona ids, sampled once each; the achieved mix reports every declared audience
- [x] The social graph ties only members of the population, each tie once; communities require a graph and partition the population
- [x] A population's hash is derived from its brief, ontology, seed, personas, graph and communities, and a graph's hash from its ties regardless of order or direction; a manifest stating other hashes is refused

---

## Phase 4: The run

**User stories**: 16, 17, 18, 20, 23, 27

### What to build

The contract for what is being run: the concept card, the scenario describing conditions with its tick unit and horizon, interventions, the budget, model pins, and the run configuration that binds variants to replicate seeds and a population.

The scenario carries no seed. World identity is derived. An unreproducible run cannot be expressed.

### Acceptance criteria

- [x] A model pin that is empty, wildcarded, or version-floating — including `-latest`, `:latest` and `@latest` suffixes — is refused
- [x] The run configuration pins the ontology hash alongside the brief hash, so editing an ontology without bumping its version is detected on replay
- [x] A scenario has no seed field, and the same scenario can be paired with different replicate seeds
- [x] World identity derives from the scenario's full content, replicate seed and population hash, and is stable across processes; changing any condition of a scenario changes it
- [x] Two replicates of one variant produce different world identities; the same replicate reproduces the same one; price points of one variant share their world seed
- [x] The run id is excluded from the configuration hash, so identical configurations hash identically
- [x] A run or grid refuses repeated seeds, repeated scenarios, a variant id naming two concept cards, and mixed tick units
- [x] Price appears on the scenario only, typed with its currency, and nowhere else in the run
- [x] Audience weights are refused unless they sum to one within tolerance
- [x] A scenario declares its tick unit and horizon, and interventions are expressed in ticks against them
- [x] Interventions at the same tick compose rather than replacing one another
- [x] A representative sweep grid file validates and expands to distinct world identities, including a price sweep over a single concept
- [x] A sweep plan refuses a scenario weighting an audience the brief does not declare, emphasizing a claim it does not make, or priced in another currency

---

## Phase 5: The simulation

**User stories**: 22, 36

### What to build

The contract for what happens during a run: probability masses over the response scale, stimuli, exposures, impressions grouping a tick's exposures for one persona on one channel, reactions referencing both what was seen and what they were about, belief dimensions alongside per-claim credence, memory views, and elicitation results carrying the model that produced them.

This is the phase carrying ADR 0003 — a persona reacts to an impression, and a survey room impression is the one-exposure case of the same type.

### Acceptance criteria

- [x] A probability mass containing a zero, a non-finite value, or a sum outside tolerance is refused
- [x] An impression holds at least one exposure, never the same stimulus twice; a survey room impression holds exactly one, using the same type as a feed impression
- [x] Exposures retain their per-stimulus attention and reason when grouped; the reason is a closed set, and whether a stimulus was noticed is computed from its attention
- [x] A turn joins an impression with its reaction and refuses a reaction about a stimulus the impression did not show, or engaging with one the persona did not notice
- [x] A reaction names the stimulus it is about; whose it is and when belong to the impression it answers
- [x] Text-producing actions need a verbatim; ignoring produces neither a verbatim nor an elicitation; forum replies, votes and ignoring are expressible
- [x] Belief levels are bounded to the unit interval and changes to the signed unit interval; beliefs carry no claim list of their own
- [x] Baseline beliefs are refused unless they credit exactly the brief's claims, checked by the population against the brief
- [x] A stimulus authored by a persona and one authored by the study are the same type; study-authored kinds refuse an author, persona-authored kinds require one, a claim post names its claim, and only a reply names a parent
- [x] An elicitation result carries its embedding model and anchor set; its headline mass is computed as the mean of at least six reference-set masses and cannot be stated at odds with them
- [x] There is no field anywhere that accepts a model-emitted numeric rating

---

## Phase 6: The trace

**User stories**: 5, 6, 28, 29, 30

### What to build

The append-only record's contract: event kinds, the event itself, its payload as a discriminated union over the eleven kinds, run registry entries pinning every hash needed for replay, and partition-level versioning with a lenient read path.

This is the hottest write path in the engine, so the phase also establishes the unvalidated-construction escape hatch and proves the round-trip holds at realistic volume.

### Acceptance criteria

- [x] Each payload kind is a distinct type that dispatches on its kind alone, and is the only record of what it describes
- [x] A turn event records the whole turn — the impression as shown, with its grouped exposures, and the reaction — so what a persona saw side by side is recoverable
- [x] Events carry no seed and no contract version, and are attributed to a persona exactly when they describe one; a turn event must agree with its impression's persona and tick
- [x] A partition header carries the brief pack, scenario, replicate seed and population hash, and derives the world id; a stated world id contradicting the derivation is refused
- [x] A partition refuses events from other worlds, repeated event ids, sequence gaps, time going backwards or past the horizon, and stimuli shown, dropped or replied to before they were published
- [x] A partition refuses claims the brief does not make, impressions over the scenario's exposure budget, unscheduled interventions, and repeated impressions or reactions
- [x] Events may be stored in any order; sequence order is recovered, and a realistic volume of turn events round-trips fully validated after being sorted by persona and tick
- [x] A partition from a newer contract, or with no valid contract version, is refused; an older one loads by applying every registered migration newer than its contract, in order; the result is always strict and the input is never mutated
- [x] Unvalidated construction is available, documented and covered in continuous integration, and refuses raw mappings as payloads
- [x] There is no field capable of storing a full prompt; a turn records its template id and hashes of its parts
- [x] A registry entry embeds the run configuration — every hash, seed, model pin, template hash and anchor-set hash — and derives its config hash, under the contract it was registered with, and its world ids
- [x] A partition header carries the run configuration and population manifest, and refuses a run whose brief, ontology, population, graph, scenario or seed pins disagree with what the partition carries
- [x] Events belong to personas in the population, render only pinned templates, elicit only with the pinned embedding model and anchor sets against the brief's category, and bill only pinned models
- [x] A turn's memories cite earlier turns or reflections of the same persona by event id
- [x] A partition opens with the world starting, moves only through started, paused and completed, and records nothing while paused or after completion

---

## Phase 7: The report

**User stories**: 31, 32, 33, 34, 35, 36

### What to build

The contract for what the engine says: findings with their supporting records and the test that would disprove them, the trust statement stated once per run, the calibration reference it requires above the uncalibrated level, objection clusters, anomalies, and outcome digests carrying both audience-level and community-level distributions with their tick unit.

This is where the engine's honesty becomes structural rather than editorial.

### Acceptance criteria

- [x] A finding without at least one distinct supporting record, or without a disconfirming test, is refused
- [x] A finding carries no trust level and no provenance — only what varies per finding; ranking and risk are finding kinds, and a ranking orders at least two distinct scenarios the report digests
- [x] Trust is stated once per report; a level above uncalibrated needs a calibration reference whose measured similarity and rank attainment both reach 0.80, and prospective validation needs a prediction registered before its outcome
- [x] A calibration reference pins its benchmark report and human study by content hash; nothing in the package constructs one, and a scan of the package enforces it
- [x] Per-finding confidence and run-level trust are separate fields that cannot be conflated
- [x] An outcome digest carries audience masses with shares and community masses with sizes, and computes adoption, polarization and audience divergence from them; stated values contradicting the computation are refused
- [x] Adoption is share-weighted top-two-box intent; polarization and audience divergence are normalized weighted Jensen–Shannon divergences, independent of insertion order
- [x] A report embeds its run configuration; every digest describes one scenario of that run, in that scenario's tick unit and audiences, once; anomalies belong to a scenario and fall within its horizon
- [x] An outcome digest carries its tick unit, and comparing digests across differing units is refused
- [x] Anomaly kinds are a closed set, an anomaly cites distinct evidence, and an objection cluster is at least as large as the distinct sample it cites

---

## Phase 8: The view

**User stories**: 43, 44, 45, 46, 47, 48, 49, 50

### What to build

The contract for what a persona may see beyond its impression: a view mapping each shown stimulus to its public context — engagement counts, reply ancestry, and the viewer's relationship to its author — recorded with the turn and verified against the trace. Votes split into upvotes and downvotes, and a world's partition joined with its population verifies the ties and communities a view records.

This phase makes social proof auditable: what a persona saw beside a stimulus is part of the record, and has exactly one correct value.

### Acceptance criteria

- [x] A view covers exactly the stimuli of its impression, and names that impression
- [x] A view carries no field for another persona's attributes, beliefs or private reactions, nor any aggregate outcome
- [x] Tie strength and shared community are absent for study-authored stimuli and the viewer's own; tie strength is zero where no tie exists; shared community is absent when the population has no communities
- [x] The vote action is replaced by upvote and downvote, and both are counted separately
- [x] A turn record carries its view, and a partition refuses a view whose counts disagree with engagement recorded at earlier ticks — including a like from the same tick
- [x] A partition refuses a view whose reply ancestry does not follow the reply chain from nearest parent to root
- [x] A world record joining a partition with its population refuses a manifest that is not that population's, and a view whose tie strength or shared community disagrees with the graph and communities
- [x] The representative partition records views with non-zero counts drawn from its own earlier turns, and round-trips

---

## Phase 9: The world step

**User stories**: 51, 52, 53, 54, 55, 56, 57

### What to build

The contract for what a world step produces and how a world's record survives a crash: a delta built from the trace's own record types, carrying one presentation per activated persona; a closed-tick record marking every fully recorded tick; and a degradation record for each budget rung applied to a world.

The world never numbers events and no world state crosses the boundary, so replaying recorded turns is the only way to rebuild a world.

### Acceptance criteria

- [x] A world delta carries the stimuli published, interventions applied, exposures dropped with the persona each was dropped for, and one presentation per activated persona and channel
- [x] Every dated element of a delta shares its tick, and a presentation's view must match its impression
- [x] No world-state type exists; the opening delta is the delta for tick zero
- [x] A partition requires ticks to close in order and refuses any record for a tick after that tick is closed
- [x] A degradation record carries its rung and the activation rate and tier-B freeze now in force; a partition refuses a rung that does not escalate
- [x] A paused lifecycle record must follow the pause rung
- [x] The representative partition closes its ticks and applies a degradation rung, and round-trips

---

## Phase 10: Model calls and guardrails

**User stories**: 58, 59, 60, 61, 62, 63

### What to build

The contract for what a model call returns and how its failures are recorded: a completion carrying its text, prompt hash, latency and the exact cost record it produced; cost records naming the route that served them; pinned fallback models; and guardrail retries and violations recorded in the trace.

A provider outage now substitutes only a model the configuration names, and a response that referred to something unshown is counted rather than logged.

### Acceptance criteria

- [x] A completion carries its text, template id, prompt hash, latency and the cost record it produced
- [x] A cost record names its route — primary, fallback or cache — and whether the cache served it is computed from the route
- [x] Model pins accept an optional fallback per role, and refuse a fallback for the embedding role or one identical to its primary
- [x] A partition accepts a billed model only as the primary on the primary route, the pinned fallback on the fallback route, or either on the cache route
- [x] A turn record lists at most one rejected prompt hash, distinct from the accepted one
- [x] A guardrail-violation record carries its impression, view, two distinct rejected prompt hashes and a rule from a closed set, and no reaction; it belongs to its impression's persona and tick, and its impression may not also appear in a turn
- [x] A partition verifies a violation's view as it verifies a turn's

---

## Phase 11: Run results

**User stories**: 64, 65, 66

### What to build

The contract for what a run returns: its registry entry and one outcome per world, each stating whether the world completed, is partial, or never started, the last tick it closed, and the degradation it underwent. The run's status is computed from its worlds. A sweep returns the same result.

### Acceptance criteria

- [ ] A run result carries one outcome per world, and its world ids are exactly the registry's
- [ ] A not-started world has closed no tick and applied no rung; a completed world has closed the final tick of its scenario's horizon; rungs escalate
- [ ] The run's status is computed — completed only when every world completed, partial otherwise — and the registry entry's status must agree
- [ ] There is no separate sweep result type

---

## Phase 12: The ontology

**User stories**: 67, 68, 69

### What to build

The two contracts the category ontology was missing: an attribute relevance order with the conditioning set first, so token budgets cut only non-conditioning attributes, and a mapping from each construct to its anchor set, so every elicitation is scored against the anchors its category names.

### Acceptance criteria

- [ ] The ontology's relevance order lists every declared attribute exactly once, and refuses an order in which a conditioning attribute is outranked by a non-conditioning one
- [ ] The ontology maps each construct to its anchor set
- [ ] A partition refuses an elicitation scored against any anchor set other than the one its ontology names for that construct
- [ ] A partition refuses a run configuration that does not pin every anchor set its ontology names
- [ ] The representative ontology ranks its attributes and names its anchor sets; the replay identities are re-pinned under contract 1.0.0
