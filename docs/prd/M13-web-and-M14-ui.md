# PRD — M13 `web` and M14 `ui`: the engine with a face on it

## Problem Statement

The engine is complete and the only way to use it is a command line. A study is configured by nineteen
flags, and what it found is read by opening JSON files in a directory named after a ULID. That is a
workable instrument for the person who built it and an unusable one for anyone else, including the person
who built it six months from now.

Three gaps are specific, and the first is the one that limits what can be studied at all. A study's
audiences are defined by a **category ontology**, and an ontology is a hand-written JSON file. Three exist.
The corpus carries **1,290 attributes**, each with a declared value set, so the limit is not the data — it
is that nobody has written the file. A researcher who wants to study anyone the three ontologies do not
describe cannot, and has no way to find out what the corpus would have allowed.

The second is that a long study is invisible while it runs. A run takes thirty to forty-five minutes,
writes thousands of events, and reports nothing until it finishes — the registry reads `$0.00` while a run
is four thousand events in, because spend is only published at the end.

The third is that the engine's endpoint independence is real but undiscoverable. ADR 0021 already means any
OpenAI-compatible endpoint works, and the documentation leads with a LiteLLM proxy, so it reads as a
requirement rather than as one option among three.

Two risks are particular to putting a face on this engine. A dashboard makes numbers feel authoritative
through presentation alone, and this engine's numbers are `UNCALIBRATED` by construction — the trust
statement, the unmeasured lines and the disconfirming tests are the parts that must not become fine print.
And an interface that computes its own aggregates rebuilds the duplication this architecture was
restructured to remove: one concept, two implementations, now with a language boundary in between.

## Solution

Two modules behind one product.

`web` (M13) serves the engine over HTTP. It reads through `TraceView`'s five closed shapes and `analysis`,
and it **derives nothing** (ADR 0045): it serialises, filters, pages and streams, and every number it
returns is a field of something a module that owns it produced. It ships as the `jahan[web]` extra, so
the core keeps its ten dependencies. It runs studies as subprocesses, because the trace is already the
status channel — a view opens on a live run — and because a tick is recorded whole or not at all, so
cancelling loses at most the tick in flight and resuming is a re-run with the same id.

`ui` (M14) is the Next.js interface, following the flow the mockups already describe: intake → population →
run → trace → atlas → report → trust. It is plumbing in the same sense the CLI is: it renders what the API
returns and configures what a study states.

The interface is a **single-operator local application** (ADR 0043). The person running it downloaded the
corpus and accepted its terms; there are no accounts, no tenancy, no quotas, and the API key is theirs, set
in the server's environment and never shown or accepted in a browser.

The ontology builder turns the codebook into the audience builder. It offers the corpus's 1,290 attributes
with their real vocabularies, validates every name against the codebook before a draft can be saved, and
saves an edit as a **new version** rather than a changed file (ADR 0044), because an ontology is hashed
into every identity and a resume refuses by name when it moves.

Four aggregates the mockups need do not exist yet, and each becomes a derived shape in `analysis` rather
than a calculation in a browser: per-tick trajectories per audience and per community, `ranking` findings
over a scenario's replicates, `risk` findings from anomalies, and a workspace summary read from registry
entries.

## User Stories

**Authoring a study**

1. As a researcher, I want to build an ontology by searching the corpus's own attributes and seeing their
   real value sets, so what I can study is bounded by the data rather than by which files exist.
2. As a researcher, I want an attribute the corpus does not carry refused as I type, so a study cannot be
   authored that dies four shards into its first draw.
3. As a researcher, I want to know that the conditioning set is the field that decides whether my personas
   differ from each other at all, stated where I choose it.
4. As a researcher, I want editing an ontology to create a version and leave the old one alone, so every
   past study still resolves to what it actually ran on.
5. As a researcher, I want to draft freely without the corpus present, and to be stopped from pinning a
   draft that has never been validated against one.
6. As a researcher, I want a brief, its variants and its environments configured in a form that uses the
   engine's own words, with each term's definition to hand.

**Running and watching**

7. As an operator, I want to start a study and watch it: ticks closing, turns landing, spend accruing
   against the budget, and the degradation rung if one fires.
8. As an operator, I want spend published while the run is going, not after it, so a budget is something I
   can act on.
9. As an operator, I want to cancel a run and lose at most the tick in flight, and to resume it later.
10. As an operator, I want a run that outlives the server process, so restarting the interface does not
    destroy forty minutes of work.
11. As an operator, I want the first thing I run to need no key, no corpus and no network, and to produce a
    real report — and to be marked permanently as a fake run wherever it appears.

**Seeing what happened**

12. As an analyst, I want one persona's whole history — what it was shown, what it said, how its beliefs
    moved, who it heard from — because that is the unit the engine actually records.
13. As an analyst, I want the exact prompt behind a turn, rebuilt from the record and checked against the
    hash the turn carries, and told plainly when it cannot be rebuilt.
14. As an analyst, I want the word-of-mouth graph: who told whom, on which channel, how often, and when
    last.
15. As an analyst, I want audiences and communities shown as different things, because a study's finding is
    often that they disagree.
16. As an analyst, I want a quantity that could not be measured to say so where the number would have been,
    with its reason.
17. As an analyst, I want every finding to carry its evidence and the real-world test that would falsify
    it, as the report already does.

**Trust**

18. As a researcher, I want the run's calibration stated once, prominently, and never adjustable from the
    interface.
19. As a researcher, I want the trust page to show what would earn the next rung, so `UNCALIBRATED` reads
    as a position on a ladder rather than as a failure.
20. As a maintainer, I want nothing in the interface to make a number feel more certain than the engine
    says it is.

**Discipline**

21. As a maintainer, I want the web layer to compute no statistic, asserted over the module.
22. As a maintainer, I want the API testable without a browser, so the interface is not the only way to
    know the server works.
23. As a maintainer, I want the command line to keep working unchanged, because it is what makes a run
    reproducible and it is what the suite exercises.

## Implementation Decisions

**Two modules, one product.** `web` is a new module (M13) rather than a second entrypoint on `cli`, which
already has one job. `ui` (M14) is the only module not written in Python, and it holds no engine logic.

**`jahan[web]` extra.** The core keeps its ten runtime dependencies; the server's belong to an extra, as
telemetry's already do.

**The web layer derives nothing (ADR 0045).** It may serialise, filter, page and stream. A panel that wants
a number nobody derives is blocked until `analysis` derives it. A boundary test asserts the package
performs no arithmetic over what it serves, in the same shape as `report`'s.

**The five shapes are the API.** `events`, `beliefs`, `edges`, `verbatims`, `resolve` map to endpoints
almost one to one, plus `analysis`'s digest, findings, clusters and anomalies, plus the run lifecycle.
Nothing reaches storage another way.

**Runs are subprocesses.** The registry is authoritative for what happened; the process table only for
whether it is still running. Orphans left by a killed session are swept on server start. Progress is polled,
not streamed: a tick takes tens of seconds, and streaming buys nothing at that rate.

**The runner publishes progress.** Status, recorded cost and ticks closed are written to the registry entry
as the run works, which is consistent with run state being derived from the trace — the entry is the
published cache of what the trace already says. The alternative, summing cost events per request, is the
cost that was removed from the budget ladder this session and would return on every page refresh.

**Execution configuration stays in the environment.** Base URL, key, concurrency and rate limits are the
server's, never hashed, never rendered. Model pins and prices are study inputs, recorded and hashed. The
setup screen reports whether an endpoint is configured, and never asks for a key in a browser.

**Four new derived shapes in `analysis`:** trajectories per audience and per community per tick; `ranking`
findings from a scenario's replicates, carrying the spread that says whether the order survives; `risk`
findings from anomalies; and a workspace summary over registry entries. `RunRegistryEntry` gains the
population size, so a workspace total never walks a partition.

**Nothing generated is a finding.** The mockups' "mitigations (simulated)" has no source in an engine whose
findings are authored by extraction and whose cluster labels are quoted verbatims (ADR 0041). It is cut. If
advice is wanted later it belongs in a panel that says a model wrote it and that it is not derived from the
record.

**The interface speaks the glossary.** Population, not cohort. Audience and community, never segment — the
glossary bans the word for both, and the two are what audience divergence and polarization separately
measure.

**Known measurement problems are shown, not hidden.** Belief deltas saturate at ±1.0 on the model measured
so far, and community detection currently forms none — modularity 0.409 across eight communities, one of
ten people under the five-percent floor. Where a chart would be empty, the diagnostic appears instead.

**Test posture.** The API is exercised in-process against temporary directories with the fake backend, the
way the CLI suite already is, and the suite reaches no network. The interface is exercised against the real
artefacts of a recorded run, never against fixtures invented for it — three of this engine's worst defects
lived for the project's whole life behind fakes that answered whatever the test wanted.
