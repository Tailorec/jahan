# The trace

Everything that happens in a world is written to its **trace**: an append-only record of every post
published, every exposure, every turn, every belief change, memory, reflection and cost. The trace is the
study's only source of truth. Reports, the interface and every number in them are derived from it, and from
nothing else.

## What is recorded

One world's whole record is a **partition**: a header (the run configuration, brief, population manifest,
scenario and seed) and every event that happened, numbered without gaps. Each event is exactly one of thirteen
kinds:

| Event | Records |
|---|---|
| `stimulus_published` | a post, reply or message entering the world: the launch post, a persona's reply, a word-of-mouth message |
| `exposure_dropped` | something that could not be shown because the exposure budget was full, with why |
| `turn` | one persona's whole impression, the view it was given, its reaction, and the prompt's hash |
| `guardrail_violation` | a reaction refused for citing something the persona was never shown, even after a stricter retry |
| `reflection` | a persona consolidating its experience into revised beliefs |
| `memory` | a memory written |
| `belief_snapshot` | a persona's beliefs at a tick |
| `probe` | a character probe's questions, answers and agreement |
| `cost` | one model call: route, pinned and served model, tokens, cost and where the cost came from |
| `intervention` | a launch, teaser or promotion applied |
| `degraded` | a budget rung taking effect |
| `tick_closed` | the mark that a tick was recorded whole |
| `lifecycle` | the world starting, pausing, resuming, finishing |

A whole impression is recorded inside its turn, so what a persona saw side by side is never reassembled
afterwards from separate events ([ADR 0006](../adr/0006-trace-records-whole-turns-in-self-verifying-partitions.md)).

When a partition is read it is **verified as a whole**: events must be gapless, stimuli must be published before
they are shown, only the brief's claims and the population's personas may appear, only pinned templates,
anchors and models may be used, and a memory may only recall the same persona's earlier turns.

## A tick is recorded whole, or not at all

A tick's events are written together, then marked by `tick_closed`. If a run is interrupted mid-tick, that tick
is a **discarded tick**: its work is lost, and its spend is unknown but not zero, so a run that lost one says so
([ADR 0033](../adr/0033-a-tick-is-recorded-whole-or-not-at-all.md)). Cancelling a run therefore loses at most
the tick in flight.

## Resume and replay

A world does not save its internal state. It **resumes by replaying its trace**: start the world fresh from its
header, feed it the recorded turns tick by tick up to the last closed tick, then continue live
([ADR 0011](../adr/0011-worlds-resume-by-replaying-their-trace.md)). Replay must reproduce every recorded event
exactly, which doubles as a determinism check. A persona's carried state is likewise rebuilt from its recorded
turns, memories and belief snapshots.

A resume **refuses** a run whose inputs or engine moved: a changed brief, population or configuration hash,
or a different engine version. Forcing it is possible, and is recorded and stated in the report
([ADR 0036](../adr/0036-a-resume-refuses-a-run-whose-inputs-or-engine-moved.md)).

## Prompts are rebuilt, never stored

The trace has deliberately **nowhere to put a whole prompt**. A turn records the parts (the persona block's
hash, the impression, the view, the recalled memories, the template version) plus a fingerprint of the exact
messages sent:

$$
\text{prompt hash} = \operatorname{SHA\text{-}256}\big(\text{canonical JSON of the messages, keys sorted}\big)
$$

To show the prompt behind a turn, the engine re-renders the persona block from the population, replays the
persona's beliefs up to that tick, resolves its memories and stimuli by id, rebuilds the messages, and hashes
them. The prompt is displayed **only if the hash matches**. Otherwise the page says it cannot be rebuilt, and
why ([ADR 0046](../adr/0046-a-prompt-is-reconstructed-and-verified-never-stored.md)).

A rebuilt prompt that hashes correctly is stronger evidence than a stored copy, which anything could have
written at any time.

## Identity: everything is derived

Briefs, ontologies, populations, configurations and worlds are identified by **hashes of their content**, not
by names ([ADR 0009](../adr/0009-identity-is-derived-and-every-pin-is-verified.md)). The canonical hash of any
object is

$$
\operatorname{SHA\text{-}256}\big(\text{JSON of the object, keys sorted, no whitespace, NaN refused}\big)
$$

with set-valued fields sorted, negative zero written as zero, and the contract version folded in. Comments and
whitespace in a brief do not change its hash; reordering claims does. A hash is stated only where its object does
not travel with it, and verified wherever the object is present.

## Storage

While a run is live, each world writes to its own SQLite file, one transaction per tick. When the world
finishes it is **finalized** into Parquet: events sorted by persona and tick, plus derived tables of beliefs
and word-of-mouth edges. What can be read does not change; only where it is read from does. A run registry
records every run's configuration, hashes, seeds, pinned models, engine version, cost and status. As a rough
size, 2,000 personas over 30 ticks is about half a million events per world.

## Asking the trace questions

Nothing reads the trace directly. Every reader, whether report, analysis or interface, goes through a fixed,
typed set of questions called the **trace view**:

| Question | Answers |
|---|---|
| `events(filter)` | the events matching a typed filter |
| `beliefs(persona)` | one persona's belief history |
| `edges()` | who told whom, on which channel, how often |
| `verbatims(grouping)` | what personas said, grouped by audience, community or claim |
| `resolve(ids)` | exactly the events a finding cites, or an error |

A live run and a finished run answer identically. Nothing else can be asked, and nothing that reads the trace
can reach past these questions ([ADR 0034](../adr/0034-one-trace-view-over-two-backends.md)).
