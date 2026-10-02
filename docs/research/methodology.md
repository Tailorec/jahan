# Methodology

Jahan is a research instrument for one question: **can a grounded synthetic population reproduce how people
respond to a product?** This page states what would count as evidence, how the engine is built to produce it
honestly, and how predictions are scored.

## Two claims, kept apart

A simulated purchase-intent number rests on two separate claims, and only one of them can be checked today.

| | Mapping claim | Simulation claim |
|---|---|---|
| **Says** | converting free text to a rating distribution (SSR) recovers the rating a real person gave from what they wrote | simulated personas' rating distributions for a product match what real people's would be |
| **Checked with** | human writing that carries its own rating, such as product reviews with stars | human answers to the same question about the same product |
| **Status** | owed: needs an anchor version that passes its check on the satisfaction construct | owed: no human purchase-intent benchmark exists yet |

A study's findings rest on the **simulation claim**, which is why every report says *uncalibrated*
([ADR 0028](../adr/0028-elicitation-validates-the-mapping-and-owes-the-simulation.md)). The SSR paper tested
the simulation claim on its own surveys and anchors; Jahan uses different anchors and embedding models, so it
inherits none of that evidence.

## Principles the engine enforces

These are not guidelines. Each is a check in the code that refuses to proceed.

1. **Personas are sampled, never invented.** Every persona is a real dataset row; a model may fill in some
   fields, but never demographics or psychographics, and every field states its
   [evidence tier](../concepts/population.md#how-much-each-value-is-worth-evidence-tiers).
2. **No numeric elicitation.** Intent is stated in words and scored by similarity; an answer carrying a rating
   is a failure, not a data point.
3. **Instruments are frozen before they are tested.** An anchor version is fixed before its check runs, and a
   failing version is never edited and re-checked; a fix is a new version. Model pins, prompts and thresholds
   are recorded and hashed with every run.
4. **Every number is traceable.** Every finding resolves to the trace events behind it and carries the
   real-world test that would falsify it. A digest recomputes from the trace alone.
5. **Absence is reported as absence.** Something not measured is *unmeasured*, with its reason, never zero.
6. **Trust cannot be overclaimed.** A trust level above *uncalibrated* requires a hashed reference to a human
   benchmark, and nothing in the repository can produce one.
7. **Expectations are written down first.** Where a study tests a prediction, the prediction goes in the brief
   before the run, and a wrong prediction is reported as wrong
   ([example](results.md#a-prediction-that-failed)).

## Determinism and replication

Every random draw derives from a seed, a tick and a named purpose, through SHA-256, so two processes on two
machines draw identically, and adding a new kind of draw cannot shift an existing one. Model outputs are not
deterministic across providers, so **reproducibility comes from the record, not from re-asking models**: a run
replays from its trace exactly ([ADR 0011](../adr/0011-worlds-resume-by-replaying-their-trace.md)).

Variance is estimated the honest way: each scenario runs under several replicate seeds, and the
[replicate spread](../concepts/scenarios-and-worlds.md#replicate-spread) between them is reported beside every
number and used as the yardstick for anomalies. One seed means no estimate of noise, and the report says so.

## Testing without a network

The engine's test suite runs with no API keys and no dataset downloads. Every non-deterministic boundary (the
model endpoint, the corpus, the trace store, evidence fetching) sits behind a port with an in-memory stand-in.
That proves the engine is **internally** correct. It cannot prove that conditioning changes answers or that
anchors order correctly, since a stand-in model answers whatever it was written to answer. Those claims are
measured on real models, separately, as [evaluations](results.md).

## Scoring a prediction

The holdout evaluation scores a stated probability distribution against the answer a real person gave, with
**proper scoring rules**[^gneiting]: scores that are best in expectation only when the stated probabilities are
the true ones, so neither hedging nor overconfidence pays.

For $N$ held-out people, person $n$ gave answer $y_n$ and the prediction stated probability $p_{n,k}$ for each
of the $K$ possible answers.

**Log loss** (natural log, each probability floored at $10^{-6}$ so one zero cannot make the mean infinite):

$$
\text{LL} = -\frac{1}{N} \sum_{n=1}^{N} \ln \max\!\big(p_{n, y_n},\ 10^{-6}\big)
$$

**Brier score**[^brier], summed over answers and averaged over people:

$$
\text{BS} = \frac{1}{N} \sum_{n=1}^{N} \sum_{k=1}^{K} \big(p_{n,k} - [k = y_n]\big)^2
$$

Lower is better for both. Log loss punishes a confident miss without limit; Brier is bounded (between 0 and 2).

!!! example "Worked example"
    Answers: *Enthusiast, Positive, Neutral, Skeptical, Opposed*. A prediction states
    $(0.10, 0.50, 0.20, 0.15, 0.05)$; the person said **Positive**.

    - Log loss: $-\ln 0.50 = 0.693$.
    - Brier: $(0.10)^2 + (0.50 - 1)^2 + (0.20)^2 + (0.15)^2 + (0.05)^2 = 0.01 + 0.25 + 0.04 + 0.0225 + 0.0025 = 0.325$.

    Had it stated $0$ for *Positive*, the log loss would be $-\ln 10^{-6} = 13.8$, which is how one model's hard
    zeros drove its mean log loss to 5.96.

**The baseline** a prediction must beat is plain counting, with no model. For a held-out person, take the
pool respondents with the same attributes and count their answers, with add-one (Laplace) smoothing so an
answer the group never gave is improbable rather than impossible:

$$
P(k \mid \text{group}) = \frac{\text{count}_k + 1}{N_{\text{group}} + K}
$$

A group with fewer than 5 pool rows backs off to the demographic group, then to the whole pool.

!!! example "Worked example"
    12 pool respondents share a held-out person's attributes, answering $(1, 6, 3, 2, 0)$ across the five
    answers. The baseline states $(2, 7, 4, 3, 1) / 17 = (0.118, 0.412, 0.235, 0.176, 0.059)$.

Two more measures are reported but never decide alone. **Marginal distance** (total variation between the
overall predicted and true answer mixes) cannot see demographics. **Calibration error** scores uniform guessing
as perfect. Proper scores lead because the others can each be gamed.

[^gneiting]: T. Gneiting and A. E. Raftery (2007). "Strictly proper scoring rules, prediction, and estimation."
    *Journal of the American Statistical Association*, 102(477), 359–378.
[^brier]: G. W. Brier (1950). "Verification of forecasts expressed in terms of probability." *Monthly Weather
    Review*, 78(1), 1–3.
