# Children's education savings app — a real study, 2026-09-20

Run `run-71j7wta9hzpxy80dzmk91a65r2` (kept under `runs/`, not committed). Real models through a local LiteLLM
gateway over Bedrock — Amazon Nova Micro (chat) and Titan Text Embeddings v2 (scoring) — on the real Persona 1M
corpus. Brief: `examples/education_savings_app_persona1m.yaml`. Read back with `analyse.py` in this directory;
its numbers are in `results.json`.

**Trust is `UNCALIBRATED`.** Nothing here was checked against human purchase behaviour. This is a demonstration
that the pipeline runs and a look at what it says, not a fact about a market.

## What was run

| | |
|---|---|
| Population | 500 personas, population seed 4022, shards 0000/0004/0005, measured sources only |
| Audiences | parents of young kids (200), early career (150), retirees (150) — all three filled to the requested shares |
| Worlds | two replicates, seeds 4021 and 917731, 3 daily ticks, `survey_room` |
| Asked | purchase intent, on the `purchase_intent/v2` anchors (rank stability 0.929, collapse 0.777; `v1` fails its check) |
| Spend | $0.034 recorded, against a $1.00 budget. Both worlds `completed`, no degradation rung reached |
| Turns | 2,000 answered, 0 unscored. Ticks 1 and 2 reached all 500 personas each; tick 0 publishes the concept |

## The expectation written down beforehand, and what happened

Fixed before the run, in the brief's header:

1. **Parents of young kids show the highest stated purchase intent of the three audiences** (confident).
2. Early career versus retirees: no directional prediction (exploratory).

**Expectation 1 did not hold.** Top-two-box purchase intent, mean over personas, 95% bootstrap interval resampling
personas:

| | world 4021 | world 917731 | pooled |
|---|---|---|---|
| parents of young kids | 0.342 [0.325, 0.361] | 0.274 [0.260, 0.287] | 0.308 |
| early career | 0.341 [0.319, 0.363] | 0.364 [0.342, 0.386] | 0.352 |
| retirees | 0.376 [0.363, 0.389] | 0.361 [0.351, 0.373] | 0.369 |

Parents are the *lowest* pooled and in world 917731, and only tied with early career in world 4021. The
prediction was wrong here; it is reported as wrong, not adjusted.

## How much of this to believe

Very little of the ordering. Three reasons, each from the run itself:

* **The replicate spread is as large as the audience gaps.** The same 200 parents, the same concept, a different
  seed: 0.342 versus 0.274, a spread of 0.068. The gaps between audiences in world 4021 are 0.002 and 0.033. The
  bootstrap intervals above resample personas only, so they are narrower than the noise between worlds, and a
  pooled interval understates it further. With two worlds the spread cannot itself be given an interval.
* **The engine's own audience divergence is near zero** (0.001 and 0.006 in the two worlds), and its share-weighted
  adoption is 0.352 and 0.327 — a 0.025 spread between replicates.
* **Audience is confounded with where the persona came from.** Respondents by source, pooled:

  | audience | sources of the personas who answered |
  |---|---|
  | parents of young kids | 185 Stack Overflow, 15 wiki |
  | early career | 145 Stack Overflow, 5 wiki |
  | retirees | 130 GSS, 19 wiki, 1 Stack Overflow |

  Overall the drawn measured personas are dominated by two survey sources. "Parents" and "early career" here are
  developers who answered a developer survey; "retirees" are largely US General Social Survey respondents. A
  retiree-versus-parent gap is therefore also a GSS-versus-Stack-Overflow gap, and this run cannot separate them.
  It says nothing about parents in general.

## Things the run showed about the engine and the interface

* **Verbatims are stable per persona.** 800 pooled parent answers, 200 distinct texts: each persona says the same
  thing every time it is asked, across ticks and worlds. Persona-level variation comes from the population, not
  from sampling.
* **No communities formed**, so polarization is unmeasured and the digest says so with the reason. No word-of-mouth
  either: a survey room has no persona-to-persona channel.
* **The interrupted tick.** A machine reboot killed the study inside tick 2 of the first world. It resumed from the
  last closed tick under the same run id; the interrupted tick is counted as `discarded_ticks: 1` and its spend is
  in the record. Nothing was re-asked that had been closed.
* **Seed 4021 was refused as a population draw** (gate: `region` p = 0.034). It was not tuned; the draw was
  repeated with seed 4022, which passed. Seed 4021 remains a *world* seed.
* **Community detection crashed on population seed 4022** (`OverflowError`, a 64-bit seed against a signed
  64-bit limit). Fixed in `jahan/population/_communities.py` without changing any partition a fitting seed
  already produced.

## What would make this worth reading as more than a demonstration

* More than two replicate worlds, so the spread has an interval and an audience gap can be tested against it.
* Personas for the audience drawn from a source that is not one survey — or the audience's source mix held equal
  across audiences.
* A calibration against a human purchase-intent benchmark, which is the only thing that moves the trust level.
