# PRD — M2 `brief`: intake

## Problem Statement

Module 1 defined every structure the engine exchanges, including the brief, the category ontology and the pack that joins them. Nothing constructs them. Today a study exists only as a Python literal in a test builder, which means the engine has contracts for a study nobody can author.

The gap is not "parse some YAML". It is that intake is where a study's reproducibility is either established or quietly lost. The brief hash pins what was tested; it feeds the population hash, the run configuration hash and every world id. If intake is non-deterministic — if what a brief hashes to depends on a web server's mood, a file's comment formatting, or which of two duplicate YAML keys the parser happened to keep — then every downstream reproducibility claim rests on nothing. Module 1 made the shapes honest; this module has to make the act of loading them honest.

There is also a narrower, sharper failure this module exists to prevent. A claim's source says where an assertion came from — asserted by the user, drawn from a public source, or assumed. Nothing currently stops a brief from marking marketing copy as `public_source` and citing nothing, and a report that repeats that label launders an assertion into a finding. Evidence is the difference, and evidence has to be real, retrieved, and pinned by content rather than by address.

## Solution

A small package, `jahan/brief`, with three public functions and no state.

`load_brief(path, ontology_dir) -> BriefPack` is a pure function of two files. It reads the author's YAML, refuses anything the contract refuses, resolves the category ontology by the exact version the brief names, joins the two into a `BriefPack`, and returns it. It opens no sockets and consults no clock, so the same files always produce the same brief.

`fetch_evidence(path, port)` is the only part that reaches the network, and it is a separate, commanded act. It retrieves each cited URL through `EvidencePort`, hashes exactly what came back, and writes the result into a sidecar beside the brief. The sidecar is committed with the study. Loading joins a claim's URL to its sidecar entry to build the `Evidence` the contract demands; a cited URL that was never fetched is refused (ADR 0013).

`assumptions_of(pack)` gathers what the study takes on faith — stated assumptions, claims marked assumed, and what the brief left unstated — so the assumption ledger is derived from the brief rather than maintained beside it.

After this module exists, a person can write a file, run the engine against it, and know that anyone else holding those files gets the same study.

## User Stories

**Authoring**

1. As a study author, I want to describe a product, its claims, its price and its audiences in one YAML file, so that starting a study does not require writing Python.
2. As a study author, I want a claim to cite a URL without my computing a SHA-256 by hand, so that evidence is something I can actually provide.
3. As a study author, I want unknown keys refused, so that a misspelled field fails loudly instead of being silently ignored.
4. As a study author, I want a repeated YAML key refused, so that a duplicated block never silently discards half my claims.
5. As a study author, I want errors that name the file and the exact field path, so that I can fix the file without reading a stack trace.
6. As a study author, I want claim identifiers assigned for me in order, so that I never invent one and never have to keep them contiguous.
7. As a study author, I want a missing ontology version to tell me which versions do exist, so that the most common first-run failure explains itself.

**Reproducibility**

8. As a maintainer, I want loading a brief to touch no network, so that a brief hash is a property of the files and not of the day.
9. As a reviewer, I want evidence identified by the content hash of what was retrieved, so that a URL that changes later cannot rewrite what a study was evidenced by.
10. As a maintainer, I want re-fetching to be explicit, so that a changed hash appears as a reviewable diff rather than a silent substitution.
11. As a maintainer, I want a partially failed fetch to keep what succeeded, so that one dead link does not discard nineteen good retrievals.
12. As a maintainer, I want the shipped example brief to hash to the identity already pinned for the representative study, so that the authored file and the pinned worlds cannot drift apart.
13. As a methodologist, I want a brief to name an exact ontology version and never a floating one, so that the conditioning set a study ran against is knowable forever.
14. As a maintainer, I want an ontology file whose declared category and version disagree with its path refused, so that filename and content can never diverge.

**Honesty of the record**

15. As an analyst, I want a claim marked `public_source` with no evidence refused, so that unevidenced copy cannot be presented as sourced.
16. As an analyst, I want a claim marked `assumed` that carries evidence refused, so that the word keeps its meaning.
17. As a reader of a report, I want the assumption ledger to include claims marked assumed and what the brief left unstated, so that reading only the `assumptions:` block cannot hide what a study took on faith.

**Engine integration**

18. As an engine developer, I want intake behind three functions with no classes and no state, so that module 3 depends on a surface it cannot reach past.
19. As an engine developer, I want the fetcher behind a port with an in-memory adapter, so that the whole suite keeps running with no network and no credentials.
20. As a CLI developer, I want every intake failure to be one exception class carrying exit code 2, so that a script can distinguish a bad input from a crash without matching strings.

## Implementation Decisions

**The interface.** Three public functions: `load_brief(path, ontology_dir) -> BriefPack`, `fetch_evidence(path, port, *, refetch=False) -> FetchReport`, and `assumptions_of(pack) -> tuple[Assumption, ...]`. No classes — there is no state to carry and no configuration to hold. Everything else is private: the YAML loader, the evidence join, sidecar read and write, ontology path resolution, and error formatting. `FetchReport` is local to the module because it crosses no module boundary; if it ever does, it moves to `schemas`.

**The authored file.** The YAML mirrors `ProductBrief` field for field, with exactly two divergences. A claim carries `evidence_url` rather than an `evidence` mapping, because the author supplies one thing and the sidecar supplies the other two. Claim identifiers are never authored; the contract already assigns `C1..Cn` by position, and forbidding authored ids makes a claim's identity its position — which is what the brief hash covers and why reordering claims is a comparability break rather than a cosmetic edit. No bare-string claims: a claim's source is mandatory, because defaulting it would manufacture provenance.

**Evidence.** `EvidencePort` is `fetch(url: str) -> bytes` and nothing more. Hashing, timestamping and sidecar writing live in the module, so there is exactly one implementation of what gets hashed and the in-memory adapter exercises it. The response body is hashed as received, with no normalization. Redirects are followed, but the recorded URL is the one the author cited — that is the provenance; the hash is what was actually seen. `fetched_at` comes from the clock inside `fetch_evidence` only, and never moves a hash, because the contract excludes it. The sidecar is written atomically — temporary file, then rename — so an interrupted fetch never leaves a half-written file behind. Entries whose URL no claim cites are ignored; the sidecar is a cache keyed by URL and may outlive an edit.

**The ontology.** `ontology_dir/<category>/<version>.json`, resolved to exactly one path and read. Both components come from validated `Identifier` fields, whose pattern admits no slash and requires an alphanumeric first character, so path traversal is closed by the type — provided validation happens before any path is built, which is a requirement on ordering, not a suggestion. The loaded file's own category and version must equal what was asked for. A missing file names the path it looked for and lists the versions present for that category. Floating versions are refused, for the same reason model pins refuse them.

**Source and evidence rules.** A `public_source` claim must carry evidence; an `assumed` claim must not; a `user_asserted` claim may. These are invariants of a brief regardless of how it was built, so they belong in `schemas` alongside the type, not in the YAML path where a test builder could walk past them. They add no field and change no serialization, so the pinned identities are untouched, and the representative brief already satisfies all three.

**Errors.** Every failure is a `GateFailure`, chained from its cause so a debugger still has the original traceback while the command line prints one line. Messages name the file and the field path within it, formatted from the contract's validation errors rather than dumped raw, with zero-based indices matching the file's own list order and a cap on how many are shown. Duplicate YAML keys are refused by the loader, because `safe_load` silently keeps the last one and no amount of schema validation can see what was dropped.

**The assumption ledger.** A derived view, not a stored record: `assumptions_of` returns `Assumption` values built from the brief's stated assumptions, its claims marked assumed, and its structural omissions — most importantly an undeclared target market, which the contract already exposes. Nothing is stored, so nothing can go stale or disagree with the brief, and no new type crosses a module boundary.

**Dependencies and packaging.** `pyyaml` joins the core dependencies. The HTTP adapter uses the standard library rather than adding a second HTTP stack for one request. This module creates `jahan/ports/`, holding port protocols and their adapters together so that no core module can import a concrete adapter; `EvidencePort` is its first protocol, and the module imports only the protocol.

## Testing Decisions

Boundary tests in `tests/boundary/brief/`, exercising the three public functions and nothing private. The suite's existing isolation applies unchanged: sockets refuse to connect and credentials are stripped for every test, so the HTTP adapter is never exercised in continuous integration by construction.

The load path is tested against the repository's own artifacts — `examples/protein_water.yaml` and `ontologies/beverage_protein/1.0.0.json` — which makes both tested artifacts rather than decorative ones. One test carries unusual weight: loading the example must produce a brief whose hash equals the value already pinned for the representative study, so the file a user authors and the identities the engine pins can never drift apart.

Failure cases build their trees in temporary directories and assert the refusal message: a missing ontology, an ontology whose content disagrees with its path, a floating version, a duplicate YAML key, an unknown key, a `public_source` claim with no evidence, an `assumed` claim with evidence, and a cited URL with no sidecar entry. The fetch path runs against the in-memory adapter: a partial failure writes its successes and reports its failures, a second run skips what is present, and a re-fetch replaces a hash visibly.

No golden run yet. Characterization snapshots need a pipeline to characterize, and arrive with the runner.

## Out of Scope

The `concepts brief fetch` command, which lands with the command-line module; until then the fetcher is called as a function, and the shipped examples carry committed sidecars. Line numbers in error messages, which require composing a node tree with position marks and can be added behind the same formatter later. Scenario and sweep-plan authoring — a `SweepPlan` joins a pack with a grid, and until the runner exists nothing needs to read one from a file. Ontology authoring tools; ontologies are hand-written JSON, versioned in the repository. Storing fetched bodies: the engine keeps the hash, not the document.

## Further Notes

Three statements in `FINAL_ARCH.md` are now out of date and are reconciled as part of this module: §5.2 still says evidence URLs are fetched at ingest, §4's port table does not list `EvidencePort`, and §9's dependency list has no YAML parser in it.

**Amended by M3.** Audiences gain a share and their filters gain predicates, so a study author chooses who is sampled and in what proportion rather than accepting whatever the data holds. Intake reads both; the shipped example declares them; the pinned identities re-pin. Specified in `docs/prd/M3-population.md`, built in phase 3 of `plans/m3-population.md`.

The build-phase table places `brief` in phase 1 and `population` in phase 0. Building intake first is a deliberate reordering: it is small, its contract already exists, and `population.build(brief, n, seed)` takes what it produces.
