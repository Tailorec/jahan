# Plan: M2 `brief` — intake

> Source PRD: `docs/prd/M2-brief.md`
> Binding decisions: ADR 0013 (pure intake, evidence fetched separately), ADR 0004 (briefs reference their ontology by version), `CONTEXT.md` (glossary). Where `FINAL_ARCH.md` disagrees, the ADRs win — §5.2, §4 and §9 are reconciled by the phases that contradict them.

## Architectural decisions

Durable across every phase:

- **Intake is pure** — loading a brief is a function of two files. No sockets, no clock, no environment. The same files always produce the same brief, and therefore the same brief hash, on any machine.
- **Evidence is fetched separately into a sidecar** — the author's file carries the URL a claim cites; a machine-written `<brief>.evidence.json` beside it carries the content hash and the moment of retrieval; loading joins them. A cited URL that was never fetched is refused, and re-fetching is explicit (ADR 0013).
- **The authored file mirrors the contract** — the YAML is `ProductBrief` field for field, with exactly two divergences: `evidence_url` in place of the `evidence` mapping, and claim identifiers never authored. Not an authoring language; two exceptions that fit in a sentence.
- **Ontologies resolve by exact version to one path** — `ontology_dir/<category>/<version>.json`, read directly, never scanned. The file's declared category and version must equal what was asked for, and no version may float.
- **Invariants live with the type** — a rule true of every brief regardless of how it was built belongs in `schemas`, not in the YAML path, where a test builder would walk straight past it.
- **One error class** — every intake failure is a `GateFailure` chained from its cause, carrying a message that names the file and the field path within it. The command line distinguishes a bad input from a crash by exception class, never by matching strings.
- **Three functions, no state** — `load_brief`, `fetch_evidence`, `assumptions_of`. No classes, no loader object, no configuration. Everything else is private to the module.
- **Ports hold protocols and adapters together** — core modules import protocols only, so no core module can reach a concrete adapter. `EvidencePort` is the first protocol; its in-memory adapter is what every test runs against.
- **Derived, never stored** — the assumption ledger is gathered from the pack on demand, so it cannot go stale or disagree with the brief it describes.
- **Test posture** — boundary tests through the three public functions, never private helpers. The happy path runs against the repository's own shipped artifacts, so they are tested rather than decorative; failures build their trees in temporary directories and assert the refusal. The suite keeps running with no network and no credentials.

---

## Phase 1: A brief loads end to end

**User stories**: 1, 8, 18, 20

### What to build

The first study anyone can author, and the narrowest path that turns it into the structure the engine consumes: a YAML brief on disk, a versioned category ontology on disk, and `load_brief(path, ontology_dir) -> BriefPack` joining them.

Claims carry no evidence yet — that path arrives in phase 5 — so this slice proves the whole spine: read a file, refuse what the contract refuses, resolve the ontology the brief names, return a validated pack. The ontology moves out of test fixtures into `ontologies/` as a real shipped artifact, and `tests/boundary/brief/` is created as the repository's first layer-2 test directory.

### Acceptance criteria

- [x] A brief authored as YAML loads into a `BriefPack` whose brief, ontology and audiences are the ones the file describes
- [x] Loading opens no socket and reads no clock, and the suite's existing isolation proves it
- [x] The shipped ontology is loaded from `ontologies/`, and the example brief from `examples/`, by the same call a user would make
- [x] A brief naming an ontology version that does not exist raises `GateFailure`, not a file-not-found traceback
- [x] A brief the contract refuses — an unknown key, a missing required field, a malformed price — raises `GateFailure`
- [x] The module's public surface is one function; nothing else is importable from it yet
- [x] `pyyaml` is a declared dependency

---

## Phase 2: Refusals a human can act on

**User stories**: 3, 4, 20

### What to build

The difference between a module a person can use and one they abandon. Every failure names the file and the exact path within it, formatted from the contract's own validation errors rather than dumped raw, and capped so a broken file produces a readable list rather than a wall.

This phase also closes a silent-data-loss hole the schema cannot see: `safe_load` keeps the last of a repeated key, so a brief with two `claims:` blocks loses one without a whisper — and the brief hash would happily pin the truncated study.

### Acceptance criteria

- [x] A validation failure names the file and the field path, with list indices matching the file's own order
- [x] Several failures in one file are reported together, capped, with the number omitted stated
- [x] A repeated YAML key is refused, naming the key
- [x] A file that is not a mapping at its top level, or is empty, is refused as such
- [x] Malformed YAML is refused with a `GateFailure` rather than a parser traceback
- [x] Every refusal chains its cause, so the original error survives for a debugger while the message stays one line

---

## Phase 3: The ontology resolves strictly

**User stories**: 7, 13, 14

### What to build

The ontology is the shared artifact that makes two studies in a category comparable (ADR 0004), so resolving it is where drift gets caught. A brief names an exact version; that version resolves to exactly one path; the file found there must declare the category and version it sits under.

The failure this phase makes good is the one a new user hits first — a version that isn't there — which should answer its own question by naming what does exist.

### Acceptance criteria

- [x] A brief naming a floating version — `latest`, a wildcard, or a range — is refused, as model pins are
- [x] An ontology file whose declared category or version disagrees with its path is refused, naming both
- [x] A missing version names the path it looked for and lists the versions present for that category
- [x] A category with no directory at all is refused distinctly from a category whose directory lacks that version
- [x] The category and version used to build a path are validated identifiers first, so no brief can address a file outside the ontology directory

---

## Phase 4: Source and evidence rules

**User stories**: 15, 16

### What to build

The narrow failure this module exists to prevent: unevidenced copy presented as sourced. A claim drawn from a public source must be able to name it; a claim marked assumed must not carry evidence, because the word means "taken as true without it".

These are invariants of a brief however it was built, so they land in `schemas` beside the type rather than in the YAML path. They add no field and change no serialization, so the pinned identities do not move, and the representative brief already satisfies them.

### Acceptance criteria

- [x] A claim whose source is `public_source` and which carries no evidence is refused, by the contract itself
- [x] A claim whose source is `assumed` and which carries evidence is refused
- [x] A claim whose source is `user_asserted` is accepted with or without evidence
- [x] The refusals hold for a brief built in Python, not only one loaded from YAML
- [x] Every pinned identity is unchanged, and the representative brief and example still validate

---

## Phase 5: Evidence joins from the sidecar

**User stories**: 2, 5, 6, 9, 12

### What to build

The author writes a URL; the sidecar supplies what was actually retrieved; loading joins them into the `Evidence` the contract demands. A claim citing a URL with no sidecar entry is refused — cite a source, prove you read it — while a claim citing nothing remains perfectly valid.

With evidence in place the example brief becomes the representative study in full, which lets this phase carry the plan's load-bearing test: the file a user authors must hash to the identity already pinned for that study, so authored input and pinned worlds cannot drift apart.

### Acceptance criteria

- [x] A claim carrying `evidence_url` loads with its `Evidence` built from the sidecar entry for that URL
- [x] A claim citing a URL absent from the sidecar is refused, naming the URL
- [x] A sidecar entry no claim cites is ignored, and does not affect what loads
- [x] A claim carrying no URL loads with no evidence
- [x] Claim identifiers are assigned in file order, and a brief that authors its own is refused
- [x] Loading the example brief produces a brief whose hash equals the value pinned for the representative study
- [x] A missing or malformed sidecar is refused as such, distinctly from a missing entry

---

## Phase 6: Evidence is fetched through a port

**User stories**: 10, 11, 19

### What to build

The only part of the module that reaches the network, and the reason it can stay out of everything else. `simcore/ports/` is created here, holding the `EvidencePort` protocol together with both adapters — an in-memory one that every test runs against, and a standard-library HTTP one that continuous integration never exercises by construction.

`fetch_evidence` retrieves each cited URL, hashes exactly what came back, and writes the sidecar atomically. It reports what it fetched, what failed and what it skipped, so twenty claims with one dead link still leave nineteen retrievals on disk.

### Acceptance criteria

- [x] The port's whole surface is retrieving bytes for a URL; hashing, timestamping and writing live in the module
- [x] Fetching writes a sidecar entry per cited URL, keyed by the URL the author cited
- [x] A run where some URLs fail writes the successes, reports the failures, and can be re-run to complete
- [x] A second run skips URLs already recorded, and leaves their hashes untouched
- [x] An explicit re-fetch replaces an entry, and a changed hash is visible in what the run reports
- [x] An interrupted write never leaves a partial sidecar behind
- [x] The retrieved bytes are hashed as received, and the body itself is not stored
- [x] No core module imports a concrete adapter

---

## Phase 7: The assumption ledger

**User stories**: 17

### What to build

What a study takes on faith, gathered from the pack rather than maintained beside it: the brief's stated assumptions, the claims it marks as assumed, and what it leaves unstated — most importantly an undeclared target market, which means the whole population was assumed to be the audience.

Reading only the `assumptions:` block hides two of those three, which is exactly how a caveat goes missing from a report.

### Acceptance criteria

- [x] Stated assumptions appear in the ledger unchanged
- [x] A claim marked `assumed` appears in the ledger, carrying its own text
- [x] A brief that declares no audiences contributes an entry saying the target market was assumed
- [x] A brief that declares audiences contributes no such entry
- [x] The ledger is derived on demand and stored nowhere, so it cannot disagree with the brief it describes
- [x] The ledger introduces no new type crossing a module boundary
