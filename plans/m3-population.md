# Plan: M3 `population` — who is in the study

> Source PRD: `docs/prd/M3-population.md`
> Binding decisions: ADR 0002 (conditioning filters before sampling), ADR 0001 as amended (three seed streams), ADR 0004, ADR 0014 (study inputs drafted from the corpus), ADR 0015 (a population is built once and carried), `CONTEXT.md` (Relaxation, Audience, Community, Category Ontology). `FINAL_ARCH.md` §5.3 is reconciled with these; where anything still disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Two functions, one question** — `assess` answers "can this study be sampled, and is the sample sound?" with no model and no cost; `build` answers it and produces the population. Nothing else is public. The nine internal stages are not a public surface, and `PersonaPatchSource` stays a no-op seam because adding it later is a breaking change.
- **Eligibility is decided before sampling and never traded** — a row lacking any conditioning attribute never enters the candidate pool, and no shortfall, quota or relaxation may loosen the conditioning set (ADR 0002).
- **A shortfall is recorded, never silent** — widen one band, then drop the least relevant non-conditioning filter, then accept the shortfall, and fail only at zero. Each rung is a `Relaxation` on the gate report; the achieved mix always tells the truth.
- **The corpus seam yields decoded rows** — the packed format, the mapping from ontology vocabulary to dataset codes, and each attribute's value set are the adapter's knowledge. The conditioning filter is in the port's signature, so it cannot be forgotten.
- **A model may only choose what the corpus contains** — completion is a choice among real values, off-list answers are refused, and gates read grounded attributes only, so completion can never be judged against the distribution it was chosen to match.
- **Structure explains itself** — attribute homophily, weighted by the ontology's relevance order, is the primary tie signal; embedding cosine is an optional secondary term, off by default. A tie can always be justified from the attributes that produced it.
- **Study parameters are recorded, operational settings are not study parameters** — anything that changes what a study measured (homophily strength, seeds, thresholds) is carried in the manifest or the contracts. The environment configures how a run executes, never what it concluded.
- **Identity is structural, not floating-point** — tie strengths are quantised before becoming edges, because the graph hash covers them and a different numeric build would otherwise change a population's identity.
- **Built once, carried thereafter** — determinism is promised under a deterministic inference port; a live model makes a rebuild a different population, so replay loads the artifact rather than re-deriving it (ADR 0015).
- **Contract amendments come first** — module 1 owns the shapes, and nothing here can produce a `Relaxation`, a graph gate result or a manifest provenance field that does not exist yet. Two of the three amendment phases move pinned identities, which are re-pinned under 1.0.0 while it remains unreleased.
- **Test posture** — boundary tests through `assess` and `build` only, against a shape-driven synthetic source and a deterministic fake model. No network, no credentials, no dataset.

---

## Phase 1: Contracts — gates, relaxations and graph results

**User stories**: 5, 16, 20, 22

### What to build

The shapes this module's verdict needs, none of which exist. A `Relaxation` records a loosened audience filter — the rung, the filter as authored and as applied, the counts before and after, and the quota achieved — and travels on the gate report, because that is already where "is this sample acceptable" is answered.

Graph gates become a third kind of gate result, keyed by the check they performed rather than by an attribute, so one report carries every judgement and computes one verdict. "Zero isolates" stops being a gate and becomes an invariant of a valid population. And a digest gains the ability to say that polarization was not measurable, so a population that formed no communities is never reported as unpolarised.

### Acceptance criteria

- [x] A relaxation records its audience, its rung, the filter as authored and as applied, the rows matched before and after, and the share achieved
- [x] A gate report carries relaxations alongside its results, and a relaxation does not change the report's verdict
- [x] A graph gate result names its check, its measured value and its threshold, and computes whether it passed
- [x] One report holds distribution and graph results together, refuses two results for the same subject, and computes its overall verdict from all of them
- [x] A population carrying a graph is refused when any persona has no tie
- [x] A digest can state that polarization was not measurable, and a stated polarization that contradicts the communities it reports is refused
- [x] The pinned identities are unchanged by this phase, or deliberately re-pinned with the change noted

---

## Phase 2: Contracts — the manifest and what may be absent

**User stories**: 6, 12, 25

### What to build

What a population must be able to say about itself once the personas are no longer present. The manifest is what travels with runs and traces in place of the personas, so it is where the facts a reader cannot otherwise recover belong: the mix that was requested beside the mix achieved, which model completed sparse fields and under which template, what share of fields was synthesized, and the homophily strength the graph was built with.

This phase also makes two things optional that the contracts currently force: a persona's embedding, since embeddings become a secondary signal rather than the primary one, and an ontology's drafting provenance, which records that a model drafted it without moving the ontology's identity.

### Acceptance criteria

- [x] A manifest records the requested mix beside the achieved mix, and a requested mix that does not sum to one is refused
- [x] A manifest records which model completed sparse fields, under which template and template hash, and what share of projected fields was synthesized
- [x] A manifest that reports synthesized fields without naming what produced them is refused, and one reporting none may name nothing
- [x] A manifest records the homophily strength the graph was generated with
- [x] A persona may omit its embedding, and a population of personas without embeddings validates
- [x] An ontology may record which model drafted it, from which codebook and when, without changing its hash
- [x] The representative identities are re-pinned under 1.0.0 with the change noted

> Re-pinned 1.0.0: the representative personas no longer carry embeddings (the default path omits them), so the population and configuration hashes and every world id moved. The graph hash did not. The brief and ontology hashes are unchanged.

---

## Phase 3: Contracts — audiences with shares and predicates

**User stories**: 1, 2

### What to build

The study author chooses who is studied and in what proportion. An audience gains a share; shares are all-or-nothing across a brief and sum to one. Filters stop being single-value equality and become predicates — an exact value, a one-of set, or a range over an ordinal attribute's declared bands — so "trains at least weekly" and "18–34" are expressible rather than silently narrowed to one band.

Module 2 learns to read both from the authored YAML, the shipped example declares its own 60/40 split, and every identity that moves is re-pinned. A scenario that states no audience weights inherits the brief's shares, so the common case is stated once.

### Acceptance criteria

- [x] An audience may declare a share, and a brief where some audiences declare one and others do not is refused
- [x] Declared shares must sum to one
- [x] A filter may be an exact value, a one-of set, or a range, and a range over a non-ordinal attribute is refused
- [x] A range or set naming a value that is not one of the attribute's declared bands is refused, with the bands listed
- [x] The authored YAML expresses shares and every predicate form, and the shipped example declares its audiences' shares
- [x] A scenario that omits audience weights is read as weighting the brief's shares
- [x] Loading the example still produces the representative study, and every moved identity is re-pinned under 1.0.0

> Re-pinned 1.0.0: audiences now carry shares and predicates, so the representative brief hash moved, and with it the population and configuration hashes and every world id. The ontology and graph hashes are unchanged.

---

## Phase 4: The coreset seam

**User stories**: 3, 26 (foundation for both)

### What to build

The port through which the engine reaches persona rows, and the two sources every test runs against. `CoresetSource` answers three questions: which rows match a set of predicates *and* have every named attribute populated, what those rows contain, and what values an attribute can take. It yields decoded rows — the packed format belongs to an adapter that does not exist yet (§12).

The synthetic source generates rows from a declared shape: per attribute, its value set, the distribution over it, and how often it is populated. That single knob is what later phases use to force a failing gate, a starved quota or a structureless graph, so no scenario needs a flag. A small hand-written fixture source covers cases where a human should read input and expectation side by side.

### Acceptance criteria

- [x] Resolution asks for matching rows and required-populated attributes in one call, so eligibility cannot be requested without stating it
- [x] Predicates — exact, one-of, range — resolve against the source's own vocabulary
- [x] A source reports the value set for an attribute, and an attribute it does not know is refused by name
- [x] The synthetic source generates the same rows for the same shape and seed, in two processes
- [x] A shape controls each attribute's value distribution and how often it is populated
- [x] The fixture source serves a handful of committed rows readable beside the tests that use them
- [x] No core module imports a concrete source

---

## Phase 5: `assess()` — eligibility, a sample, and a verdict

**User stories**: 7, 8, 9, 13, 14, 15, 23

### What to build

The first real answer the module gives, and the cheapest: who is eligible, who was drawn, and whether the draw is sound. Eligibility applies the conditioning filter before anything is sampled, so a row missing a conditioning attribute never enters the pool. Quotas follow the brief's declared shares, sampling is seeded, and the achieved mix and source mix are recorded.

Gates then judge the sample: categorical marginals by chi-squared, ordinal attributes by similarity on their own band scale, reading grounded attributes only. Any failure rejects. No model is called, so this is free and fast — the check a user runs before spending anything.

### Acceptance criteria

- [x] A row missing any conditioning attribute never reaches the candidate pool, whatever its other attributes say
- [x] Sampling fills each audience's quota from its own eligible pool, and the achieved mix is recorded
- [x] The source mix of the sample is reported, so skew induced by the conditioning filter is visible
- [x] A skewed categorical marginal fails its gate, and a faithful one passes
- [x] An ordinal attribute is judged on its declared bands, and a shifted distribution fails
- [x] Gates read grounded attributes only
- [x] Any failing gate rejects the population
- [x] Assessing calls no model and opens no socket, and the same seed assesses identically twice

---

## Phase 6: The relaxation ladder

**User stories**: 3, 4, 5, 6

### What to build

What happens when the people a study asked for are not there in the numbers it asked for. A quota that cannot be filled climbs a fixed ladder — widen an ordinal predicate by one band, nearest first; drop the least relevant non-conditioning filter, using the ontology's own relevance order; accept the shortfall — and fails only when an audience matches nothing at all.

Every rung is recorded, so a reader can reconstruct what was asked for, what was applied, and what was obtained without rerunning anything. The conditioning set is never a rung.

### Acceptance criteria

- [x] A quota that cannot be filled widens its ordinal predicate by one band and records the rung
- [x] A widened predicate that still cannot fill drops the least relevant non-conditioning filter, chosen by the ontology's relevance order
- [x] A quota that still cannot fill is accepted short, and the achieved mix shows what was really drawn
- [x] An audience matching no rows at all is refused, naming its filters and the counts at each rung
- [x] No rung ever loosens the conditioning set
- [x] Relaxations do not change the gate report's verdict
- [x] A study whose audiences all fill records no relaxations

---

## Phase 7: Projection with constrained completion

**User stories**: 10, 11, 12

### What to build

Turning eligible rows into personas. The ontology's relevance order selects fields, the conditioning set lands in a persona's conditioning and everything else in its attributes, and every projected field states where it came from.

Sparse fields are completed by a model — but as a choice among the values the corpus already contains for that attribute, never as free text. An answer outside that set is retried once and then left absent, because a persona missing a non-conditioning attribute is valid and an invented vocabulary is not. What completed the fields is recorded on the manifest, since the personas will not always travel with it. This phase brings the chat port and its deterministic fake into the repository.

### Acceptance criteria

- [x] Every projected field states its origin, and a persona whose origins do not cover its fields is refused
- [x] Completion offers the attribute's own value set and accepts only a value from it
- [x] An off-list answer is retried once, then the field is left absent
- [x] No demographic or psychographic field is ever synthesized, whatever the completion policy says
- [x] Completion is batched rather than one call per persona
- [x] The manifest records the completing model, its template and hash, and the synthesized share
- [x] Under the deterministic fake, projecting the same sample twice produces identical personas
- [x] A population needing no completion calls no model

---

## Phase 8: The graph

**User stories**: 17, 18, 19, 20

### What to build

The social structure the study's diffusion runs over. A ring lattice supplies clustering, preferential attachment supplies a hub tail, and a homophily pass rewires a fraction of edges toward attribute-similar partners — similarity computed in attribute space and weighted by the ontology's relevance order, over sampled candidates rather than every pair.

Tie strengths are quantised before becoming edges, so a graph's identity is its structure rather than the numeric path that produced it. The graph is then judged — degree shape, clustering, connectivity — with its results carried in the same report as the distribution gates, and its measured assortativity reported so the influence of attributes on structure is a number rather than an assumption.

### Acceptance criteria

- [x] Generated graphs carry clustering and a hub tail rather than uniform degree
- [x] Two personas sharing their most relevant attributes are likelier to be tied than two who share none
- [x] A tie's strength can be explained from the attributes that produced it
- [x] Tie strengths are quantised, and the same graph built twice hashes identically
- [x] Every persona has at least one tie
- [x] Degree shape, clustering and connectivity are judged, and a failure rejects the population
- [x] The measured attribute assortativity is reported, and a degenerate graph whose communities merely restate the audiences is refused
- [x] Homophily strength is recorded, and two strengths produce two different graphs
- [x] Similarity is computed over sampled candidates, not all pairs

---

## Phase 9: Communities

**User stories**: 21, 22

### What to build

Who ended up talking to whom. Leiden runs seeded over the weighted graph across a resolution search, and the qualifying partition with the highest modularity is selected: enough communities, each holding at least a share of the population rather than a fixed count, so a small study is not structurally doomed.

A population that yields no qualifying partition is still a valid population. What changes is what may be said about it: polarization is reported as not measurable, never as zero, because a measured zero for an unmeasured quantity is the dishonesty the engine exists to avoid.

### Acceptance criteria

- [ ] Communities are detected from the graph and appear only in outputs, never read from an input
- [ ] Detection is seeded, and the same graph yields the same communities twice
- [ ] The resolution search selects the qualifying partition with the highest modularity, breaking ties deterministically
- [ ] A community must hold at least a share of the population, so the floor scales with study size
- [ ] Communities partition the population — every persona in exactly one
- [ ] A graph with no qualifying partition produces a population with no communities rather than a failure
- [ ] Such a population reports polarization as not measurable

---

## Phase 10: `build()` and determinism

**User stories**: 24, 25

### What to build

The whole path, and the guarantee that makes it trustworthy. `build` runs eligibility, sampling, relaxation, gating, projection, patching, graph generation and community detection, and returns the validated population beside its embedding array when embeddings are enabled.

Every randomised stage draws from its own stream spawned from the one population seed — sampling, rewiring, community detection — so no two stages can correlate and none is left unseeded. The reproducibility guarantee is stated with its condition attached: identical under a deterministic port, and against a live model a population is built once and carried.

### Acceptance criteria

- [ ] Building returns the validated population and, when embeddings are enabled, the array its personas index into
- [ ] The population validates against the brief and ontology it was built for, with every cross-persona invariant enforced
- [ ] The same brief, size and seed build an identical population twice under a deterministic port, hash for hash
- [ ] Three independent streams are spawned from the population seed, and changing one stage's draw does not shift another's
- [ ] The embedding array is never inside the contract, and a population without embeddings carries none
- [ ] The no-op patch seam is applied and changes nothing
- [ ] The reproducibility test states the deterministic-port condition in its name

---

## Phase 11: Perf and volume

**User stories**: 26

### What to build

The quickstart path has to be fast enough that a first-time user does not wonder whether it hung, and the graph has to hold its properties across seeds rather than on the one that was developed against.

### Acceptance criteria

- [ ] Building two thousand personas against the synthetic source and the deterministic fake completes under five seconds
- [ ] Rewiring's candidate sampling keeps graph generation from growing with the square of the population
- [ ] Graph gates hold across twenty seeds
- [ ] A larger population builds without loading every row it considered into memory at once
- [ ] The suite still runs with no network, no credentials and no dataset
