# Plan: M7 `world` — environments, and who sees what

> Source PRD: `docs/prd/M7-world.md`
> Binding decisions: ADR 0011 (no world state crosses the boundary; a world resumes by replay), ADR 0010 (within-tick independence), ADR 0003 (a reaction names the stimulus it is about), ADR 0021 (one OpenAI-compatible endpoint), ADR 0030 (persona state travels with its job — the world holds none of it), ADR 0016 (no corpus rows committed). `CONTEXT.md` (Tick, Horizon, Intervention, Stimulus, Exposure, Impression, View, Social Proof, Presentation, Activation, Affordance, Word of Mouth, Community). Where `FINAL_ARCH.md` §5.7 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Two calls outward** — `reset(header) -> WorldDelta` and `step(tick, turns) -> WorldDelta`. The opening delta is tick zero. `WorldDelta` is the existing contract and is not widened without an ADR.
- **No world state crosses the boundary** — a world resumes by `reset` and replaying its recorded turns up to the last closed tick, and the replay reproduces the recorded events exactly. Internal checkpoints may make that faster and are never a contract.
- **The runner is the only writer** — the world assigns no event ids and no sequence numbers.
- **Upstream-diffable inside, one port outside** — `env.py`, `platform.py`, `recsys.py`, `clock.py` keep their upstream file shapes and licence headers so quarterly OASIS diffs stay mechanical.
- **Platform state is SQLite from phase one** — salvaged rather than rewritten, with provenance columns added at write time. In-memory first is the shortcut that defers determinism and replay, which are this module's hardest requirements.
- **Every draw is derived** — activation, recsys tie-breaks, exposure selection and word-of-mouth targets each draw from a seed derived from the world seed, the tick and a named purpose, so adding a later draw cannot shift an earlier one.
- **What a persona is shown is public and past** — a view carries counts, ancestry, tie strength and shared community only, counts include only earlier ticks, and no aggregate outcome ever reaches a presentation.
- **Exposures are grouped, not flattened** — everything a persona saw on one channel in one tick is one `Impression`.
- **The world owns affordances** — an action a channel does not support is recorded as rejected and changes no state.
- **Time is declared** — a scenario states its `tick_unit` and `horizon_ticks`; the straggler case is simply the lowest tick among live worlds, with no second vocabulary.
- **Test posture** — boundary tests through `reset` and `step`, with fakes for inference and embedding. The suite never reaches a network.

---

## Phase 1: The loop and the survey room

**User stories**: 1, 4, 5, 12

### What to build

The module's shape made true on the baseline environment. `reset` opens a world at tick zero from its header; `step` takes the previous tick's recorded turns and returns a delta built from the trace's own record types. The survey room gives every persona the stimulus alone, with no social signal and no ranking — one exposure per impression. Everything in this phase is deterministic under a fixed seed.

### Acceptance criteria

- [x] `reset` returns the opening delta as tick zero, built from trace record types only
- [x] `step` takes recorded turns and returns published stimuli, drops and one presentation per activated persona and channel
- [x] A survey-room impression holds exactly one exposure, and its view carries no social signal
- [x] The world assigns no event id and no sequence number anywhere in a delta
- [x] `step` is deterministic under a fixed seed and bit-identical across two processes
- [x] No world state appears in any delta, asserted over the whole structure

---

## Phase 2: Replay and resume

**User stories**: 2, 3

### What to build

The property the rest of the module is built to keep. A world reconstructed by `reset` and replaying its recorded turns through `step` reproduces every recorded delta exactly, so resume and the determinism check are the same mechanism. Internal checkpointing may speed replay up, and a run with checkpoints must produce what a run without them produces.

### Acceptance criteria

- [x] Replaying recorded turns from `reset` reproduces every recorded delta, field for field
- [x] A world resumed at tick N continues identically to one that never stopped
- [x] An internal checkpoint changes speed and never output, asserted by replaying with and without one
- [x] A replay that diverges fails loudly, naming the first tick and field that differ
- [x] Replay needs nothing but the header and the recorded turns

---

## Phase 3: The clock

**User stories**: 18, 19, 20, 21

### What to build

When personas act and when things happen to them. A scenario declares its `tick_unit` and `horizon_ticks`, and the unit travels forward into every delta so a report can label an axis truthfully. Activation is a seeded Bernoulli draw per persona per tick from involvement × a rhythm curve keyed to the tick unit. Interventions are expressed in ticks and compose rather than overwrite.

### Acceptance criteria

- [x] A scenario's tick unit and horizon are declared and carried forward in every delta
- [x] Activation probability comes from involvement × a rhythm curve keyed to the tick unit, with defaults overridable per scenario
- [x] An hour-tick and a day-tick scenario use different rhythm curves
- [x] A rerun under the same seed activates the same personas on the same ticks
- [x] Two interventions on one tick apply additively, and neither overwrites the other
- [x] Interventions are expressed in ticks against the declared horizon, never in wall-clock time

---

## Phase 4: Platform state in SQLite

**User stories**: 17

### What to build

Where a platform's facts live. The salvaged OASIS schema, extended with provenance columns written at the time the row is written, holds posts, comments, reactions and follows. Actions arriving in recorded turns are applied to it, and an action the channel does not support is rejected and recorded rather than raised.

### Acceptance criteria

- [x] Platform state is SQLite, internal to the module, and appears in no delta
- [x] Actions from recorded turns are applied, and the state they produce survives a replay
- [x] An action a channel does not support is recorded as rejected and changes no state
- [x] Provenance columns are written at write time, not backfilled
- [x] The salvaged schema is extended rather than rewritten, so an upstream diff stays mechanical
- [x] Two processes reach byte-identical state from the same turns

---

## Phase 5: The social feed

**User stories**: 6, 7, 8, 13

### What to build

The first environment with social signal. Posts, comments, likes, reposts and quotes, with visible social-proof counters. Everything a persona saw on the feed in one tick arrives as one impression, and its view carries only public context — counts, reply ancestry, the persona's tie strength and shared community with each author — with counts drawn from earlier ticks only.

### Acceptance criteria

- [x] The feed supports post, comment, like, repost, quote and follow
- [x] Everything a persona saw on one channel in one tick is one impression, grouped and not flattened
- [x] A view carries counts, ancestry, tie strength and shared community, and nothing else
- [x] No view carries another persona's attributes, beliefs or private reactions, asserted over the whole delta
- [x] Engagement counts include only engagement from earlier ticks
- [x] No aggregate outcome reaches any presentation

---

## Phase 6: Exposure budget and the control arm

**User stories**: 9, 10

### What to build

How much a persona sees, and the baseline against which ranking effects are measured. A budget caps stimuli per persona per tick; everything dropped is recorded with the persona it was dropped for and a reason. The `random` recsys mode is the control arm, and it exists before any ranking mode so every later mode is measured against it.

### Acceptance criteria

- [ ] The exposure budget is never exceeded, and no impression exceeds it
- [ ] Every drop records the persona it was dropped for and its reason
- [ ] The budget default is 3 and is configurable per scenario
- [ ] `random` selects without reference to engagement, deterministically under a seed
- [ ] Exposure concentration under `random` is measurable on a fixture, giving the baseline later modes are compared against
- [ ] Exposures keep their per-stimulus attention, reason and seen flag

---

## Phase 7: `reddit_hot` and the global forum

**User stories**: 11, 14

### What to build

The first ranking mode and the first forum preset. The hot score is copied verbatim from upstream — its value is fidelity, not our improvement of it. The `reddit_global` preset lets any persona reach any thread, ranked by that score, with create_post, reply and vote.

### Acceptance criteria

- [ ] The hot-score computation is copied verbatim, with its upstream licence header intact
- [ ] The global forum supports create_post, reply and vote, with threads open to any persona
- [ ] `reddit_hot` produces measurably higher exposure concentration than `random` on the same fixture
- [ ] Ranking ties break from a derived seed, so ordering is reproducible
- [ ] Votes affect ranking only through the upstream score, with no additional weighting of ours

---

## Phase 8: The community-scoped forum

**User stories**: 14

### What to build

The same forum class, the opposite dynamic. The `community_scoped` preset scopes threads to Leiden communities from the population and ranks by recency and agreement with no hot score, so consensus hardens slowly where the global preset herds quickly. One class, two presets, so the comparison is a study variable rather than a fork in the code.

### Acceptance criteria

- [ ] Threads are scoped to the population's communities, and a persona sees its own community's threads
- [ ] Ranking uses recency and agreement, and no hot score is computed in this preset
- [ ] Both presets are the same class with different configuration, asserted over the module
- [ ] On one fixture, the two presets produce measurably different concentration and divergence
- [ ] A persona with no community assignment is handled explicitly rather than silently excluded

---

## Phase 9: `twitter` and `twhin` recsys

**User stories**: 10, 11

### What to build

The two remaining modes, both reading signals computed elsewhere. `twitter` ranks by interest match against profile embeddings carried in the population manifest; `twhin` is graph-aware, using degree centralities from the generated graph. Neither recomputes its signal per tick.

### Acceptance criteria

- [ ] `twitter` ranks by interest match against profile embeddings from the manifest, with no embedding call at step time
- [ ] `twhin` uses degree centralities from the generated graph, computed once
- [ ] All four modes are selectable per scenario and produce measurably different exposure concentration on one fixture
- [ ] A scenario naming a mode whose signal is missing fails at `reset`, not mid-run
- [ ] Every mode remains deterministic under a fixed seed

---

## Phase 10: Word of mouth

**User stories**: 15, 16

### What to build

The graph channel. After a reaction, `wants_to_talk(reaction, peer)` gates on sentiment strength and tie strength, and a delivery creates a next-tick exposure with `reason=wom` whose view records the tie strength between the two personas. A cap per persona per tick keeps one strongly-felt reaction from crossing a dense community in a single tick.

### Acceptance criteria

- [ ] Word of mouth delivers as a next-tick exposure, never within the tick that produced it
- [ ] The delivered exposure's view records the correct tie strength and `reason=wom`
- [ ] Both gates are configurable with documented defaults
- [ ] The per-tick cap holds on a dense-community fixture
- [ ] Targets are drawn from a derived seed, so deliveries reproduce
- [ ] A persona with no ties produces no deliveries and no error
