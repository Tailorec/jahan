# Evaluation: does simulated purchase intent track what developers really do?

*2026-10-02 · first real-world benchmark · 1,500 Stack Overflow personas · Qwen 3.8 Flash (thinking on) ·
Qwen3-Embedding 4B · run `run-4tm8fqby19qpnypthb6q59hexf`*

## The question

A concept test is only useful if the personas who say they would buy are, more often than not, the people who
really would. The persona corpus makes that checkable for one product: Stack Overflow respondents answered
whether they use AI tools for **code review** — currently (mostly or partly), plan to (mostly or partly), or do not
plan to (`ai_task_code_review`). So the engine was shown an AI code-review assistant and asked each persona how
likely it was to buy it; afterwards each persona's simulated intent was compared with its own row's real answer.

## How it was run

- **Population:** 1,500 personas drawn at random from the 113,120 Stack Overflow rows (shards 0004 and 0005),
  seed 4021, one audience with no filters, so the sample mirrors the source. It passed its distribution gates under
  the Holm correction (ADR 0049), which this study prompted.
- **What personas saw:** 29 attributes — demographics, years of experience, role, seniority, code-review and
  open-source habits, tools such as Git, GitHub and Python. **No AI attribute and no value mentioning AI**: not
  `att_ai`, `ai_task_*`, `coding_ai_*`, `coding_agent_*`, nor ChatGPT, Claude or Copilot usage. No attribute was
  completed by a model.
- **Concept:** *Codepilot Review*, $19 a month — "an AI code-review assistant that comments on your pull requests,
  explains risky changes and suggests fixes before a human reviewer looks". One survey wave, no channels.
- **Scale:** purchase intent scored by SSR against anchor set `purchase-intent-v1`, version v2, which passed its check
  on this embedding model (rank stability 1.00; the 0.6B model had failed at 0.75).
- **Truth:** each persona's `ai_task_code_review`, read from its corpus row after the run and never shown to it,
  ranked 5 (currently mostly AI-assisted) to 1 (does not plan AI use); "Not applicable" is excluded. *Measured*
  means the survey recorded the answer; the rest were inferred by the corpus's model from related answers.
- **Yardstick:** a demographic baseline that predicts the truth from attributes the personas did see (age,
  experience, role), fitted on 21,450 other Stack Overflow rows with a measured answer.

## Results

| | Personas | Spearman: simulation vs truth | Spearman: baseline vs truth | Real: use AI for review now | Simulated: top-two box |
|---|---:|---:|---:|---:|---:|
| Measured truth | 672 | **0.02** | 0.05 | 16% | 45% |
| Measured + inferred | 952 | 0.05 | 0.06 | 11% | 45% |

- **No person-level signal.** A correlation of 0.02 over 672 personas is indistinguishable from zero (its standard
  error is about 0.04). Simulated intent does not tell apart the developers who use AI for code review from those
  who do not plan to.
- **The yardstick barely does better.** Age, experience and role predict the truth weakly too (0.05): whether a
  developer uses AI for review is mostly not written in those attributes. So this benchmark asks a hard question,
  and the honest reading is that the simulation adds nothing beyond them.
- **The level is three times too high.** The simulation puts 45% in the top two boxes; 16% of these developers
  really use AI for code review. Part of the gap is the construct — "would buy a $19 tool" is not "uses AI for
  review" — but the direction matches the earlier holdout's finding of a biased overall picture.
- **Answers collapse to the middle.** For 83% of personas the most likely answer is the scale's midpoint; the mean
  score's standard deviation across 1,500 personas is 0.26 on a 1–5 scale. The model answered almost everyone with a
  variation of "I might try it if it helps, but I would not trust it blindly".
- **What it did pick up is the obvious cue.** Students' simulated top-two box is 0.23–0.24 against 0.44–0.49 for
  everyone else — the model reacts to "student" and a $19 price. Real students use AI for review no less than
  others (19–26% in this sample).

By group (measured truth, cells with at least 15 personas), the simulated level is nearly flat while the real one
varies: across age brackets real use runs 8–20% and simulated top-two 40–47%; across regions real use runs
11–47% and simulated 43–47%. Rank correlations across cells are unstable at these cell counts (−0.49 to 0.70) and
are not evidence either way.

## What it means

On this product and population, with this model, the engine's concept test does **not** predict who adopts. It
reproduces a plausible-sounding, middle-of-the-road answer for nearly everyone and adjusts it only for crude cues.
That is consistent with the 2026-09-17 holdout (relative structure weak, overall level biased) and with ADR 0018's
position that raw simulated distributions must be calibrated against measured marginals before they are read as
market facts. The engine's trust level stays **uncalibrated**.

## Threats to validity

- **Construct gap.** The truth is current or planned AI use for code review, not willingness to pay $19 for one
  product. A persona can rationally use a free tool and decline a paid one. A benchmark with a purchase outcome would
  be a stricter test.
- **One model, one prompt, one product.** A larger or differently prompted model may separate personas better;
  Qwen 3.8 Flash ran with thinking on and a single survey question.
- **Hidden attributes cut both ways.** Hiding every AI attribute is what makes this a fair test, but a real
  marketer would know some of them; the result says nothing about a study conditioned on them.
- **Free-route reliability.** 978 of about 2,480 chat calls returned an empty reply (zero output tokens) and were
  retried; every persona was scored in the end (no turn without intent), but some answers come from a retry.

## Reproduce

`analyze.py <run_id>` beside this file, run from the engine checkout with the corpus cached. The run's brief and
ontology are recorded in its run directory; personas' real answers are read from the corpus at analysis time and
are not stored here.
