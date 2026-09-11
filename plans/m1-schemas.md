# Plan: M1 `schemas` — the engine's contracts

> Source PRD: `docs/prd/M1-schemas.md`
> Binding decisions: `CONTEXT.md` (glossary), `docs/adr/0001`–`0003`. Where `FINAL_ARCH.md` disagrees with either, those win — the architecture document has not yet been reconciled.

## Architectural decisions

Durable across every phase:

- **Leaf rule** — the package imports nothing from the project, and only the validation library plus the standard library from outside. No numeric or dataframe dependency, ever. Enforced by a test, not by convention.
- **File organization** — one file per domain (base/identifiers, enumerations, errors, brief, persona, population, simulation, run, trace, report), with a single curated export surface as the only import path other modules use.
- **Model defaults** — every model rejects unknown fields, is frozen, rejects non-finite floats, and strips surrounding string whitespace. Container fields are tuples, frozensets or `FrozenDict` — list, dict and set annotations are refused when a class is defined, because freezing a model does not freeze a container inside it. Copying a model with updates re-validates the updates.
- **Canonical hashing** — sorted keys, compact separators, enumerations serialized by value, non-finite values rejected, per-class exclusion of outputs (observed cost, wall-clock timestamps), exclusions and version folding honoured at every nesting level, including inside sequences and mappings; set-valued fields sorted so hash-seed iteration order never leaks in; negative zero normalised so structures that compare equal hash equally; the contract version folded under a reserved key no field can occupy; misspelled or mistyped exclusions refused when a class is defined. Four hashes exist: brief, population, run configuration (which folds in the contract version), and graph.
- **Identity** — persona identity derives from the dataset row so cross-run joins need no lookup table; persona identity is `p-` followed by the dataset row identifier; run and stimulus identities are `run-` and `st-` followed by a lowercase ULID, so they sort by creation time; world identity derives from variant, replicate seed and population hash (ADR 0001).
- **Two provenance vocabularies** — one for where a brief statement came from, one for where a persona field came from. The second carries an explicit grounded value; grounding is never inferred from an absent key.
- **Audience versus community** — audiences are declared in inputs and referred to by name; communities are discovered and appear only in outputs. "Segment" and "stratum" are not used.
- **Validation guards boundaries, not inner loops** — three documented unvalidated-construction paths (trace writes, graph adjacency, per-row decode), fully validated only in continuous integration.
- **Errors carry exit codes** — the command line distinguishes a failed gate from a crash by exception class, not by string matching.
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

---

## Phase 2: The brief

**User stories**: 4, 7, 14, 18, 19, 21, 24, 37

### What to build

Everything needed for a real study brief to validate: claim sources, claims with evidence references, product information, price with currency, competitors, target market, named audience declarations, assumptions, and the category ontology that travels with them — the conditioning set, the completion policy, and the ordinal attribute scales.

At the end of this phase an actual brief file parses, and reordering its claims is caught rather than silently invalidating comparability.

### Acceptance criteria

- [ ] A representative brief file validates, and one with an unknown key is refused
- [ ] Claim identifiers are assigned automatically, are contiguous, and duplicates are refused
- [ ] Reordering claims changes the brief hash; reformatting whitespace or comments does not
- [ ] Price carries its currency and refuses a non-positive amount
- [ ] Audiences are declared by name and can be referenced by name without a population existing
- [ ] A brief declaring no audiences is valid, and the type records that audiences will be derived
- [ ] The category ontology declares its conditioning set, its completion policy, and its ordinal scales, and refuses a completion policy that lists a demographic attribute
- [ ] Evidence references carry a fetched-at time and content hash when present, and are optional when absent

---

## Phase 3: The population

**User stories**: 9, 10, 11, 12, 13, 15

### What to build

The contract for who is in a study: field origin stated on every projected field, persona source as a validated value, the persona split between the conditioning attributes its category requires and everything else, the distribution gate as a tagged union over categorical and ordinal tests, the gate report with its source mix, the population manifest, and the graph with its discovered communities.

This is the phase where the engine's central invariant becomes structural: a persona that cannot be conditioned, or one whose demographics were invented, cannot be constructed.

### Acceptance criteria

- [ ] A persona missing any attribute in its category's conditioning set is refused at construction
- [ ] A persona whose field origin marks a demographic or psychographic as synthesized is refused
- [ ] Every projected field states an origin; grounding is never represented by an absent key
- [ ] A gate result declares which test produced it rather than leaving the other test's fields null
- [ ] The ordinal gate exposes both the raw statistic and the similarity derived from it, named so the pass direction cannot be misread
- [ ] A gate result over an attribute whose origin is synthesized is refused
- [ ] Overall gate status is computed from its results and cannot be set directly
- [ ] The gate report carries the population's source mix alongside its distributions
- [ ] The population manifest records an achieved mix keyed by audience, and carries no stratum concept
- [ ] Communities appear only in output types and cannot be referenced from any input type
- [ ] Persona embeddings are referenced by position rather than stored inline, keeping the numeric library out of the package

---

## Phase 4: The run

**User stories**: 16, 17, 18, 20, 23, 27

### What to build

The contract for what is being run: the concept card, the scenario describing conditions with its tick unit and horizon, interventions, the budget, model pins, and the run configuration that binds variants to replicate seeds and a population.

The scenario carries no seed. World identity is derived. An unreproducible run cannot be expressed.

### Acceptance criteria

- [ ] A model pin that is empty, wildcarded, or version-floating is refused before anything else validates
- [ ] A scenario has no seed field, and the same scenario can be paired with different replicate seeds
- [ ] World identity derives from variant, replicate seed and population hash, and is stable across processes
- [ ] Two replicates of one variant produce different world identities; the same replicate reproduces the same one
- [ ] Price appears on the scenario only, typed with its currency, and nowhere else in the run
- [ ] Audience weights are refused unless they sum to one within tolerance
- [ ] A scenario declares its tick unit and horizon, and interventions are expressed in ticks against them
- [ ] Interventions at the same tick compose rather than replacing one another
- [ ] A representative sweep grid file validates and expands to distinct world identities

---

## Phase 5: The simulation

**User stories**: 22, 36

### What to build

The contract for what happens during a run: probability masses over the response scale, stimuli, exposures, impressions grouping a tick's exposures for one persona on one channel, reactions referencing both what was seen and what they were about, belief dimensions alongside per-claim credence, memory views, and elicitation results carrying the model that produced them.

This is the phase carrying ADR 0003 — a persona reacts to an impression, and a survey room impression is the one-exposure case of the same type.

### Acceptance criteria

- [ ] A probability mass containing a zero, a non-finite value, or a sum outside tolerance is refused
- [ ] An impression holds at least one exposure and no more than its channel's budget
- [ ] A survey-room impression holds exactly one exposure, using the same type as a feed impression
- [ ] Exposures retain their per-stimulus attention, reason and seen flag when grouped into an impression
- [ ] A reaction references the impression it saw and, separately, the stimulus it is about
- [ ] Belief levels are bounded to the unit interval and deltas to the signed unit interval
- [ ] Per-claim credence keys are refused unless they match the brief's claims exactly
- [ ] A stimulus authored by a persona and one authored by the study are the same type, distinguished by whether an author is present
- [ ] An elicitation result carries the embedding model that produced it, so a mismatch is detectable from the record alone
- [ ] There is no field anywhere that accepts a model-emitted numeric rating

---

## Phase 6: The trace

**User stories**: 5, 6, 28, 29, 30

### What to build

The append-only record's contract: event kinds, the event itself, its payload as a discriminated union over the eleven kinds, run registry entries pinning every hash needed for replay, and partition-level versioning with a lenient read path.

This is the hottest write path in the engine, so the phase also establishes the unvalidated-construction escape hatch and proves the round-trip holds at realistic volume.

### Acceptance criteria

- [ ] An event whose payload kind disagrees with its declared type is refused
- [ ] Each of the eleven payload kinds has a distinct type, and the union dispatches on the kind alone
- [ ] Events carry no seed field and no contract version field
- [ ] The contract version is recorded once per partition and in the run registry entry
- [ ] A partition written under an earlier contract version loads under a later one without error
- [ ] The strict write path and the lenient read path are separate entry points, and the lenient one is never used to write
- [ ] Events at realistic volume round-trip with ordering preserved by persona, tick and sequence
- [ ] Unvalidated construction is available, documented, and covered by a validated equivalent in continuous integration
- [ ] There is no field capable of storing a full prompt; only its parts and a hash
- [ ] A registry entry pins every hash and model identifier required to reproduce its run

---

## Phase 7: The report

**User stories**: 31, 32, 33, 34, 35, 36

### What to build

The contract for what the engine says: findings with their supporting records and the test that would disprove them, the trust statement stated once per run, the calibration reference it requires above the uncalibrated level, objection clusters, anomalies, and outcome digests carrying both audience-level and community-level distributions with their tick unit.

This is where the engine's honesty becomes structural rather than editorial.

### Acceptance criteria

- [ ] A finding without at least one supporting record is refused
- [ ] A finding without a disconfirming test is refused
- [ ] A finding carries no trust level and no provenance — only what varies per finding
- [ ] Trust is stated once per report, not per finding
- [ ] A trust level above uncalibrated without a calibration reference is refused
- [ ] Nothing in the package or repository can produce a calibration reference
- [ ] Per-finding confidence and run-level trust are separate fields that cannot be conflated
- [ ] An outcome digest carries both audience-level and community-level distributions
- [ ] An outcome digest carries its tick unit, and comparing digests across differing units is refused
- [ ] Polarization is defined over communities, with audience-level divergence reported separately
- [ ] Anomaly kinds are a closed set, and an anomaly carries the evidence that produced it
