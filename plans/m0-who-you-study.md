# Plan: M0 "Who you study" — describe the people, see who exists

> Source PRD: `docs/prd/M0-who-you-study.md`
> Binding decisions: ADR 0047 (a study's description drafts its audiences, never its category's conditioning set), ADR 0045 (the web layer derives nothing), ADR 0044 (an ontology is an immutable versioned study input), ADR 0014 (study inputs are drafted from the corpus and confirmed by a person), ADR 0004 (briefs reference their ontology by version), ADR 0020 (the catalog-constrained vocabulary), ADR 0017 (grounding is measured, extracted or synthesized), ADR 0021 (one OpenAI-compatible endpoint), ADR 0043 (single-operator local application), ADR 0016 (research instrument, research-only corpus). `CONTEXT.md` (Candidate Pool, Text Source, Coverage, Audience Preview, Audience, Source, Conditioning Set, Category Ontology, Extracted, Assumption Ledger). The working mockup and its measurements are in `~/jahan_sim/mockups/ontology/` (`PLAN.md`, `CORPUS.md`, the evaluations, `check_in_browser.mjs`); where the mockup and this plan disagree, this plan wins.

## Architectural decisions

Durable across every phase:

- **No contract changes** — `CategoryOntology`, `Audience`, `Assumption` and the population build are unchanged. The step produces an ontology version and a brief's audiences and assumptions, exactly as a hand-written study does.
- **The category owns the conditioning set (ADR 0047)** — a reused category's is kept and locked; a new category's defaults to the **cross-survey core**, derived from the data as the attributes at least half of every survey source answered. A trait every group shares is a filter in each audience. Adding a declared attribute to a reused category publishes a new patch version with the conditioning set unchanged. The conditioning set leads the relevance order.
- **Counting lives in the engine** — every count the step shows (candidate pool, requirement and filter costs, value counts per source, audience head counts, what a text source would add, survey splits) is derived by an engine module; `web` serialises it (ADR 0045) and the interface renders it.
- **The persona value matrix** — every persona's value for every attribute, decoded through the corpus adapter so presence, overrides and missingness follow the draw's rules; built once per machine beside the coverage cache, keyed by shard digests, memory-mapped. Synthetic rows are left out.
- **Attribute embeddings** — one per attribute (label, category, values) with the pinned embedding model, cached by codebook digest and model, built in the background. Without them, or without an endpoint, search is by words and drafting is unavailable, and the interface says so.
- **Routes** — `GET /api/codebook` (labels, categories, what each measures; `mode=words|meaning`, `sources`), `GET /api/codebook/{attribute}/values` (counts per value and source, among the candidate pool), `POST /api/pool` (the candidate pool and what each requirement costs), `POST /api/audiences/preview` (audience head counts against quotas, source mix, filter costs, text-source additions, survey splits), `GET /api/categories` (reusable categories), `POST /api/describe` (the reading and the category match), `POST /api/draft` (audiences and ontology draft from a confirmed category). Saving stays on `POST /api/ontologies` and the brief's existing validation and launch routes.
- **Key models** — `CandidatePool` (people per source, and each requirement's cost per source), the existing `AudiencePreview` extended with quota, filter costs and text-source additions, `Reading` (product, groups with their traits, shared traits, topics), and `Draft` (audiences with filters, the questions put to the person, the changes awaiting acceptance, and each attribute's role: required, defines, describes).
- **The drafter is checked, not trusted** — each trait is matched among 20 candidates by meaning with their value counts in view; an attribute not offered, or a value outside its list, is refused; a trait matched differently with and without the rest of the description becomes a question for the person; guess words make a phrase a topic, enforced in code.
- **Text sources are opt-in** — Amazon reviewers and Wikipedia figures are off by default, labelled "read by a model from text, not surveyed", and admitting one writes an `assumed` entry to the assumption ledger.
- **Test posture** — deterministic behaviour runs offline against the packed-shard fixture and a fake chat port, and the suite reaches no network. Counts that depend on the real corpus are `real_corpus` tests pinned per source. The retrieval gate runs with the real corpus and an endpoint and is skipped, announced, without them. The interface is driven in a real browser.

---

## Phase 1: The codebook in plain words

**User stories**: 13, 16 (by words), 28

### What to build

The builder shows code names and matches letters in them, so "kids" finds nothing. The codebook already carries a label and a category for every attribute; this phase carries them through the API, searches over them, and says what each attribute measures — a fact about the person, a habit, an attitude — taken from its id and category. The coverage chips stop saying "dense" and "sparse", which the glossary avoids.

### Acceptance criteria

- [ ] `GET /api/codebook` returns each attribute's label, category and what it measures, and never a path
- [ ] Word search covers labels and categories: "kids", "money" and "wealthy" each return a relevant attribute in the top five
- [ ] Every attribute shown in the builder states what it measures, and an attitude, value or interest is marked as how people feel rather than what they do
- [ ] Without an endpoint the builder searches by words and says that search by meaning is unavailable
- [ ] The coverage chips use the glossary's words, asserted over the interface source

---

## Phase 2: The candidate pool, and what each requirement costs

**User stories**: 12, 27

### What to build

The persona value matrix, built once per machine, and the first thing it answers: who can be drawn at all. `POST /api/pool` returns the candidate pool per source for the chosen sources and required attributes, and what each requirement removes — including when it removes a whole survey. The sidebar shows it for the ontology being edited.

### Acceptance criteria

- [ ] The matrix decodes every non-synthetic row through the adapter and agrees with the adapter's own decoding on the packed fixture, field by field
- [ ] It is keyed by shard digests: a changed shard rebuilds it rather than answering from the old one
- [ ] With the real corpus, age, region, education, employment and life stage keep 52,530 Stack Overflow and 11,754 GSS respondents, and adding marital status and children keeps no Stack Overflow respondent (`real_corpus`)
- [ ] Each requirement's cost is reported per source, and a requirement that empties a source says so by name
- [ ] `web` performs no arithmetic over what it serves, asserted over the package as today
- [ ] A cold start without the matrix builds it in the background and the page says it is counting

---

## Phase 3: Audience head counts against quotas

**User stories**: 9, 10, 11

### What to build

`POST /api/audiences/preview` answers, for each audience in a draft: how many people match, against its quota at the study size; where they come from; and which filter is shrinking it and by how much. The existing audience panel shows it live on hand-built audiences, and the sidebar gains the study size.

### Acceptance criteria

- [ ] An audience's quota is its share of the study size, and the page shows head count against quota for every audience
- [ ] Each audience's source mix is shown, and one drawn mostly from a single survey says which
- [ ] A filter whose removal would multiply an audience is named with both counts, and can be turned into a description in one step
- [ ] "Parent of young kids" counts 1,017 Stack Overflow respondents and no GSS respondent (`real_corpus`)
- [ ] An audience that matches nobody says that the people holding one of its answers never gave another, rather than showing zero alone

---

## Phase 4: Editing filters by picking values

**User stories**: 14, 15

### What to build

A filter is changed by ticking values in a list that shows how many people in the candidate pool hold each, coloured by source — never by typing a value. Beside it, the other ways the corpus asks the same question, with how many people answered each, can replace the filter in one click.

### Acceptance criteria

- [ ] `GET /api/codebook/{attribute}/values` returns every value of the attribute with its count per source among the candidate pool
- [ ] No value can be entered that is not in the attribute's list, asserted over the interface
- [ ] "The corpus also asks this as" lists alternatives with their head counts, and choosing one swaps the filter and declares the attribute
- [ ] Swapping "Parenthood" for "Children" on a parents audience raises its head count as the counts predict, in a real browser

---

## Phase 5: Text sources and the ledger

**User stories**: 10, 22, 23, 24

### What to build

Amazon reviewers and Wikipedia figures are offered off by default and labelled wherever their people are counted. When surveyed people cannot fill an audience, the preview says what each text source would add. Admitting one, and audiences drawn mostly from different surveys, become `assumed` entries in the brief's assumption ledger, derived by the engine and shown before the study continues.

### Acceptance criteria

- [ ] Text sources are unticked by default and every count that includes their people is labelled "read by a model from text, not surveyed"
- [ ] An audience below its quota reports what each unticked text source would add, per source
- [ ] Admitting a text source writes an `assumed` ledger entry naming it and its contribution to the candidate pool
- [ ] Two audiences each drawn mostly from different surveys produce an `assumed` entry naming both audiences and both surveys
- [ ] Every entry validates as the engine's `Assumption` and appears in the report of a study that carries it

---

## Phase 6: Search by meaning

**User stories**: 16, 17, 27

### What to build

Attribute embeddings, built in the background with the pinned embedding model, and search that ranks by meaning with attributes almost nobody answered sunk below comparable ones people did. Results show how well they match, how many people answered them and from which sources, and what requiring them would do to the pool. An attribute can be added to describe people without ever excluding anyone.

### Acceptance criteria

- [ ] Embeddings are cached by codebook digest and model; a different model builds a new cache rather than mixing vectors
- [ ] Ranking sinks attributes under 10% and 1% coverage in the chosen sources, and ranks one nobody in them answered last
- [ ] The retrieval gate: of the evaluation's 15 queries, at least 11 find an expected attribute first and 13 within the top five, surveyed sources only (real corpus and endpoint; skipped and announced without them)
- [ ] A described attribute never changes the candidate pool or any audience's head count
- [ ] While embeddings build, search falls back to words and says so

---

## Phase 7: Describe, then confirm the category

**User stories**: 1, 2, 3, 5, 8

### What to build

The step opens with one question and one input. `POST /api/describe` reads the description into a `Reading` — the product, the groups with the traits that decide membership, traits every group shares, and topics — and matches the product against the categories `GET /api/categories` offers. The page shows the reading and asks whether this is the same kind of product as an existing category, or a new one. Nothing is drafted before the answer.

### Acceptance criteria

- [ ] The reading is shown before any draft, with a way to rephrase
- [ ] A phrase with a guess word ("interested in", "possibly", "likely", "might", "tend to") is a topic, never a trait, whatever the model returned
- [ ] Only categories whose latest ontology names attributes the codebook carries are offered; `beverage_protein` is not
- [ ] The category match is a closed choice: the model can name an existing category or none, and anything else is refused
- [ ] A short follow-up that names one group is read as one group — the instructions' own examples never appear as groups (fake port replaying the recorded failure)

---

## Phase 8: Drafting from the description

**User stories**: 6, 7, 13, 19

### What to build

`POST /api/draft` turns a confirmed category and a reading into a `Draft`. The category's own attributes come first — reused and locked, or the cross-survey core for a new category. Each trait is matched among 20 candidates by meaning, with their value counts in view; the server refuses an attribute it did not offer and a value outside the attribute's list. A trait matched differently with and without the rest of the description becomes a question with the choices, their head counts and "neither". Traits become filters in their audiences, topics become descriptions, and no trait becomes a requirement.

### Acceptance criteria

- [ ] A reused category's conditioning set is kept exactly and cannot be edited in the step; a new category's is the cross-survey core, derived from the data
- [ ] A trait every group shares is a filter in each audience and never enters the conditioning set
- [ ] With a fake chat port, an invented attribute id and an out-of-list value are refused, and the refusal is shown
- [ ] With a fake chat port that answers differently with and without context, the trait becomes a question and no filter is applied until the person answers; an answer applies wherever that phrase was asked
- [ ] Every filter in a draft names an attribute and values the codebook holds, asserted over drafts from the three example briefs

---

## Phase 9: Nothing changed behind your back

**User stories**: 18, 20, 21

### What to build

When a drafted audience falls below its quota, the draft moves its costliest filter to a description until it fits, and flags each move with its counts for the person to accept or undo. Shares the person stated are kept; a group without one waits for it. Continue lists exactly what still stands in the way.

### Acceptance criteria

- [ ] Each change made to fit the data is shown with the counts before and after, and needs Accept or Undo
- [ ] Continue is blocked by, and lists: an unconfirmed category, an unanswered question, an unaccepted change, shares missing or not summing to 100%, an audience below its quota
- [ ] Adding a group never rewrites a share the person stated
- [ ] An audience that is still below its quota at Continue cannot reach launch, so the engine's relaxation ladder never drops a filter the person did not see dropped

---

## Phase 10: Follow-ups

**User stories**: 4

### What to build

The same input stays open after the first draft. A follow-up that names a group adds it, under the same category and with its own share; one that names no group ("all of them in North America") refines every existing audience. Each follow-up is matched and checked as the first description was.

### Acceptance criteria

- [ ] "Add a group of students" adds exactly one audience and asks for its share
- [ ] "All of them in North America" adds the filter to every audience and adds no audience
- [ ] A follow-up never changes the category or its conditioning set
- [ ] The conversation shows how each phrase of each message was matched, and what could not be found

---

## Phase 11: One step, into launch

**User stories**: 25, 26

### What to build

"Who you study" replaces the ontology builder and the New-study page's audience panel. Continue validates the ontology and audiences with the engine's own types, and saves: the category's ontology reused as it is, a new version of it adding the declared attributes, or a new category. The launch form opens with the audiences, the assumptions, the sources and the study size.

### Acceptance criteria

- [ ] A draft that adds nothing to a reused category reuses its version; one that declares new attributes publishes the next patch version with the conditioning set unchanged; a new category starts at 1.0.0 — and no version a past study pinned is ever overwritten
- [ ] The saved ontology passes schema and codebook validation, and every audience and assumption validates as the engine's types
- [ ] The launch form arrives pre-filled with the audiences, assumptions, sources and study size, and launches
- [ ] The education-savings study is authored from a single description, reusing its category, and runs, driven in a real browser
- [ ] The old ontology builder route and audience panel are gone, and nothing links to them
