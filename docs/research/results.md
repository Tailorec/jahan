# Results so far

Everything Jahan has measured, positive and negative, in the order it was run. Each row links to the full
write-up, with its setup, numbers, caveats and the engine defects the run exposed. All real-model runs used
AWS Bedrock; the total spend across all of them is under USD 2.

| Date | Evaluation | Result |
|---|---|---|
| 2026-09-17 | [Holdout: can a model fill in attitudes?](#holdout) | **Negative.** Both models lose to a demographic baseline on every proper score |
| 2026-09-17 | [Anchor check on Titan v2](../evaluations/2026-09-17-elicitation-titan/README.md) | **Negative.** `purchase_intent/v1` rank stability 0.500 (needs > 0.8); not pinned |
| 2026-09-17 | [Anchor check on Nova 2](../evaluations/2026-09-17-elicitation-nova/README.md) | **Negative.** Same failure on a second model (0.500); confirmed by an independent recompute outside the engine |
| 2026-09-18 | [First whole study on a real model](../evaluations/2026-09-18-first-real-study/README.md) | **Runs.** 200 personas, 4,052 events validate; the run exposed defects that had zeroed belief change and word of mouth |
| 2026-09-18 | [Analysis reconciled on a regenerated study](../evaluations/m10-analysis/README.md) | **Reproducible.** Every digest figure recomputed from raw events |
| 2026-09-19 | [The conditioning effect](../evaluations/2026-09-19-conditioning-effect/README.md) | **Positive.** Without a persona block, all 150 personas give the same answer (sd 0.0); with it, sd 0.153 |
| 2026-09-19 | [First measured study](../evaluations/2026-09-19-first-measured-study/README.md) | **Positive.** `purchase_intent/v2` passes its check on the first attempt (0.929); adoption measured for the first time |
| 2026-09-20 | [Education savings app](../evaluations/2026-09-20-education-savings/README.md) | **Pre-registered prediction failed.** Parents were expected to show the highest intent; they showed the lowest |
| 2026-09-20 | [Feed and forum on real models](../evaluations/2026-09-20-non-survey-channels/README.md) | **Runs.** Both channels work end to end; two defects found and fixed |
| 2026-10-01 | [Channels and survey waves](../evaluations/2026-10-01-m15-channels/README.md) | **As predicted.** With no channels, intent is flat across waves; with channels, it moves |
| 2026-10-01 | [Where a study's memory goes](../evaluations/2026-10-01-run-memory/README.md) | **Engineering.** About 40% less memory per tick, identical results byte for byte |

## Holdout

*Can a model fill in a persona's attitudes realistically?*
([full write-up](../evaluations/2026-09-17-holdout-bedrock/README.md))

Survey rows measure demographics but rarely consumer attitudes, so the engine asks a model to fill them in.
This tests that on Stack Overflow respondents whose real attitude to AI is known: 25% are held out, the model
predicts their answer from what else is known about them, and the prediction is scored against what they
actually said. The baseline is plain counting: the answer mix among the other 75% with the same attributes.

| Demographics only (3,945 held out) | Log loss ↓ | Brier ↓ | Marginal distance ↓ | Pattern recovered ↑ |
|---|---|---|---|---|
| **Baseline (counting)** | **1.237** | **0.651** | **0.009** | 100% |
| DeepSeek V3.2 | 1.489 | 0.765 | 0.264 | 71% |
| Ministral 3 8B | 1.705 | 0.828 | 0.370 | 90% |

**What it shows.** Given only demographics, neither model beats counting. The failure is in the overall level,
not the pattern: the models reproduce 71–90% of how the attitude varies between demographic groups, but think
developers as a whole are far more negative about AI than developers say they are. That supports calibrating
filled-in values against measured marginals rather than using raw model output
([ADR 0018](../adr/0018-calibrate-against-marginals-rather-than-fusing-persons.md)).

How the scores work is on the [methodology](methodology.md#scoring-a-prediction) page.

## Conditioning

*Does telling the model who it is change the answers?*

Same 150 personas, same stimulus, same model, same seeds. The only difference is the persona block.

| | conditioned | unconditioned ("You are a person.") |
|---|---|---|
| mean top-two-box | 0.433 | 0.435 |
| **spread of top-two-box between personas** | **0.153** | **0.0** |

Without conditioning, the mean barely changes, but the population collapses into one respondent repeated. This
is why conditioning is an invariant the engine enforces, not a setting.

## Channels move intent; no channels does not

Five studies over one population of 60, identical except for their channels. Adoption at each survey wave:

| Channels | tick 0 | tick 2 | tick 4 | tick 5 |
|---|---|---|---|---|
| none | 0.327 | 0.327 | 0.327 | 0.327 |
| word of mouth | 0.323 | 0.306 | 0.309 | 0.294 |
| social feed | 0.327 | 0.523 | 0.474 | 0.458 |
| forum | 0.327 | 0.476 | 0.442 | 0.435 |
| all three | 0.327 | 0.463 | 0.439 | 0.439 |

With no channels intent is exactly flat, as "a survey wave only reads" predicts. With channels it moves. One
seed per study, 60 personas, uncalibrated: this shows the mechanism works, not how a market would respond.

## A prediction that failed

Before the education-savings study ran, its brief recorded the expectation that parents of young children would
show the highest purchase intent of three audiences. They showed the **lowest** (pooled top-two-box 0.308,
against 0.352 and 0.369). The prediction is reported as wrong, not adjusted.
