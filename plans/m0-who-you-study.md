# Plan: M0 "Who you study" — describe the people, see who exists

> Source PRD: `docs/prd/M0-who-you-study.md`
> Binding decisions: ADR 0047 (a study's description drafts its audiences, never its category's conditioning set), ADR 0045 (the web layer derives nothing), ADR 0044 (an ontology is an immutable versioned study input), ADR 0014 (study inputs are drafted from the corpus and confirmed by a person), ADR 0004 (briefs reference their ontology by version), ADR 0020 (the catalog-constrained vocabulary), ADR 0017 (grounding is measured, extracted or synthesized), ADR 0021 (one OpenAI-compatible endpoint), ADR 0043 (single-operator local application), ADR 0016 (research instrument, research-only corpus). `CONTEXT.md` (Candidate Pool, Text Source, Coverage, Audience Preview, Audience, Source, Conditioning Set, Category Ontology, Extracted, Assumption Ledger).
> Interface reference: `~/jahan_sim/mockups/ontology/index.html` at mockups commit `8cc4be9` — the working mockup, with its server, measurements (`PLAN.md`, `CORPUS.md`, the evaluations) and browser check (`check_in_browser.mjs`). The page is built to its layout and wording; where its *behaviour* and this plan disagree, this plan wins.

## Architectural decisions

Durable across every phase:

- **No contract changes** — `CategoryOntology`, `Audience`, `Assumption` and the population build are unchanged. The step produces an ontology version and a brief's audiences and assumptions, exactly as a hand-written study does.
- **The category owns the conditioning set (ADR 0047)** — a reused category's is kept and locked; a new category's defaults to the **cross-survey core**, derived from the data as the attributes at least half of every survey source answered. A trait every group shares is a filter in each audience. Adding a declared attribute to a reused category publishes a new patch version with the conditioning set unchanged. The conditioning set leads the relevance order.
- **Counting lives in the engine** — every count the step shows (candidate pool, requirement and filter costs, value counts per source, audience head counts, what a text source would add, survey splits) is derived by an engine module; `web` serialises it (ADR 0045) and the interface renders it.
- **The persona value matrix** — every persona's value for every attribute, decoded through the corpus adapter so presence, overrides and missingness follow the draw's rules; built once per machine beside the coverage cache, keyed by shard digests, memory-mapped. Synthetic rows are left out.
- **Attribute embeddings** — one per attribute (label, category, values) with the pinned embedding model, cached by codebook digest and model, built in the background. Without them, or without an endpoint, search is by words and drafting is unavailable, and the interface says so.
- **API routes** — `GET /api/codebook` (labels, categories, what each measures; `mode=words|meaning`, `sources`), `GET /api/codebook/{attribute}/values` (counts per value and source, among the candidate pool), `POST /api/pool` (the candidate pool and what each requirement costs), `POST /api/audiences/preview` (audience head counts against quotas, source mix, filter costs, text-source additions, survey splits), `GET /api/categories` (reusable categories), `POST /api/describe` (the reading and the category match), `POST /api/draft` (audiences and ontology draft from a confirmed category). Saving stays on `POST /api/ontologies` and the brief's existing validation and launch routes.
- **Key models** — `CandidatePool` (people per source, and each requirement's cost per source), the existing `AudiencePreview` extended with quota, filter costs and text-source additions, `Reading` (product, groups with their traits, shared traits, topics), and `Draft` (audiences with filters, the questions put to the person, the changes awaiting acceptance, and each attribute's role: required, defines, describes).
- **The drafter is checked, not trusted** — each trait is matched among 20 candidates by meaning with their value counts in view; an attribute not offered, or a value outside its list, is refused; a trait matched differently with and without the rest of the description becomes a question for the person; guess words make a phrase a topic, enforced in code.
- **Text sources are opt-in** — Amazon reviewers and Wikipedia figures are off by default, labelled "read by a model from text, not surveyed", and admitting one writes an `assumed` entry to the assumption ledger.
- **One new page, built from phase 1** — "Who you study" is a new interface route, `/who`, at step 0 of the sidebar. It is built in the mockup's layout from the first phase, and every later phase fills in its own part of that page; the old ontology builder (`/ontology`) and the New-study page's audience panel keep working, untouched, until phase 11 retires them. No feature is built into a page that is later thrown away.
- **The page follows the mockup** — built from the frontend's existing design tokens and components, which are the mockups' own design system (the same colour tokens and `panel`, `chip`, `btn` classes). Its screens, regions and wording:
  - **Sidebar** — *Category* (id, version, reused or new); *Draw from* (presets All surveys · US public · Developers; one row per source with people, questions answered, and text sources labelled); *Study size*; *Candidate pool* (people, "of … in your sources have every required answer", source bar, "Requiring *X* removes *n*", naming a survey it empties); the list of what still blocks Continue; **Continue to study →**; *Start over*.
  - **Opening** — "Who do you want to study?", one sentence of guidance, one input with **Read it**, three example briefs, and the line saying every count is real.
  - **Reading and category card** — "I read this as a study of …", the groups with their traits, *Everyone*, *You want to know*, the rephrase hint, the category question, and **Yes — use its ontology** · **Start a new category** · *It's the same as…* · *Rephrase*.
  - **Audience card** — editable name, share %, the "changed from what you asked" badge, head count with "needs *quota*", filter chips each with "measures: …", **+ filter**, the value picker (checkbox, value, source bar, count) with "The corpus also asks this as", the question box ("I wasn't sure what you meant by …" with choices and "Neither — leave it out"), the source bar, and the notes (too few, text sources would add, what shrinks it, share from one survey, changes with **Accept** / **Undo**).
  - **Ontology table** — columns req · attribute (label, id, what it measures, the phrase it came from) · role (Required for everyone · Defines *audiences* · Describes everyone) · kind in plain words (Who they are · How they think · What they do · Money & work · How they decide · What they read & watch) · ordered ("yes?" for a guess) · remove; a reused category's own rows locked; **Find more attributes** opening search.
  - **Conversation** — each message, how its phrases were matched, what could not be found; the follow-up input docked at the bottom.
  - **Ready for a study** — the engine's verdict, whether the ontology is reused, a new version or a new category, the assumptions written to the brief, the ontology and the brief's audiences with downloads, and **Back to editing**.
- **Test posture** — deterministic behaviour runs offline against the packed-shard fixture and a fake chat port, and the suite reaches no network. Counts that depend on the real corpus are `real_corpus` tests pinned per source. The retrieval gate runs with the real corpus and an endpoint and is skipped, announced, without them. The page is driven in a real browser, and each phase checks its region against the mockup's.

---

## Phase 1: The page, and the codebook in plain words

**User stories**: 13, 16 (by words), 28

### What to build

The `/who` page in the mockup's layout — the sidebar with *Draw from*, the main column with audience cards authored by hand and the ontology table — and the first thing it needs from the engine: the codebook in words people use. The codebook already carries a label and a category for every attribute; this phase carries them through the API, searches over them in **Find more attributes**, and states in every chip and table row what an attribute measures, taken from its id and category. Kinds are shown in plain words. The coverage chips stop saying "dense" and "sparse", which the glossary avoids.

### Acceptance criteria

- [ ] `/who` renders the mockup's sidebar and main column, reachable as step 0 of the sidebar, while `/ontology` and the New-study page still work unchanged
- [ ] `GET /api/codebook` returns each attribute's label, category and what it measures, and never a path
- [ ] Word search covers labels and categories: "kids", "money" and "wealthy" each return a relevant attribute in the top five
- [ ] Every chip and table row states what the attribute measures, and an attitude, value or interest is marked as how people feel rather than what they do
- [ ] The ontology table has the mockup's columns, with kinds in plain words
- [ ] Without an endpoint the page searches by words and says that search by meaning is unavailable
- [ ] The coverage chips use the glossary's words, asserted over the interface source

---

## Phase 2: The candidate pool, and what each requirement costs

**User stories**: 12, 27

### What to build

The persona value matrix, built once per machine, and the first thing it answers: who can be drawn at all. `POST /api/pool` returns the candidate pool per source for the chosen sources and required attributes, and what each requirement removes — including when it removes a whole survey. It fills the sidebar's *Candidate pool* block.

### Acceptance criteria

- [ ] The matrix decodes every non-synthetic row through the adapter and agrees with the adapter's own decoding on the packed fixture, field by field
- [ ] It is keyed by shard digests: a changed shard rebuilds it rather than answering from the old one
- [ ] With the real corpus, age, region, education, employment and life stage keep 52,530 Stack Overflow and 11,754 GSS respondents, and adding marital status and children keeps no Stack Overflow respondent (`real_corpus`)
- [ ] Each requirement's cost is reported per source, and a requirement that empties a source says so by name, in the sidebar as the mockup shows it
- [ ] `web` performs no arithmetic over what it serves, asserted over the package as today
- [ ] A cold start without the matrix builds it in the background and the page says it is counting

---

## Phase 3: Audience head counts against quotas

**User stories**: 9, 10, 11

### What to build

`POST /api/audiences/preview` answers, for each audience: how many people match, against its quota at the study size; where they come from; and which filter is shrinking it and by how much. The sidebar gains *Study size*; each audience card gains its head count with "needs *quota*", its source bar, the running share total above the cards, and the notes for too few people, a shrinking filter ("use as a description instead") and a share drawn from one survey.

### Acceptance criteria

- [ ] An audience's quota is its share of the study size, and every card shows head count against quota
- [ ] Each card shows its source bar, and one drawn mostly from a single survey says which
- [ ] A filter whose removal would multiply an audience is named with both counts, and can be turned into a description in one click
- [ ] "Parent of young kids" counts 1,017 Stack Overflow respondents and no GSS respondent (`real_corpus`)
- [ ] An audience that matches nobody says that the people holding one of its answers never gave another, rather than showing zero alone
- [ ] The audience card matches the mockup's regions and wording, compared screenshot to screenshot

---

## Phase 4: Editing filters by picking values

**User stories**: 14, 15

### What to build

Clicking a filter chip opens the value picker in its card: every value with how many people in the candidate pool hold it, coloured by source, ticked rather than typed. Beneath it, "The corpus also asks this as" lists the other ways the corpus asks the same question, with how many people answered each; choosing one swaps the filter. **+ filter** picks from the ontology's attributes or opens search.

### Acceptance criteria

- [ ] `GET /api/codebook/{attribute}/values` returns every value of the attribute with its count per source among the candidate pool
- [ ] No value can be entered that is not in the attribute's list, asserted over the interface
- [ ] "The corpus also asks this as" lists alternatives with their head counts, and choosing one swaps the filter and declares the attribute
- [ ] Swapping "Parenthood" for "Children" on a parents audience raises its head count as the counts predict, in a real browser
- [ ] The picker matches the mockup's, compared screenshot to screenshot

---

## Phase 5: Text sources and the ledger

**User stories**: 10, 22, 23, 24

### What to build

In *Draw from*, Amazon reviewers and Wikipedia figures are unticked and labelled "read by a model from text, not surveyed". When surveyed people cannot fill an audience, its card says what each text source would add. Above the cards, audiences drawn mostly from different surveys are named in a note that says it will be recorded. Those, and any text source admitted, become `assumed` entries in the brief's assumption ledger, derived by the engine.

### Acceptance criteria

- [ ] Text sources are unticked by default and every count that includes their people is labelled
- [ ] An audience below its quota reports what each unticked text source would add, per source
- [ ] Admitting a text source writes an `assumed` ledger entry naming it and its contribution to the candidate pool
- [ ] Two audiences each drawn mostly from different surveys produce an `assumed` entry naming both audiences and both surveys, shown above the cards before Continue
- [ ] Every entry validates as the engine's `Assumption` and appears in the report of a study that carries it

---

## Phase 6: Search by meaning

**User stories**: 16, 17, 27

### What to build

Attribute embeddings, built in the background with the pinned embedding model, and **Find more attributes** ranking by meaning with attributes almost nobody answered sunk below comparable ones people did. Each result shows what it measures, how many people answered it and from which sources, what requiring it would do to the pool (for a new category), and **+ Describe** / **+ Require** as the mockup has them.

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

The page now opens as the mockup does: "Who do you want to study?", one input, **Read it**, and three example briefs. `POST /api/describe` reads the description into a `Reading` — the product, the groups with the traits that decide membership, traits every group shares, and topics — and matches the product against the categories `GET /api/categories` offers. The reading and category card shows it and asks the category question; the sidebar's *Category* block fills when it is answered. Nothing is drafted before the answer.

### Acceptance criteria

- [ ] The opening screen and the reading and category card match the mockup's, compared screenshot to screenshot
- [ ] The reading is shown before any draft, with **Rephrase** returning the text to the input
- [ ] A phrase with a guess word ("interested in", "possibly", "likely", "might", "tend to") is a topic, never a trait, whatever the model returned
- [ ] Only categories whose latest ontology names attributes the codebook carries are offered; `beverage_protein` is not
- [ ] The category match is a closed choice: the model can name an existing category or none, and anything else is refused
- [ ] A short follow-up that names one group is read as one group — the instructions' own examples never appear as groups (fake port replaying the recorded failure)

---

## Phase 8: Drafting from the description

**User stories**: 6, 7, 13, 19

### What to build

`POST /api/draft` turns a confirmed category and a reading into a `Draft` that fills the cards and the table. The category's own attributes come first — reused and locked in the table, or the cross-survey core for a new category. Each trait is matched among 20 candidates by meaning, with their value counts in view; the server refuses an attribute it did not offer and a value outside the attribute's list. A trait matched differently with and without the rest of the description appears as the card's question box. Traits become filters in their audiences, topics become descriptions, and no trait becomes a requirement. The conversation shows how each phrase was matched and what could not be found.

### Acceptance criteria

- [ ] A reused category's conditioning set is kept exactly and its rows are locked; a new category's is the cross-survey core, derived from the data
- [ ] A trait every group shares is a filter in each audience and never enters the conditioning set
- [ ] With a fake chat port, an invented attribute id and an out-of-list value are refused, and the refusal is shown in the conversation
- [ ] With a fake chat port that answers differently with and without context, the trait becomes a question with its choices, their head counts and "Neither — leave it out", and no filter is applied until the person answers; an answer applies wherever that phrase was asked
- [ ] Every filter in a draft names an attribute and values the codebook holds, asserted over drafts from the three example briefs
- [ ] The conversation and the question box match the mockup's, compared screenshot to screenshot

---

## Phase 9: Nothing changed behind your back

**User stories**: 18, 20, 21

### What to build

When a drafted audience falls below its quota, the draft moves its costliest filter to a description until it fits; the card carries the "changed from what you asked" badge and a note per change with the counts, **Accept** and **Undo**. Shares the person stated are kept; a group without one waits for it, marked in its card. The sidebar lists exactly what still stands in the way, and **Continue to study →** stays disabled until nothing does.

### Acceptance criteria

- [ ] Each change made to fit the data is shown with the counts before and after, and needs Accept or Undo
- [ ] Continue is blocked by, and the sidebar lists: an unconfirmed category, an unanswered question, an unaccepted change, shares missing or not summing to 100%, an audience below its quota
- [ ] Adding a group never rewrites a share the person stated
- [ ] An audience still below its quota at Continue cannot reach launch, so the engine's relaxation ladder never drops a filter the person did not see dropped

---

## Phase 10: Follow-ups

**User stories**: 4

### What to build

The follow-up input docked at the bottom of the page, as in the mockup, open once a category is confirmed. A follow-up that names a group adds a card, under the same category and with its own share; one that names no group ("all of them in North America") refines every existing audience. Each message is matched and checked as the first description was, and appears in the conversation.

### Acceptance criteria

- [ ] "Add a group of students" adds exactly one audience and asks for its share
- [ ] "All of them in North America" adds the filter to every audience and adds no audience
- [ ] A follow-up never changes the category or its conditioning set
- [ ] The conversation shows how each phrase of each message was matched, and what could not be found

---

## Phase 11: Ready for a study, into launch

**User stories**: 25, 26

### What to build

**Continue to study →** validates the ontology and audiences with the engine's own types and shows the mockup's *Ready for a study* screen: the verdict, whether the ontology is reused, a new version or a new category, the assumptions written to the brief, and both artefacts. It saves the ontology — the category's reused as it is, the next patch version adding the declared attributes, or a new category — and opens the launch form with the audiences, the assumptions, the sources and the study size. The old ontology builder and the New-study page's audience panel are retired.

### Acceptance criteria

- [ ] A draft that adds nothing to a reused category reuses its version; one that declares new attributes publishes the next patch version with the conditioning set unchanged; a new category starts at 1.0.0 — and no version a past study pinned is ever overwritten
- [ ] The saved ontology passes schema and codebook validation, and every audience and assumption validates as the engine's types
- [ ] The launch form arrives pre-filled with the audiences, assumptions, sources and study size, and launches
- [ ] The education-savings study is authored from a single description, reusing its category, and runs, driven in a real browser
- [ ] Both of the mockup's paths — a reused category, and a new one with a follow-up — run through the app in a real browser, and every screen in the page inventory is compared side by side with the mockup's
- [ ] `/ontology` and the New-study page's audience panel are gone, the sidebar's step 0 is "Who you study", and nothing links to the old pages
