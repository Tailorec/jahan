# The non-survey environments, run with real models — 2026-09-20

The interface offered `social_feed`, `forum` and `wom` as environments but only `survey_room` had ever been run
against real models. Each was run on the same brief (`examples/education_savings_app_persona1m.yaml`), the same 60
personas (population seed 4022, shards 0004/0005, gss and stackoverflow), one world (seed 4021), three daily ticks,
Amazon Nova Micro and Titan Text Embeddings v2 through the local gateway. These are runs to see whether each
environment works, not a comparison of them: one world each, 60 personas, no replicate.

| | `social_feed` | `forum` | `forum`, from the interface (30 personas, 2 ticks) | `wom` |
|---|---|---|---|---|
| Result | completed | completed | completed after a fix, below | refused |
| Turns (tick 1, tick 2) | 60, 110 | 60, 109 | 30 | — |
| Scored turns | all | all | all | — |
| Actions | like 103, buy 40, follow 15, ask_peer 10, comment 2 | upvote 61, reply 49, buy 32, downvote 10, reject 9, ask_peer 8 | reply 21, upvote 9 | — |
| Communities formed | 4 | 4 | 4 | — |
| Polarization | 0.0005 | 0.053 | 0.015 | — |
| Word-of-mouth deliveries | 81 | 52 | 0 | — |
| Recorded cost | $0.0103 | $0.0076 | $0.0006 | — |

Both real-model environments ran end to end: every turn scored, no degradation rung, every recorded cost priced by
the gateway or served from the response cache. The survey room's baseline study formed no communities, so
polarization was unmeasured there; the forum measures it, and its verbatims carry the thread's content ("I'm
retired and not planning for a child's education") where the feed's are generic.

## What was wrong, and is fixed

* **`wom` is not an environment.** It is a channel a message is *delivered* on, beside a feed's or forum's own
  presentation. Asking to run a study on it drew the whole population and then failed on the first tick with
  `the wom channel is delivered, not presented`. The command, the API and the interface now offer only the three
  environments a study runs on, from one definition (`STUDY_CHANNELS` in `simcore/schemas/enums.py`), and the command
  refuses `wom` at parse time, before anything is drawn.
* **A forum study crashed its own report.** The interface-launched forum study finished its world and then died
  building the digest: `a response mass contains a zero, which the SSR softmax cannot emit`. The published SSR formula
  the engine computes (ADR 0026) gives the least similar anchor *exactly zero* within each set, and a community
  whose members agree averages to zero there. That is 16% of turns in the survey study and 63% here, so a small
  community all at zero is ordinary, and the digest's mass type still carried the softmax-era rule that forbade it.
  The digest now accepts a non-negative mass; a negative one, or one that does not sum to one, is still refused.
  The world was not re-run: the study was resumed and only its analysis ran.
* **`progress.json` said `completed` before the report existed.** It is now written after the report and
  `result.json`.

## What was found and is not fixed

* **The channel is not part of a run's recorded configuration.** The `social_feed` and `forum` runs above have the
  same `config_hash` (`f520aa3d566de4a2`) and the same world id (`4c541b71bddd`), because a scenario, a seed and a
  population make the id and the environment is none of them. Two consequences follow from that, the second not
  demonstrated: a result cannot say from its config hash which environment produced it, and a resume that names a
  different `--channel` than the run began with would presumably not be refused as a moved input. Interface resumes
  reuse the recorded launch and so keep the channel. Making the channel part of the scenario changes every existing
  world id and config hash, so it wants a decision (an ADR), not a patch.
* **`exposure_dropped` reads `budget_exhausted`, and it is not money.** A scenario's `exposure_budget` (3) is how many
  stimuli one persona can be shown per channel per tick; those beyond it are recorded as dropped. Both runs record 120
  such drops for 60 personas over two scored ticks. The reason string reads like a spending limit.
