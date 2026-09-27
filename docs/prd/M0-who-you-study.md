# PRD — M0 "Who you study": describe the people, see who exists

## Problem Statement

A study is only as good as the people it draws, and today nobody authoring one can see who they are drawing.
The corpus is 999,847 personas described by 1,290 attributes. A study's audiences are filters over those
attributes, declared against a category ontology, and the ontology builder asks its author to pick attributes
from a list of 1,290 code names they have never seen.

What the author cannot see is the shape of the data, which decides everything. Measured over the whole release
(every one of the 599,847 personas based on a real person; the 400,000 synthetic rows are never drawn):

* **It is not one population but six.** Four surveys — Stack Overflow (113,120 people), the US General Social Survey
  (63,532), PRISM (1,487) and a real human survey (355) — and two **text sources**, whose every field a model read
  from text: Amazon reviewers (97,915) and Wikipedia figures (323,438), who are notable people from Wikidata,
  including mythological and fictional ones. By default a study draws only the 178,494 surveyed people.
* **Each survey asked different questions.** The General Social Survey answers 18 attributes, Stack Overflow 784.
  Only **four** attributes are answered by at least half of both: age, region, education and employment.
* **Combining attributes across surveys collapses.** Age, region, education, employment and life stage keep 52,530
  Stack Overflow and 11,754 GSS respondents; adding marital status and children removes every Stack Overflow
  respondent. Six attributes spread across both surveys leave 277 surveyed people.
* **Values live in one source.** No GSS respondent is "High income" — the survey's scale stops at Upper-middle —
  and 918 of the 938 surveyed people who are come from Stack Overflow, which never asked about religion. "High
  earners who are religious" returns 10 people although both attributes look well covered.
* **Lifestyle is almost all text.** Exercise frequency: 339 surveyed people, 116,422 from text sources.

The builder hides all of it. Its search matches letters in code names — "kids", "money", "salary" and "wealthy" find
nothing, because the attributes are `demo_children_count` and `demo_household_income`. Audience values are typed by
hand. Coverage is shown per attribute, which cannot reveal a collapse that only happens in combination. Where the
people came from appears after the draw, on the population page.

The damage is already on record. The education-savings study compared parents of young kids — 185 Stack Overflow
respondents and 15 Wikipedia figures — with retirees, 130 of whom of 150 came from the General Social Survey, so every
difference it found was also a difference between two surveys, and some of its "parents" were encyclopedia entries.
Its ontology requires `life_stage`, which only 19% of GSS respondents answered, so every later study of that
category inherits a pool that excludes four in five of them.

Two risks come with the obvious fix. A language model can draft audiences from a description, but in the working
mockup it read the same description differently on different runs — "early career" became *Seniority: Mid …
C-suite* once, "parent" vanished from "busy parents who work full time" on others — invented attribute ids when
given the whole codebook, and copied an example from its own instructions into its answer. And a friendly screen
makes weak evidence look strong: a text source's people or a two-survey comparison look exactly like a sound
audience unless something says otherwise.

## Solution

One step, **"Who you study"**, replacing the ontology builder (step 0) and the New-study page's audience panel. It
produces the same two artefacts the engine reads today — a category ontology version and a brief's audiences — and
changes neither contract.

1. **Describe.** The page opens with one question, "Who do you want to study?", and one input. The author writes
   what they are testing, the groups, what makes someone belong, and what they want to know.
2. **Read, and confirm the category.** The description is read into groups with the traits that decide membership,
   traits every group shares, and topics that matter but exclude no one. The reading is shown before anything is
   drafted, with the question the author must answer: *same kind of product as an existing category — reuse its
   ontology — or a new category?*
3. **Draft.** Each trait is matched to an attribute and values the corpus holds, counted against the real data, and
   placed: filters in each audience; descriptions for the topics. The required set belongs to the category — reused
   as it is, or the cross-survey core for a new one (ADR 0047).
4. **Edit.** Audience cards show head counts against each audience's quota, where the people come from, what each
   filter measures and costs, and every question and change the draft is waiting on. Filters are edited by picking
   values from lists with counts, or swapped for another way the corpus asks the same thing. Search by meaning finds
   more attributes. Follow-ups in the same box add groups or refine them all.
5. **Continue.** The engine validates the ontology and audiences with its own types; caveats are written into the
   brief's assumption ledger; the launch form opens with the audiences, the sources and the study size.

The design was built as a working mockup against the real corpus and real models before this PRD
(`../mockups/ontology/`: the page, its server, the full-corpus analysis `CORPUS.md`, the retrieval evaluations, and
`PLAN.md` with every decision and measurement). It was grilled against the glossary and the ADRs on 2026-09-27;
ADR 0047 and the glossary entries **Candidate Pool** and **Text Source** came out of that.

## User Stories

**Describing who to study**

1. As a researcher, I want to describe who I want to study in my own words, so I do not have to learn 1,290
   attribute names before I can start.
2. As a researcher, I want to see how my description was read — the groups, the traits that put someone in each,
   what applies to everyone, and what I only want to know about them — before anything is built, so I can rephrase
   when something I meant is missing.
3. As a researcher, I want words like "possibly", "likely" or "interested in" treated as things to describe rather
   than filters, so a guess never shrinks my audience.
4. As a researcher, I want to add a group or refine every group in follow-up messages, so I can build a study in
   conversation instead of starting over.

**The category**

5. As a researcher, I want to be asked whether my product is the same kind as an existing category, so studies that
   should be compared share an ontology and ones that should not, do not.
6. As a researcher, I want a new category to require only what every survey asked most people, so the first study of
   a category cannot shut a survey out of every later one.
7. As a researcher reusing a category, I want its required attributes kept as they are and shown with what they
   cost, so I know what the category already excludes and cannot change it by accident.
8. As a researcher, I want a category whose ontology names attributes the corpus does not have never to be offered.

**Seeing who exists**

9. As a researcher, I want every audience to show how many people match, against how many it needs at my study
   size, so I know before launch whether it can be drawn.
10. As a researcher, I want to see which surveys an audience's people come from, and to be told when two audiences
    come mostly from different surveys, so I do not mistake a difference between surveys for a difference between
    people.
11. As a researcher, I want to be told which filter is shrinking an audience, and by how much, so I can fix the one
    that matters.
12. As a researcher, I want the candidate pool — everyone who carries every required attribute — shown with what
    each requirement costs, including when it removes a whole survey.
13. As a researcher, I want every filter to say what it measures — a fact about the person, a habit, an attitude — so
    I notice when "owns an electric car" was matched to how someone feels about electric cars.

**Editing**

14. As a researcher, I want to change a filter by ticking values from a list that shows how many people hold each
    and from which survey, never by typing a value.
15. As a researcher, I want the other ways the corpus asks the same question offered beside a filter, with their head
    counts, so I can swap "Parenthood" (a few thousand people) for "Children" (tens of thousands) in one click.
16. As a researcher, I want to search attributes by meaning, with the ones almost nobody answered sunk below the
    ones people did, so "kids" finds children and "money" finds income.
17. As a researcher, I want to add an attribute that only describes people without it ever excluding anyone.

**Nothing changed behind my back**

18. As a researcher, when the draft had to change an audience to make it drawable, I want to be told what it changed
    and why, with the counts, and to accept or undo each change before I can continue.
19. As a researcher, when the drafter was not sure what I meant, I want to be asked — with the choices side by side,
    their head counts, and "neither" — rather than have it guess.
20. As a researcher, I want the shares I stated kept when I add a group, and to be asked for the new group's share.
21. As a researcher, I want Continue to list everything still in the way — an unanswered question, an unaccepted
    change, shares that do not add up, an audience too small for its quota.

**Text sources and caveats**

22. As a researcher, I want Amazon reviewers and Wikipedia figures off by default and labelled "read by a model from
    text, not surveyed" wherever their people appear.
23. As a researcher, when surveyed people cannot fill an audience, I want to be told what each text source would add,
    so I can decide with the numbers in front of me.
24. As a researcher, I want admitting a text source, and comparing audiences drawn from different surveys, written
    into the brief's assumptions automatically, so every report of the study states it.

**Continuing**

25. As a researcher, I want Continue to hand the launch form my audiences, my sources and my study size.
26. As a researcher, I want to know whether my study reuses its category's ontology as it is, makes a new version of
    it, or starts a new category — and never to overwrite a version a past study pinned.

**Operating it**

27. As the operator, I want the per-machine data this step needs built once, in the background, keyed so a changed
    corpus or embedding model rebuilds it rather than answering from a stale copy.
28. As the operator, I want the step to work without a model endpoint — search by words, no drafting — and to say so.

## Implementation Decisions

**No contract changes.** `CategoryOntology`, `Audience`, `Assumption` and the population build are unchanged. The
step produces an ontology version (ADR 0044) and audiences and assumptions for the brief, exactly as a hand-written
study would.

**The category owns the required set (ADR 0047).** A reused category's conditioning set is kept and locked; a new
category's defaults to the **cross-survey core**, computed from the data as the attributes at least half of every
survey source answered (today age, region, education, employment). A trait every group shares is a filter in each
audience. Adding a declared attribute to a reused category publishes a new patch version with the conditioning set
unchanged; changing a category's conditioning set is a separate, deliberate action outside this step. The required
set leads the relevance order, as the schema already requires.

**The category is confirmed before anything is drafted.** The product is read from the description and matched
against existing categories as a closed choice. Only categories whose latest ontology names attributes the codebook
carries are offered (`beverage_protein`, a test fixture naming `age` and `sex`, is not).

**The persona value matrix.** Every persona's value for every attribute, decoded through `HfCoresetSource` so
presence, overrides and missingness follow the same rules as a draw: 1,290 × 599,847, 774 MB, built in about two
minutes at 3.2 GB peak. It lives in `ports` beside the coverage cache, keyed by shard digests, memory-mapped rather
than held by the API process, and it generalises `coverage.py`. Every count this step shows — candidate pool, what
each requirement and filter costs, head counts per value and per source, what a text source would add — is vector
work over it, in milliseconds.

**Counts are derived in the engine, never in the web layer (ADR 0045).** The draft state, value counts, source mixes
and the survey-split judgement are computed by an engine module and served; `web` serialises them and the interface
renders them. The assumption-ledger entries for survey splits and text sources are produced by the engine too.

**Attribute embeddings.** One embedding per attribute — its label, category and values — with the run's pinned
embedding model, cached by codebook digest and model: 1,290 texts, about 24 minutes once at Titan v2's default quota,
about $0.001. Built in the background; until it exists, and without an endpoint, search is by words over labels and
categories.

**Search ranks by meaning, then sinks what almost nobody answered.** Relevance minus 0.04 below 10% coverage in the
chosen sources, minus 0.08 below 1%, nobody-carries-it last. Measured on 15 queries against the whole corpus: 11
found first, 13 in the top five; words alone found 2 first; multiplying relevance by √coverage found 9. No model call
per keystroke.

**Matching a trait: retrieve 20, let the model choose among real ids with counts, refuse anything else.** Candidates
come from search by meaning; the model sees each candidate's values and how many people hold each; the server
refuses an attribute it was not offered and a value outside the attribute's list. Measured: 14 of 15 in the top five
with no invented ids at 20 candidates; at 40 the model did worse and invented one; reading the whole codebook it
invented ids and drifted out of JSON. This extends `population.interpret_audience` beyond the declared ontology
(ADR 0014's unfinished half).

**The drafter is checked, not trusted.** Each trait is matched twice — with the whole description and on its own —
and a disagreement is put to the person instead of applied (Q5). The rules the reader is told and does not always
obey are enforced in code: guess words move a phrase to the topics. The reading prompt carries no example groups,
because a short follow-up returned the example as a group on three runs of three. The model's own judgement of how
well something fits is not shown; what an attribute measures is taken from its id and category.

**Quotas, not a fixed floor.** An audience's quota is its share of the study size. A draft that leaves an audience
below its quota moves the costliest filter to a description until it fits, and flags each move for acceptance; an
audience still below its quota blocks Continue, because past it the engine's relaxation ladder would drop filters on
its own.

**Continue is blocked by exactly what is unresolved:** an unconfirmed category, an unanswered question, an
unaccepted change, shares missing or not summing to 100%, an audience below its quota. The page lists them.

**Text sources are opt-in, labelled and recorded.** Off by default; labelled wherever their people are counted; when
surveyed people cannot fill an audience, the page says what each would add; admitting one writes an `assumed` entry
with its contribution to the candidate pool.

**The interface speaks the glossary.** Candidate pool, audience, text source, extracted; never "segment",
"model-read" or "inferred". The coverage chips shipped on 2026-09-20 say "dense/sparse", which the glossary avoids;
they become coverage.

**Test posture.** Everything deterministic runs offline against the packed-shard fixture, as the corpus suite
already does: the matrix against the adapter's own decoding, counts, the cross-survey core, category eligibility,
required-set rules, quota relaxation, the guess-word rule, and export through the engine's types. Reference counts, pinned per
source so they do not depend on which shards a machine holds, become a `real_corpus` test: "Parent of young kids" is
1,017 Stack Overflow respondents and no GSS respondent; age, region, education, employment and life stage keep 52,530
Stack Overflow and 11,754 GSS respondents; adding marital status and children keeps no Stack Overflow respondent. The retrieval evaluation becomes a gate that runs with the real
corpus and an endpoint and is skipped, announced, without them: at least 11 of its queries found first and 13 in
the top five. The model-backed drafting is exercised with a fake chat port whose answers include the failures seen —
an invented id, a value outside the list, a disagreement between the two matches, a copied example — each of which
must be refused or put to the person. The interface is driven in a real browser through both paths, as
`check_in_browser.mjs` does for the mockup.

## Phases

| Phase | Delivers | Done when |
|---|---|---|
| 1 | Codebook labels and categories through the API; word search over them; the coverage wording | "kids", "money", "wealthy" each return a relevant attribute in the top five by words |
| 2 | The persona value matrix and the draft-state read: candidate pool, requirement and filter costs, value counts by source, what text sources would add | the per-source reference counts reproduce through the API, from the engine, with `web` doing no arithmetic |
| 3 | The edit surface on hand-built audiences: value pickers with counts, "also asks this as", quotas against study size, survey-split and text-source notes, ledger entries | the education-savings audiences are rebuilt without typing a value, and the survey split is visible and recorded before launch |
| 4 | Search by meaning: attribute embeddings in the background, sunk ranking, words fallback | the retrieval gate passes |
| 5 | Describe → read → category checkpoint → draft, with the agreement check, the guess-word rule, quota relaxation and every flag | no draft can carry an attribute or value outside the codebook; every failure the fake port injects is refused or asked; the three example briefs reach Continue |
| 6 | One step replacing the ontology builder and the intake audience panel; Continue into launch | the education-savings study is authored from a single description, reusing its category, and launches |

## Out of Scope

* **"A parent, however the survey asked it."** The same question exists as different attributes in different surveys,
  and an audience is an AND of attribute filters. Expressing an OR across attributes, backed by a reviewed value-level
  crosswalk, changes the `Audience` contract and needs its own decision.
* **Running environments together.** A study still runs in one environment; combining survey room, feed, forum and
  word of mouth in one study is a separate piece of work.
* **Changing a category's required set** from within a study, and pruning ontology versions.
* **Sweeps** from the interface.

## Further Notes

Open questions carried from the grill, to settle during the phases rather than before:

1. How an unsure match is detected. Two matches per trait is what the mockup does; a value-level check — one
   embedding per value, about 6,500, two hours once — may catch what it misses ("students" matched to education
   level; "early career" to senior job levels). Measure both on the failures recorded in `PLAN.md` before phase 5
   fixes the mechanism.
2. The reading itself still varies between runs and the drafter cannot detect a trait it never read; showing the
   reading at the checkpoint is the mitigation. Whether to read twice and compare is worth measuring in phase 5.
3. The retrieval evaluation is 15 queries with answers written by one person. Grow it before tuning the ranking
   further, or the ranking will fit its author.
