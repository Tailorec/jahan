# Plan: M15 Channels and survey waves — information spreads the ways a study chooses, and intent is tracked

> Source PRD: `docs/prd/M15-channels-and-survey-waves.md`
> Binding decisions: ADR 0048 (channels, survey waves and launch reach are scenario content), ADR 0005 (world identity and seeds), ADR 0021 (one OpenAI-compatible endpoint), ADR 0026 (the paper's SSR formula), ADR 0012 (embedding never falls back), ADR 0045 (the web layer derives nothing), ADR 0007 (adoption is share-weighted over audiences). `CONTEXT.md` (Channel, Survey Wave, Launch Reach, Impression, Affordance, Degradation, Adoption).
> OASIS reference: the local checkout `~/github_interesting/oasis` at `46cdc8d` — `oasis/social_platform/recsys.py` (`rec_sys_personalized_twh`, `rec_sys_reddit`), `process_recsys_posts.py` (`process_batch`), `platform.py` (`refresh`).

## Architectural decisions

Durable across every phase:

- **The scenario says it all** — `Scenario.channels` (a frozen set of `social_feed`, `forum`, `wom`; empty allowed), `survey_every` (positive ticks) and `launch_reach` (a share, only with `channels == {wom}`, default 0.10) are hashed with the scenario. World id and config hash change with them, with no extra code: both already hash the scenario (ADR 0005). `elicits` is removed.
- **The survey room stays internal** — `Channel.SURVEY_ROOM` remains the channel of a wave's impression, so the trace, its validators and `Affordance` (answer only) keep working. It leaves `STUDY_CHANNELS`, and no person chooses it.
- **Wave ticks are one pure function** — `wave_ticks(survey_every, horizon)`: `{0, k, 2k, …} ∪ {horizon − 1}`. The world, runner, analysis and interface all call it and never recompute it.
- **A wave only reads, everywhere** — a survey turn is recorded and scored. Four places skip it, which is exactly what keeps it read-only:
  - the runner's state carry (`_turn_events` writes no memory and no belief change);
  - `rebuild_state` (`agent/_replay.py`);
  - `World._ingest_turns`;
  - `World._wom_deliveries`.
  
  A property test asserts that a world with waves and the same world without them produce identical channel turns, given the same draws.
- **Task by channel, not by run** — the runner sets a job's task from its impression's channel: a survey impression asks `purchase`, and any other asks `reaction`.
- **Order within a tick** — channel presentations first, then word of mouth, then the wave last. The runner already applies outcomes in order, so the wave sees everything from its own tick.
- **Tick 0** — `reset` still publishes the study stimuli. Its delta now carries the launch-reach impressions (word of mouth alone) and the tick-0 wave, so the baseline wave is taken after launch. Feed and forum present from tick 1, as today.
- **Two embedding roles** — `ModelPins.embed` scores SSR (Titan, anchors checked). A new optional `ModelPins.recsys_embed` ranks the feed (TwHIN-BERT through the gateway). Neither falls back (ADR 0012), and each is recorded in the method disclosure.
- **TwHIN-BERT is a tool, not a dependency** — `tools/twhin_server.py` loads `Twitter/twhin-bert-base` and serves `POST /v1/embeddings`, returning `pooler_output` with 512-token truncation. LiteLLM routes to it as `openai/twhin-bert-base`. PyTorch never enters `simcore`'s dependencies.
- **Old runs** — readable as recorded. Resuming one is refused by the existing config-hash check, and the refusal names ADR 0048.
- **Test posture** — everything deterministic runs offline with the fake chat and embed ports, as today. The TwHIN server has one check, skipped and announced without `transformers`. Phase 8 is the only real-model phase. It runs under `systemd-run --user --scope -q -p MemoryMax=… -p MemorySwapMax=0`, one heavy job at a time.

---

## Phase 1: The scenario carries channels and waves

**User stories**: 1, 2, 15, 16, 26

### What to build

- **Scenario:**
  - add the three fields, with validators: launch reach only for word of mouth alone; the horizon holds at least one wave;
  - add `wave_ticks`;
  - remove `elicits` from `Scenario`, `cli/_study.py`, `cli/_concepts.py`, `web/app.py`, the frontend's launch body and `_fake.py`.
- **World:** `WorldConfig.platform` becomes `channels`, read from the scenario rather than passed in beside it; `cli/_study.py:499` stops passing a channel.
- **Command line:** `--channels` (comma list, empty for none), `--survey-every` and `--launch-reach` replace `--channel` and `--elicits` in `study` and `sweep`.
- **This phase's world:** at this point it knows only "no channels" — every persona sees the concept on the wave ticks and nothing else. That is today's concept test, reached through the new path.

### Acceptance criteria

- [x] The three fields hash with the scenario: two scenarios differing only in `channels` have different world ids and config hashes, and the same world seed (ADR 0005)
- [x] `launch_reach` with any channel besides word of mouth is refused, and so is a horizon with no wave
- [x] `wave_ticks(2, 7) == (0, 2, 4, 6)` and `wave_ticks(3, 5) == (0, 3, 4)`; `survey_every ≥ horizon` gives `(0, horizon − 1)`, and a horizon of 1 gives `(0,)`
- [x] Resuming a run recorded before the change is refused, naming the moved input
- [x] `STUDY_CHANNELS`, `--channel`, `--elicits` and `Scenario.elicits` are gone; a grep over `simcore`, `tests` and `frontend` finds none
- [x] `study --channels ""` on the fake study runs end to end, and every persona answers once per wave tick

---

## Phase 2: Survey waves

**User stories**: 6, 7, 8, 9, 10, 11, 12, 13

### What to build

- **World:** emits one survey presentation per persona — all of them, never gated by activation — on each wave tick, after the tick's channel presentations. `_survey_presentations` loses its `_activated` filter.
- **Runner:**
  - sets each job's task from its channel;
  - records survey turns and their SSR scores, but writes no memory, no belief change and no snapshot from them;
  - leaves survey turns out of `previous`, so the world never ingests them;
  - skips them in `rebuild_state`.
- **Budget:** the degrade ladder thins channel activation only. Before a wave tick, the runner projects the wave's cost as personas × the mean cost of recorded survey turns (the pinned price estimate before the first wave). If the projection does not fit the remaining budget, the world pauses at that tick and records `wave_unaffordable`.

### Acceptance criteria

- [x] Every persona has exactly one survey turn per wave tick, including personas never activated and never reached
- [x] A survey turn changes nothing: the persona's state after a tick with a wave equals its state after the same tick without one, field by field, and `rebuild_state` agrees with the runner's carried state
- [x] Channel turns are identical with and without waves over the same draws — a property test over random seeds and schedules
- [x] A survey turn sparks no word of mouth and writes no engagement
- [x] The wave's turn comes after the same persona's channel turn in the same tick, by sequence number
- [x] At the `thin` rung, activation falls and waves stay whole; with a budget short of one wave, the run pauses before it, `wave_unaffordable` is recorded, and no partial wave exists in the trace
- [x] A channel turn whose reaction is a purchase is recorded as an action and never scored as intent

---

## Phase 3: Channels together

**User stories**: 1, 3, 4, 5, 25

### What to build

- **Presentations:** `_presentations` presents every ticked platform. An active persona gets a feed impression and a forum impression when both are ticked, and a word-of-mouth impression when told and word of mouth is ticked.
- **Platform state:** feed and forum keep separate state. Posts published on one platform appear on that platform only, keyed by the impression channel they were authored from.
- **Word of mouth:** follows its checkbox — `_wom_deliveries` returns nothing when it is off.
- **Launch reach:** when word of mouth is the only channel, `reset` exposes a seeded random `launch_reach` share of personas to the concept on the word-of-mouth channel, with reason `launch`. Their reactions tell ties from tick 1.
- **Population:** the graph and personas are untouched. The gate and population build never read channels.

### Acceptance criteria

- [x] With feed and forum ticked, an active persona has one feed and one forum turn in the tick; with only one ticked, none on the other
- [x] A post authored on the forum never appears in a feed, and the reverse
- [x] With word of mouth off, no `wom` impression exists in the whole run; with it on beside a platform, deliveries match today's behaviour for the same draws
- [x] Word of mouth alone runs to the horizon with no crash, with `round(launch_reach × n)` personas reached at tick 0, chosen by the world seed (two seeds give different sets, and one seed gives the same set)
- [x] All eight combinations of the three checkboxes run on the fake study, and each passes the trace validator
- [x] Two runs over one population and seed, differing only in channels, have the same population hash and the same tick-0 activation draws

---

## Phase 4: The forum ranks like Reddit

**User stories**: 18

### What to build

The forum's recsys mode becomes `reddit_hot`, the ranking already ported verbatim, and every forum study uses it. `random` stays available to tests as the control arm. `WorldConfig.recsys_mode` splits into a feed mode and a forum mode, so the two platforms rank independently in one world.

### Acceptance criteria

- [x] A forum study orders threads by hot score: a newer thread with equal votes outranks an older one, and a heavily upvoted older one outranks a new one, matching `rec_sys_reddit` on the same numbers
- [x] In a world with both platforms, the feed's mode and the forum's mode are recorded separately in the trace's exposure reasons

---

## Phase 5: The feed ranks like X

**User stories**: 17, 19, 20

### What to build

- **Serving TwHIN-BERT:**
  - `tools/twhin_server.py`, about 30 lines of transformers plus the stdlib HTTP server, serving `POST /v1/embeddings`;
  - the gateway entry, added to RUN.md and to `../litellm_bedrock.yaml`'s example;
  - `ModelPins.recsys_embed`, required whenever the feed is ticked.
- **Vectors:**
  - one profile per persona — the rendered attributes plus the latest post, as upstream appends "Recent post". It is embedded at world build and again after a persona posts;
  - one vector per post, embedded when published;
  - all cached on the world. Resume replays them from the trace's published stimuli, and one batch call re-embeds whatever the cache lacks.
- **Ranking:** a port of `rec_sys_personalized_twh`:
  - **in-network:** posts by the persona's graph ties and in-study follows, most liked first;
  - **out-of-network:** `cosine(profile, post) × log((271.8 − age) / 100)`, with age in ticks, filling the rest of the candidate window;
  - the `twhin` degree-centrality mode stays as it is.

### Acceptance criteria

- [ ] The server returns `pooler_output` for a text, equal to transformers' own on the same input within 1e-5, and truncates at 512 tokens (skipped, announced, without transformers)
- [ ] Launching a feed study without `recsys_embed` is refused, naming the pin
- [ ] With a fake embedder, a post from a tie outranks an unrelated recommended post, ties' posts come most-liked first, and among recommended posts, similarity × recency orders them exactly as the port of upstream's formula on the same numbers
- [ ] No ranking call embeds: embeddings happen once per persona profile update and once per post, and the embed call count after a fake run equals personas + profile updates + posts
- [ ] A resumed feed run ranks identically to an uninterrupted one
- [ ] SSR still scores in `embed`: a digest refuses a survey turn scored in the recsys model

---

## Phase 6: Intent over time

**User stories**: 22, 23, 24

### What to build

- **Digest:** intent and adoption are read from survey turns only, per wave tick and per audience, share-weighted over audiences as today (ADR 0007) — an intent trajectory.
- **Spread per channel:** exposures by channel and reason per tick, cumulative reach per channel, and word-of-mouth paths, from the existing `_spread` module.
- **Report:**
  - a finding for intent and adoption across waves by audience, and the reached-versus-unreached gap at each wave;
  - a method disclosure naming the channels, survey interval, launch reach, the chat model, both embedding models, and the OASIS departures listed in the PRD;
  - a sentence that repeated SSR is an extension of the paper's one-shot evidence.

### Acceptance criteria

- [ ] On a fake run with known survey answers, the per-wave per-audience intent equals the hand-computed mixture at every wave
- [ ] Channel turns contribute nothing to intent or adoption, even when scored; a channel purchase is counted under behaviour
- [ ] A persona reached by no channel by wave *t* is counted in that wave's unreached group
- [ ] The report's method section names every setting and both models, asserted over the rendered report
- [ ] A run with no channels and one wave produces today's concept-test headline, with the same numbers on the same fake answers

---

## Phase 7: The interface

**User stories**: 1, 2, 4, 5, 14, 22

### What to build

- **New Study:**
  - the Environment select, `ONE_ENVIRONMENT_NOTE` and "Asked — what personas answer" are replaced by three channel checkboxes (Social feed · Forum · Word of mouth), each with a line on what it does;
  - "Survey every *k* ticks", with the resulting wave ticks listed;
  - "Launch reach", shown only when word of mouth is the only channel;
  - the waves' cost stated before launch (personas × waves), computed by the engine's preview route, not the page (ADR 0045);
  - no channels ticked reads "Concept test — every persona sees the concept alone";
  - a feed without the TwHIN model reachable says so and blocks launch.
- **Run page:** turns per channel and waves completed.
- **Report page:** intent over waves by audience.
- **Session state:** every new input is kept with `useSessionState`.

### Acceptance criteria

- [ ] In headless Chrome, every checkbox combination launches, and the launch body carries exactly the ticked channels
- [ ] Launch reach appears only for word of mouth alone and is sent only then
- [ ] Changing the interval updates the listed wave ticks and the stated cost from the engine
- [ ] Reloading keeps the checkboxes, interval and launch reach
- [ ] `tests/test_interface.py` passes, and a grep of the frontend finds no `elicits`, `channel:` launch field or `ONE_ENVIRONMENT_NOTE`
- [ ] The report page draws one intent line per audience across the waves of a real fake-run record

---

## Phase 8: Measured

**User stories**: all, on real models

### What to build

One population drawn once, then real-model runs over it with the same seed:
- no channels;
- word of mouth alone;
- feed alone;
- forum alone;
- all three.

Each run is small (≤ 200 personas, a 6-tick horizon, a survey every 2 ticks) and runs under a systemd memory cap, one at a time. Record them as an evaluation in `docs/evaluations/`: per-wave intent, reach per channel, cost per wave, and anything that broke. Update RUN.md with the TwHIN server and the new flags.

### Acceptance criteria

- [ ] All five runs complete, or pause for a recorded reason, and each passes the trace validator
- [ ] The five runs share one population hash and five distinct world ids
- [ ] With no channels, intent is flat across waves up to scoring noise, which checks that waves only read
- [ ] The evaluation states the measured cost per wave, beside the estimate New Study showed
- [ ] RUN.md starts the TwHIN server, the gateway and a study with `--channels`, and was followed once, from a clean shell
