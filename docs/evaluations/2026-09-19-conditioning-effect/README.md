# Evaluation: the conditioning effect, measured

*2026-09-19 · M6 phase 3's owed criterion · 150 personas, two arms, real model · Bedrock spend < $0.01*

The architecture says conditioning is the invariant `agent` exists to own, and that an invariant
deciding validity cannot be co-owned. The PRD justifies it from the SSR literature: unconditioned
personas produce *optimistic, narrow* distributions. Until now nobody had measured it here —
the criterion was explicitly marked "not tickable with a fake", because a stand-in model returns
whatever the stand-in was written to return.

## What ran

Two arms over the same 150 personas, the same stimulus, the same question, the same pinned scale
(`purchase_intent/v2`), the same seeds and the same model (`amazon.nova-micro-v1:0`). The only
difference is what the persona block says:

| arm | persona block |
|---|---|
| conditioned | the block the ontology selects, describing that person |
| unconditioned | `"You are a person."` — identical for everyone |

The block is swapped through `PersonaBlockCache.block_for`, the seam the runner already owns, so
nothing in the engine is modified and both arms travel the same path. The block stays non-empty
deliberately: *a turn cannot proceed unconditioned* is the invariant itself, and the third arm
below exercises that refusal.

## What it found

| | conditioned | unconditioned |
|---|---|---|
| scored | 150 / 150 | 150 / 150 |
| mean top-two-box | 0.4329 | 0.4352 |
| **sd of top-two-box** | **0.153** | **0.0** |
| mean expected rating | 3.2018 | 3.3399 |
| sd of expected rating | 0.5383 | 0.0 |
| **distinct answers** | **57** | **1** |
| distinct verbatims | 57 | 1 |

Conditioned, personas answer from their own attributes:

> "I'm inclined to try it since it's protein-rich and fits my fitness routine."
> "I'm not likely to buy it because I don't usually exercise and I'm not interested in protein drinks."

Unconditioned, 150 personas return one sentence, character for character:

> "I'm neutral about buying it; it sounds like a typical health product."

**The invariant holds on the real path.** An empty persona block refused all three jobs it was
given, with kind `unconditioned`, before any call was dispatched — so the refusal costs nothing
and no turn can be recorded as a persona's reaction without conditioning.

## Reading it

**Conditioning is the entire source of variance, and almost none of the mean.** Standard
deviation goes from 0.153 to exactly zero; distinct answers from 57 to one. But the two arms'
mean top-two-box differ by **0.0023** — indistinguishable.

That is a sharper claim than the PRD's, and it cuts differently:

- **"Narrow" is confirmed**, in the strongest form available. Not merely narrower: collapsed. An
  unconditioned population is one respondent answered 150 times, and every quantity that depends
  on personas differing — audience divergence, polarization, segmentation, any heterogeneity a
  study exists to find — is identically zero by construction.
- **"Optimistic" is not supported on this model.** The means are within 0.002 on top-two-box. On
  expected rating the unconditioned arm sits 0.138 higher, which is the direction the literature
  reports but a small fraction of what "optimistic" implies.

The practical consequence is worth stating plainly, because it changes how a report should be
read: **a study's headline adoption figure would be nearly unchanged without any conditioning at
all.** The first measured study's adoption of 0.5684 is not, by itself, evidence that conditioning
did anything. What conditioning buys is the ability to tell personas apart — and that is not
visible in the headline number, only in the spread beneath it.

## What this does not show

The literature also reports rank correlation falling to roughly half under an unconditioned
prompt. That cannot be computed here: rank correlation needs human data to correlate *against*,
and there is none. This is the calibration gap, and it is why trust stays `UNCALIBRATED` however
this evaluation came out. Spread is not validity: a conditioned population that varies could vary
in entirely the wrong way, and nothing here would know.

## What the evaluation exposed

Getting a sound comparison took two defects and one regression of my own, all found by running it:

**An intent turn offered an action that made it unrecordable.** The elicitation question asks the
persona to answer in the verbatim; `Reaction` refuses an ignored impression that carries one.
Offering `ignore` invited the model to do both, and 81 of 150 conditioned personas did — every one
lost. The bias ran the worst way: only conditioned personas ever produce an "I would skip this"
reaction, so the arm under test silently dropped its least-engaged half and averaged the
enthusiasts. Reported from that run, the conditioned optimism figure would have been inflated by
selection with nothing to reveal it.

**A one-item list is not a choice.** Removing `ignore` left `'action' (one of answer)`, which a
model reads as a field to fill in: it answered `"consider"` and `"not likely to purchase"`, and
both arms went to zero. Where there is no choice the value is stated — `'action' (always
"answer")`.

What caught the first of these was the run failing *identically* at 30 requests per minute with
five retries. Throttling would have moved the numbers; determinism turned what looked like flaky
infrastructure into a reproducible defect.

## Caveats

- One model (`amazon.nova-micro-v1:0`) and one category. A larger model may separate the arms'
  means where this one does not.
- 150 personas of one 500-persona population, one tick, one stimulus.
- The unconditioned block is one sentence. A different non-informative block might collapse to a
  different single answer; it is the collapse, not the sentence, that is the finding.
- Trust remains `UNCALIBRATED`. Nothing here is evidence that the conditioned distribution is
  *correct*, only that it is not degenerate.
