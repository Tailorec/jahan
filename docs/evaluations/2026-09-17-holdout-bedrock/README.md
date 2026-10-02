# Evaluation: can an LLM fill in a persona's attitudes realistically?

*2026-09-17 · first real-model holdout · AWS Bedrock · Stack Overflow Developer Survey rows · total spend ≈ $0.66*

## The question

The persona corpus measures demographics for most people but almost no consumer attitudes: a GSS respondent was
never asked about coffee or brand loyalty. So when a study needs an attitude the data lacks, the engine asks a
model to fill it in from what it knows about the persona (ADR 0018), and samples the value from the probability
distribution the model states (ADR 0024). Those filled-in attitudes decide how personas react to a concept.

Everything the engine concludes therefore rests on one question, which ADR 0019 left owed: **are filled-in
attitudes anything like what real people would say?** This is the first time it was measured against a real
model.

## How it was measured

A holdout on people whose true answer is known:

1. Take Stack Overflow survey respondents whose attitude to AI (`att_ai`) was *measured* — they answered it
   (rows where a model had inferred it are excluded). The answers are `Enthusiast`, `Positive`, `Neutral`,
   `Skeptical`, `Opposed`.
2. Split them by seed: 75% form a **pool**, 25% are **held out**.
3. Hide `att_ai` on the held-out rows, and ask the model — through the engine's real projection path — for the
   probability of each answer.
4. Score those stated distributions against the answers the people actually gave.

A score needs something to beat. The **baseline** is plain counting with no model: for each held-out person, the
distribution of answers among *pool* respondents with the same attributes (add-one smoothed; a cell with fewer
than 5 pool rows backs off to the demographic cell, then to the whole pool). Held-out rows never inform it.

### Two information arms

Projection and the baseline always see exactly the same attributes:

- **Demographics** — only the conditioning set: `age_bracket`, `region`, `demo_employment_status`. This is the
  question ADR 0019 asks: how much of an attitude do demographics explain?
- **All** — every other declared attribute too, including `coding_ai_sentiment`, `years_experience`,
  `dev_professional_status` and `highest_education`. This shows what other known attitudes add.

### What the scores mean

| Score | Reads as | Better |
|---|---|---|
| **Log loss** | how much probability the stated distribution gave the true answer (floored at 1e-6) | lower |
| **Brier score** | squared distance between the stated distribution and the true answer | lower |
| **Marginal distance** | whether the *overall* mix of answers looks right, e.g. "70% favourable" (total variation) | lower |
| **Demographic pattern recovered** | share of the attitude's real dependence on demographics the predictions reproduce, above chance | higher |
| Calibration error | whether stated probabilities match observed frequencies | lower |

Log loss and Brier lead, because they are proper scoring rules: neither uniform guessing nor ignoring
demographics can score well on them. Marginal distance cannot see demographics, and calibration scores uniform
guessing as perfect, so neither is a verdict alone.

### Setup

| | |
|---|---|
| Endpoint | Bedrock `bedrock-mantle` OpenAI-compatible Chat Completions, `us-east-1`, short-term Bedrock API key |
| Gateway | none — the engine called Bedrock directly (ADR 0021 permits any OpenAI-compatible URL) |
| Models | `mistral.ministral-3-8b-instruct`, `deepseek.v3.2`; every response reported the pinned model as served |
| Seeds | holdout 4021, population 4021 |
| Completion temperature | 1.0 |
| Sizes | demographics arm: pool 11,834, held out 3,945 · all arm: pool 2,316, held out 772 |
| Reports | `reports/*.json` (aggregate scores only — no corpus rows, per ADR 0016) |

## Results

### Demographics arm — 3,945 held-out personas each

| | Log loss ↓ | Brier ↓ | Marginal distance ↓ | Pattern recovered ↑ | Calibration ↓ | Calls | Failures | Cost |
|---|---|---|---|---|---|---|---|---|
| **Baseline** | **1.237** | **0.651** | **0.009** | 100% | **0.015** | — | — | — |
| DeepSeek V3.2 | 1.489 | 0.765 | 0.264 | 71% | 0.046 | 158 | 0 | $0.426 |
| Ministral 3 8B | 1.705 | 0.828 | 0.370 | 90% | 0.086 | 165 | 0 | $0.067 |

### All arm — 772 held-out personas each

| | Log loss ↓ | Brier ↓ | Marginal distance ↓ | Pattern recovered ↑ | Calibration ↓ | Calls | Failures | Cost |
|---|---|---|---|---|---|---|---|---|
| **Baseline** | **1.165** | 0.600 | **0.047** | 100% | **0.062** | — | — | — |
| DeepSeek V3.2 | 1.201 | **0.527** | 0.215 | 100% | 0.159 | 33 | 0 | $0.107 |
| Ministral 3 8B | 5.962 | 1.073 | 0.504 | 0% | 0.420 | 43 | 0 | $0.022 |

Every run projected every held-out persona.

## What it shows

**On the question ADR 0019 asks, neither model beat plain counting.** Given only demographics, both lost to the
demographic-conditional baseline on every proper score.

**The failure is the overall level, not the pattern.** The models reproduce much of how the attitude varies across
demographic groups (71–90% of the real dependence) but hold a strongly wrong picture of developers as a whole:
marginal distance 0.26–0.37 against the baseline's 0.009. On the 115-persona smoke run, 70% of the real respondents
were `Enthusiast` or `Positive`; Ministral put 27% of its probability there and 26% on `Opposed`, which is 2% of
the truth. They believe developers are far more negative about AI than developers say they are.

**That points at calibration, not away from the method.** ADR 0018 already calls for judging projected values
against measured marginals. The result says raw model distributions should not be used as they come: keep the
relative pattern the model captures, and recalibrate the overall levels toward measured marginals where they exist.
Whether that combination beats the baseline is the next experiment.

**DeepSeek is viable; Ministral is not.** With every known attribute, DeepSeek roughly matched the baseline on log
loss (1.20 against 1.17) and beat it on Brier (0.53 against 0.60). Ministral writes hard `0.0` probabilities — on
the smoke run, 37 of 115 true answers received exactly zero — and each such answer costs the maximum penalty,
which is what drives its log loss to 5.96.

## Caveats

- **One attitude, one population, one prompt, one seed.** `att_ai` among software developers is not a consumer
  attitude, and a single seed gives no spread.
- **The baseline is unusually strong.** It is built from 75% of the *same* survey. An FMCG study has no measured
  joint of demographics and consumption to count from (ADR 0018), so "worse than this baseline" is expected here;
  the question this evaluation cannot answer is whether the model beats *having no measured data at all*.
- **The all arm is small.** 772 personas, and its baseline conditions on seven attributes with backoff.
- **Model choice.** Two inexpensive open-weight models. Stronger models were reachable on the same endpoint and were
  not tested. gpt-oss-120b was excluded: its reasoning consumed the answer budget, and 8 of 9 smoke-run calls were
  cut off at `max_tokens`.
- **Early smoke numbers were contaminated.** At 115 personas, before the information arms existed, DeepSeek appeared
  to beat the baseline (log loss 1.06 against 1.41). Projection had been shown `coding_ai_sentiment` for 100 of 115
  personas, and that attribute nearly is the answer (`Somewhat favorable` → `Positive` in 40 of 42 cases,
  `Somewhat unfavorable` → `Skeptical` in 5 of 5) while the baseline saw only demographics. Those numbers are not
  results.

## What the real run exposed in the engine

None of these were visible to the fake models the suite runs on. Each fix was proven by a test that fails on the old
code.

| Found | Effect | Fix |
|---|---|---|
| The repair turn was a `system` message after the model's answer | Bedrock refused every repair: *"Unexpected role 'system' after role 'assistant'"* | `a6e49fb` — the repair is a user turn |
| The answer budget counted probabilities but not each persona's id | A 25-persona answer needed 1,132 tokens (1.25 characters a token) against a budget of 1,064, and was cut off mid-list | `f9bcd1e` — the budget counts ids and punctuation |
| A cut-off answer was sent for a repair at the same budget | A repair that can only be cut off again | `242021e` — recorded as cut off, in one call |
| Projection re-parsed answers with bare `json.loads` | Every fenced answer the client had accepted was read as empty; the first working run completed zero fields | `699592b` — one lenient parser shared by the client and every caller |
| A failed or discarded call carried no cost | Eight cut-off answers were billed and never counted | `5878f9c` — failures and discarded attempts carry their billed costs |
| Projection saw every known attribute; the baseline saw only demographics | A correlated attitude leaked the answer; on a test fixture the old evaluation reports an unearned 0.632 log-loss advantage | `1dbb167`, `cf74670` — two information arms with matched baselines |

## Cost

Priced from the AWS Pricing API, us-east-1 standard on-demand, per million tokens: Ministral 3 8B $0.15 in /
$0.15 out; DeepSeek V3.2 $0.62 / $1.85; gpt-oss-120b $0.15 / $0.60.

| | Cost |
|---|---|
| Four measured runs above | $0.622 |
| Smoke runs, availability probes and budget measurement | ≈ $0.03 |
| gpt-oss cut-off calls billed before failed-call costs were recorded | ≈ $0.01, estimated |
| **Total** | **≈ $0.66** |

A demographics-arm run of 3,945 personas takes about one minute on Ministral and two on DeepSeek.

## Follow-ups

1. **Calibration.** Keep the model's relative pattern, recalibrate overall levels toward measured marginals, and
   re-score both arms. This tests whether ADR 0018's calibration makes projection competitive.
2. **Stronger models.** Re-run the demographics arm on state-of-the-art models reachable on the same endpoint, to
   see how much of the marginal bias is the model and how much is shared. Calibration stays required either way:
   the error was a confident wrong prior, which larger models can share.
3. **A no-data comparison.** Score projection against a prior with no measured joint — the situation an FMCG study
   is actually in.
4. **Engine gaps this run left open.** Reasoning models need a reasoning-effort setting or budget room; the holdout
   command cannot declare a model's price or accepted aliases, so its costs record as `unknown`.

## Reproducing

```bash
# a short-term Bedrock API key, derived from existing AWS credentials (expires within 12 hours)
python -c "from aws_bedrock_token_generator import provide_token; print(provide_token(region='us-east-1'))"

JAHAN_INFERENCE_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/v1 \
JAHAN_INFERENCE_API_KEY=<key> \
  python -m jahan.holdout --endpoint --model deepseek.v3.2 --information demographics --pool 20000 --out report.json
```

`run_holdout.py` in this directory produces the same report and also meters tokens, cost and failure kinds. The
corpus shards must be cached locally; see `examples/README.md`.
