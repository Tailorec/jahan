# PRD — M7 `world`: environments, and who sees what

## Problem Statement

A persona can react, but nothing yet decides what it reacts to. Between the population and the agent sits the part
of the engine that makes a study a simulation rather than a batch of surveys: what exists in the environment, who
is shown which of it, who is even awake this tick, and what happens to what they do.

This is also where the engine's central comparison lives. A survey room — every persona sees the stimulus alone,
with no social signal — is the baseline that FMCG concept testing already does with humans. A social feed, a forum
with hot-score ranking, a forum scoped to communities with consensus ranking, and word of mouth across the graph
each add a different mechanic on top of it. The difference between the baseline and the others is the finding a
study is for, so all of them must be the same code path with different mechanics, not different code paths that
happen to be compared.

Three risks belong to this module. A world that is not deterministic makes every finding unreproducible and every
sweep incomparable. A world that keeps state the engine cannot rebuild makes resume a guess. And a recsys that
quietly concentrates exposure turns a filter-driven artefact into what looks like organic consensus, which is why
the random control arm is not optional.

The module also carries an unusual structural constraint: its internals mirror upstream OASIS file-for-file so
quarterly upstream diffs stay mechanical, while the rest of the engine sees exactly one narrow port.

## Solution

`reset(header) -> WorldDelta` and `step(tick, turns) -> WorldDelta`. A step takes the previous tick's recorded turns
and returns what changed: stimuli published, interventions applied, exposures dropped with the persona each was
dropped for, and one presentation — impression plus view — per activated persona and channel. The opening delta is
tick zero.

No world state crosses the boundary. A world resumes by `reset` followed by replaying its recorded turns through
`step` up to the last closed tick, and the replay must reproduce the recorded events exactly, which doubles as the
determinism check (ADR 0011). Internal checkpoints may make replay faster and are never a contract. The world never
assigns event ids or sequence numbers; the runner is the partition's only writer.

Platform state lives in SQLite from the first phase, salvaged from OASIS `database.py` rather than rewritten, with
provenance columns added at write time. Platforms land in order — SurveyRoom, SocialFeed, Forum with both presets,
then word of mouth — so the agent branch has a real environment to integrate against early. Recsys modes land in
order too: `random` first as the control arm, then `reddit_hot` copied verbatim, then `twitter`, then `twhin`.

Time is declared, not assumed: a scenario states its `tick_unit` and `horizon_ticks`, interventions are expressed in
ticks against them, and the unit travels forward so a report can label an axis truthfully.

## User Stories

**The loop and its record**

1. As a runner, I want `step` to take the last tick's turns and return a delta built from the trace's own record
   types, so the world never needs a private vocabulary.
2. As a researcher, I want a world to resume by replaying its recorded turns, so a resumed run is the same run.
3. As a maintainer, I want replay to reproduce every recorded delta exactly, so determinism is tested by the same
   mechanism that provides resume.
4. As a runner, I want the world never to assign event ids or sequence numbers, so the partition has one writer.
5. As a researcher, I want `step` to be bit-identical across two processes under a fixed seed, so a finding does not
   depend on where it ran.

**Who sees what**

6. As a persona, I want everything I saw this tick on one channel to arrive as one impression, so seeing two things
   side by side is not recorded as seeing each alone.
7. As a methodologist, I want the view to carry only public context — counts, ancestry, my tie strength and shared
   community with each author — so nothing private about another persona can reach a prompt.
8. As a methodologist, I want engagement counts to include only earlier ticks, so within-tick independence holds
   (ADR 0010).
9. As an operator, I want an exposure budget per persona per tick, never exceeded, with every drop recorded and
   given a reason.
10. As an analyst, I want the `random` recsys mode to produce measurably flatter exposure concentration than
    `reddit_hot` on the same fixture, so filter-driven effects can be separated from organic ones.
11. As a maintainer, I want the `reddit_hot` score copied verbatim from upstream, so its value is fidelity rather
    than our improvement of it.

**Platforms**

12. As a researcher, I want a survey room where every persona receives the stimulus with no social signal, so the
    baseline matches how concept tests are run with humans.
13. As a researcher, I want a social feed with posts, comments, likes, reposts and quotes, and visible social-proof
    counters, so juxtaposition and social proof can act.
14. As a researcher, I want one forum class with two presets — global with hot-score ranking, and community-scoped
    with recency-and-agreement ranking — so herding and slow hardening are a study variable rather than a fork.
15. As a researcher, I want word of mouth to deliver as a next-tick exposure whose view records the correct tie
    strength, so a peer's recommendation is not the same object as a feed impression.
16. As a methodologist, I want word of mouth capped per persona per tick, so one strongly-felt reaction cannot fan
    across a dense community within a single tick.
17. As an analyst, I want a persona's attempted action that the channel does not support to be recorded and
    rejected, so what a persona tried is data rather than an error.

**Time, activation and interventions**

18. As a researcher, I want a scenario to declare its tick unit and horizon, so every downstream digest can label
    time truthfully.
19. As a persona, I want my chance of acting each tick to come from my involvement and the rhythm of the tick unit,
    so an hour-tick study and a day-tick study do not share one curve.
20. As a researcher, I want interventions to compose rather than overwrite, so a promotion during a launch is both.
21. As an operator, I want activation and every other draw derived from the run seed, so a rerun activates the same
    personas.

## Implementation Decisions

**Interface.** `reset(header) -> WorldDelta`, `step(tick, turns) -> WorldDelta`. `WorldDelta` already exists in
`simcore/schemas/world.py` and is not widened without an ADR.

**State.** SQLite from phase one (OASIS `database.py`, extended with provenance columns at write time), internal to
the module. Nothing crosses the boundary; replay is the contract (ADR 0011).

**Structure.** `env.py`, `platform.py`, `recsys.py`, `clock.py` keep their upstream file shapes and licence headers
so quarterly diffs stay mechanical. The merge is at the interface: one port outward, upstream-diffable structure
inward.

**Ordering within a tick.** Every draw — activation, recsys tie-breaks, exposure selection, word-of-mouth targets —
comes from a seed derived from the world seed, the tick and a named purpose, so adding a later draw cannot shift an
earlier one.

**Exposure.** Default budget of 3 stimuli per persona per tick. Exposures keep per-stimulus attention, reason and
seen flag, and are grouped into one `Impression` per persona and channel — grouped, not flattened.

**Profile embeddings** for the `twitter` mode are computed once at population build and carried in the population
manifest, never recomputed per tick. `twhin` uses degree centralities from the generated graph.

**Word of mouth.** `wants_to_talk(reaction, peer)` gates on sentiment strength and tie strength, both configurable
with documented defaults, capped at two peers per persona per tick. Delivery creates a next-tick exposure with
`reason=wom`.

**Activation.** Per-persona probability from involvement × a rhythm curve keyed to `tick_unit`; defaults in code,
overridable per scenario; seeded Bernoulli per tick.

**Affordances.** The world is the authority on what a channel supports. An unsupported action is recorded with its
rejection and dropped, never retried.

**Phasing.** SurveyRoom → SocialFeed → Forum (both presets) → word of mouth; `random` → `reddit_hot` → `twitter` →
`twhin`.

**Salvage.** OASIS `env.py`, `env_action.py`, `make.py` (PettingZoo-style loop, CAMEL stripped, our `ChatPort`
injected), `platform.py` + `database.py` + `channel.py` (already trace-shaped — extend, do not rewrite),
`recsys.py` + `process_recsys_posts.py` (embedder swapped to our port), `clock.py` (straggler-aware semantics),
`typing.py` (`ActionType`, `RecsysType`).

## Testing Decisions

Boundary tests through `reset` and `step`, with fakes for inference and embedding; the suite never reaches a
network.

- `step` is deterministic under a fixed seed and bit-identical across two processes.
- Replaying recorded turns from `reset` reproduces every recorded delta.
- The exposure budget is never exceeded, and an impression never exceeds it.
- Every drop carries a persona and a reason.
- `random` produces measurably flatter exposure concentration than `reddit_hot` on the same fixture.
- A view carries no attribute, belief or private reaction of another persona, and no aggregate outcome — asserted
  over the whole delta, not one field.
- Engagement counts in a view include only earlier ticks.
- A survey-room impression holds exactly one exposure.
- A word-of-mouth delivery appears as a next-tick exposure whose view records the correct tie strength, and the
  per-tick cap holds in a dense community fixture.
- Composed interventions apply additively.
- An action a channel does not support is recorded as rejected and changes no state.

## Out of Scope

Orchestration, budget and sweeps (`runner`, module 8). Trace storage (`trace`, module 9). Prompt assembly and
everything about a persona's reasoning (`agent`, module 6). The RetailShelf platform, deferred in §12. Analysis of
what the dynamics produced (`analysis`, module 10).

## Further Notes

The two forum presets are mechanically similar and dynamically opposite: hot-score produces herding, consensus
ranking produces slow hardening. Keeping them in one class with a preset is deliberate — it makes the comparison a
study variable rather than a fork in the code.

The straggler case has no separate vocabulary: it is the lowest tick among live worlds, and the clock is written
that way from the start.
