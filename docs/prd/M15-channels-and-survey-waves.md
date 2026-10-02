# PRD — M15 Channels and survey waves: information spreads the ways a study chooses, and intent is tracked

## Problem Statement

A study exists to answer one question: **how does purchase intent change as word about a product spreads?** The
engine was designed to answer it by combining two pieces of research:

* **OASIS** (camel-ai/oasis) — language-model agents living on a social platform: an X-like feed or a Reddit-like
  forum, a recommender deciding what each agent sees, a clock deciding who is active, and actions (post, like,
  repost, reply, vote, follow) through which information spreads. Jahan adds a third way information travels:
  word of mouth along the population's social ties.
* **SSR** (arXiv 2510.08338, *LLMs reproduce human purchase intent via semantic similarity elicitation of Likert
  ratings*) — a persona answers a purchase-intent question in words, and the answer becomes a distribution over a
  five-point scale by its similarity to anchor statements. It was validated as a one-shot survey of a concept.

The combination is a tracking panel inside a social simulation: information spreads through whichever channels the
study chose, and at fixed intervals every persona is surveyed for purchase intent, so intent becomes a trajectory
over time. The architecture specified exactly that — a scenario carried a list of channels, and "a persona reacts once
per channel per tick" (FINAL_ARCH, ARCHITECTURE, the M7 PRD and plan).

The engine does not do it. Measured against the code on 2026-09-29:

* **One platform per world.** `WorldConfig.platform` is a single channel, and `World._presentations`
  (`jahan/world/env.py`) takes exactly one branch: feed, forum or survey room. Feed and forum cannot run together.
* **Word of mouth is hard-wired**, not chosen: always on beside a feed or forum, always off in the survey room. It
  cannot be switched off, and it cannot run alone — a word-of-mouth-only study drew its population and crashed on
  the first tick, so it was removed as a choice (2026-09-20).
* **The channel is not part of the study.** `Scenario` has no channel field; `--channel` goes straight to the world.
  A feed run and a forum run over the same population and seed had the same config hash (`f520aa3d566de4a2`) and the
  same world id (`4c541b71bddd`): a result cannot say which environment produced it, and a resume naming another
  channel is not refused.
* **Purchase intent is not tracked.** A scenario's single `elicits` task applies to every turn of every tick. With
  `reaction`, personas spread information and no intent is ever measured; with `purchase`, intent comes from whoever a
  platform happened to activate that tick, mixed into what they did there — not from the population on a schedule.
* **The feed is not X-like and the forum is not Reddit-like.** Nothing sets `recsys_mode`, so every study ranked both
  at random — the control arm. The `twitter` interest mode exists but would not work either: no persona profile vector
  or post vector is ever computed, so every score is zero.

The divergence began on **2026-09-17**, when the first world phase (`4fd9a8e`) built a single `platform` per world;
the scenario's list of channels never reached the code. Every later step built on it, each platform was tested on its
own, and no acceptance criterion required two channels in one world or intent over time, so the gap never failed a
test.

## Solution

A study makes two independent choices, both recorded on its scenario (ADR 0048):

1. **Which channels spread information** — any combination of three checkboxes, including none:

   | Channel | What happens | Ranking |
   |---|---|---|
   | Social feed (X-like) | active personas see a feed and can post, like, repost, comment, follow | as OASIS's X: posts from the persona's ties and follows, most liked first, plus recommended posts by interest × recency, interest measured with TwHIN-BERT |
   | Forum (Reddit-like) | active personas see threads and can post, reply, vote | Reddit's hot score, verbatim |
   | Word of mouth | a persona who reacts strongly tells close ties, who hear on the next tick | the social graph |
   | *none* | nothing spreads; each persona only ever sees the concept | — |

2. **When purchase intent is measured** — a **survey wave** every *k* ticks, always at tick 0 and the last tick. Every
   persona answers the SSR purchase-intent question about the concept, at the end of its tick, apart from anything
   they did on a channel. A wave only reads: answering changes nothing about the persona.

One simulation runs one world with its channels fixed from launch to horizon. An experiment on channels is another
simulation over the same population and seed; the two worlds have different identities and share their random draws,
so the difference between their intent trajectories is what the channels did.

A study with no channels and one wave at tick 0 is today's concept test. The survey room stops being an environment.

## User Stories

1. As a researcher, I want to tick any combination of social feed, forum and word of mouth, so a study spreads
   information the ways I choose and no other.
2. As a researcher, I want to tick no channel at all, so I can run the concept test — every persona judges the concept
   alone — as the baseline for a study that spreads.
3. As a researcher, I want feed and forum to run together in one world, with an active persona reacting once on each
   per tick, so the two platforms' dynamics coexist rather than exclude each other.
4. As a researcher, I want word of mouth as its own switch — on beside a platform, off beside one, or alone — so its
   contribution can be isolated.
5. As a researcher, I want a word-of-mouth-only study to start from a launch reach — a random share of personas, 10% by
   default, who hear of the product first-hand — so there is something to pass on.
6. As a researcher, I want purchase intent measured in survey waves every *k* ticks, always including tick 0 and the
   last tick, so intent is a trajectory with a baseline and an endpoint.
7. As a researcher, I want every persona surveyed in every wave, so a change between waves is movement, not sampling.
8. As a methodologist, I want a survey to read a persona and change nothing about it — no memory of answering, no belief
   update — so the measurement never drives what it measures.
9. As a methodologist, I want a wave to come at the end of its tick, so the tick-0 wave is the post-launch baseline and
   the wave at tick *t* reflects everything up to *t*.
10. As a methodologist, I want the survey to show the concept, so a persona no channel reached still answers — cold —
    and the gap between reached and unreached personas is part of what a study shows.
11. As a researcher, I want channel turns always to be reactions and purchase intent to come only from waves, so intent
    and adoption have one source, one schedule and one respondent set in every study.
12. As an analyst, I want a purchase on a channel recorded as behaviour and kept apart from adoption, so the headline
    never mixes what personas did with what they said they intend.
13. As a researcher, I want the budget never to thin a wave — a world pauses before a wave it cannot afford — so every
    recorded wave was answered by everyone, and the run page says where it stopped.
14. As a researcher, I want New Study to show a wave's cost before launch, so I set a budget that covers the waves.
15. As a methodologist, I want the channels, survey interval and launch reach hashed into the world and config
    identity, so two simulations with different channels are different worlds and a resume that changes them is refused.
16. As a researcher, I want a second simulation over the same population and seed, differing only in channels, to
    share its random draws with the first, so comparing their trajectories isolates the channels.
17. As a researcher, I want the feed ranked as OASIS ranks X — ties and follows most liked first, plus recommendations
    by interest × recency with TwHIN-BERT — so the feed spreads information the way the paper's platform does.
18. As a researcher, I want the forum ranked by Reddit's hot score, so it herds the way the paper's forum does.
19. As an operator, I want TwHIN-BERT served locally behind the same OpenAI-compatible gateway and pinned as the feed's
    own embedding model, so it costs nothing and every model call stays pinned and recorded (ADR 0021).
20. As a methodologist, I want the TwHIN-BERT vectors computed exactly as OASIS computes them (`pooler_output`, 512-token
    truncation), so the ranking matches upstream behaviour.
21. As a methodologist, I want purchase intent still scored with the embedding model its anchors were checked against,
    so the SSR evidence still applies; a different model needs its anchors re-checked first.
22. As an analyst, I want intent and adoption per wave, per audience, as a trajectory, so the report says how intent
    moved as information spread.
23. As an analyst, I want spread measured per channel — who was reached, by which channel, and word-of-mouth paths — so
    a change in intent can be read against what reached whom.
24. As a reader, I want the report's method section to state the channels, the survey interval, the launch reach, both
    embedding models, and where the port departs from OASIS, so a result says how it was produced.
25. As a researcher, I want a population's social graph and personas unchanged by the channel choice, so the same
    people can be simulated under different channels.
26. As an operator, I want an old run to stay readable and its resume refused with a clear reason, so the identity
    change never corrupts a record.

## Implementation Decisions

**Scenario (`schemas`).** `Scenario` gains `channels` (a set of `social_feed`, `forum`, `wom`; empty allowed),
`survey_every` (a positive tick count) and `launch_reach` (a share, meaningful only when `channels == {wom}`, default
0.10). `elicits` is removed. `STUDY_CHANNELS` goes; the survey room is no longer a study choice. The fields enter the
scenario's canonical hash, so world ids and config hashes change (ADR 0048). A validator refuses a launch reach set
when word of mouth is not the only channel, and a horizon too short for one wave.

**The feed's ranking model.** A new pinned role, `recsys_embed`, beside `embed`: the model id of TwHIN-BERT as served by
the gateway. It is recorded on `RunConfig` and in the method disclosure. SSR keeps `embed`.

**World (`world/env.py`).** `WorldConfig.platform` becomes the scenario's channel set. `_presentations` presents every
ticked platform: an active persona gets one impression per ticked platform, plus a word-of-mouth impression when told
and word of mouth is ticked. Feed and forum keep separate platform state. Word of mouth delivers only when ticked, and
beside no platform it starts from the launch reach: at tick 0, a seeded random share of personas is exposed to the
concept first-hand. On a wave tick the world also emits one survey impression per persona — the concept, one
exposure, `Channel.SURVEY_ROOM` retained internally as the wave's channel — after the tick's channel presentations.
Wave impressions never touch platform state and never spark word of mouth.

**Ranking (`world/recsys.py`).** The forum uses `reddit_hot` (already verbatim). The feed ports OASIS's X refresh:
in-network posts from the persona's ties in the social graph and anyone it follows during the study, most liked
first; out-of-network posts scored `cosine(profile, post) × log((271.8 − age) / 100)`, with age in ticks. A persona's
profile is its rendered attributes plus its latest post, as upstream appends "Recent post". Vectors come from
`recsys_embed`: each persona's profile once at world build, each post when published, cached on the world and
replayed from the trace on resume — never recomputed per tick.

**TwHIN-BERT serving (a tool, not the engine).** A small script in the repository's tools serves
`Twitter/twhin-bert-base` with an OpenAI-compatible `/embeddings` endpoint returning `pooler_output` with 512-token
truncation, exactly as OASIS's `process_recsys_posts.py`. It runs outside the engine, behind the LiteLLM gateway, so
PyTorch and Transformers never enter the engine's dependencies. RUN.md gives the command and the gateway entry.

**Runner (`runner/_run.py`).** The task is per job, not per run: platform and word-of-mouth presentations are
reactions; survey presentations are purchase intent. A survey outcome is recorded and scored but does not advance the
persona's state: no memory, no belief update, no snapshot. The degrade ladder applies to channel activity only; before
a wave tick, if the projected cost of the wave does not fit the remaining budget, the world pauses and records why.

**Agent (`agent`).** A survey turn asks the frozen SSR intent question over the concept, with the persona's memory in
context; its reaction carries no action. Channel turns keep today's reaction envelope.

**Analysis (`analysis`).** The digest's intent and adoption come from survey turns only, per wave and per audience —
an intent trajectory beside the existing belief trajectories. Spread per channel: exposures by channel and reason,
reach over ticks, word-of-mouth paths. Purchases on channels are counted as behaviour.

**Report (`report`).** A finding for intent and adoption over waves by audience. The method disclosure lists the
channels, survey interval, launch reach, the chat model, both embedding models, and the OASIS departures below.

**Command line and web.** `--channels feed,forum,wom` (empty for none), `--survey-every k`, `--launch-reach 0.1`
replace `--channel` and `--elicits`. The launch API takes the same fields and validates them. The gate is unaffected:
it draws the population, which does not depend on channels.

**Interface.** New Study replaces the Environment select and "Asked — what personas answer" with three channel
checkboxes, a survey interval, and a launch reach shown only when word of mouth is the only channel; it shows the
waves' cost before launch. The run page shows per-channel activity and waves completed. The report page shows the
intent trajectory by audience.

**Where the port departs from OASIS**, stated in the method disclosure: follows start from the generated social graph
rather than an imported follow list; a profile is a persona's rendered attributes, not a user bio; recency is in ticks;
there is no 4,000-post pre-filter, since a study has far fewer posts; the embedding server is reached through the
gateway rather than loaded in-process.

## Phases

1. **The scenario carries channels and waves.** Schema fields, hashing, validators; command line and API accept them;
   a no-channel study with one wave at tick 0 runs end to end through the new path (the concept test).
2. **Survey waves.** Every-*k* schedule with tick 0 and the last tick; end-of-tick placement; read-only survey turns;
   per-job tasks; `elicits` removed; the budget pauses before an unaffordable wave.
3. **Channels together.** Every ticked platform presented; feed and forum in one world; word of mouth as its own
   switch; launch reach for word of mouth alone.
4. **The forum ranks like Reddit.** `reddit_hot` switched on for the forum.
5. **The feed ranks like X.** `recsys_embed` pin; the TwHIN-BERT server tool and gateway entry; profile and post
   vectors; in-network plus interest × recency ranking; resume replays the vectors.
6. **Intent over time.** Intent and adoption per wave and audience; spread per channel; the report's trajectory finding
   and method disclosure.
7. **The interface.** New Study checkboxes, interval, launch reach and wave cost; run and report pages.
8. **Measured.** One real-model study per channel combination of interest over one population, recorded as an
   evaluation; RUN.md updated.

## Out of Scope

* Comparing channel mixes inside one run: an experiment is another simulation (a sweep may vary channels later).
* A survey panel or a fresh sample per wave: every persona answers every wave.
* Survey answers entering memory (panel conditioning).
* Forum presets other than Reddit-global, and a user-chosen ranking mode: `random` and `community_scoped` stay in the
  engine as control arms.
* The `twhin` degree-centrality mode as a user choice.
* Changing a study's channels mid-simulation.
* Validating SSR for repeated measurement; the report states it is an extension of the paper's one-shot evidence.

## Further Notes

* ADR 0048 records the identity decision; `CONTEXT.md` defines **Channel**, **Survey Wave** and **Launch Reach**, and
  updates Impression, Affordance, Degradation and Adoption.
* Cost: a wave costs one chat call and one embedding per persona. 2,000 personas surveyed every 2 ticks over a
  10-tick horizon is six waves, 12,000 answers; New Study states it before launch.
* Validity: SSR's evidence is for a one-shot survey; repeated waves over one population are an extension, stated in
  every report. Changing the SSR embedding model requires re-checking the anchors (`ssr-replica`); the feed's ranking
  model carries no such check.
* The OASIS source used for the port is the local checkout at `github_interesting/oasis`
  (`oasis/social_platform/recsys.py`, `process_recsys_posts.py`, `platform.py`); pin its commit in the plan.
