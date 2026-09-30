# Evaluation: channels and survey waves on real models (M15 phase 8)

*2026-10-01 · AWS Bedrock (Nova Micro, Titan Text Embeddings v2) · TwHIN-BERT served locally · 60 personas ·
five studies over one population · total spend under $0.20*

## The question

M15 lets a study tick which channels spread information — social feed, forum, word of mouth, any combination or
none — and measures purchase intent in survey waves put to every persona every *k* ticks (ADR 0048). Its tests run
on fakes. This asks whether it holds on real models:

1. Do all combinations run to the horizon and leave a record that passes the trace validator?
2. Do they share one population and differ only in world identity?
3. With no channels, is intent flat across waves — which is what "a wave only reads" predicts?
4. What does a wave cost, measured, against what New Study says it will take?

## How it was run

One brief — **NestEgg Kids**, the children's education savings app authored in Who you study
(`children_education_savings_app` ontology 1.0.1, three audiences) — and one draw: 60 personas, population seed
4021, shards 0004 and 0005, sources GSS, Stack Overflow and Amazon. Five studies over it, identical except for
`--channels`: none, `wom`, `social_feed`, `forum`, and all three. Every study: replicate seed 4021, 6 daily ticks, a
survey wave every 2 ticks (waves at ticks 0, 2, 4 and 5), `purchase_intent=v2` (checked against Titan), budget $5.

Chat `amazon.nova-micro-v1:0`, SSR embeddings `amazon.titan-embed-text-v2:0`, feed ranking `twhin-bert-base`
(`tools/twhin_server.py` behind the LiteLLM gateway), with RUN.md's Titan settings: one text per embedding call,
50 requests a minute, 4 in flight. Each study ran alone under `systemd-run … MemoryMax=6G`.

## Results

All five studies ran to the horizon, every wave was answered by all 60 personas and scored, and every record read
back through the strict trace validator. They share one population (`1e436b13…`) and have five distinct world ids —
the channels are part of the world's identity; the draws are not.

| Study | Run | World | Turns | Adoption at tick 0 → 2 → 4 → 5 |
|---|---|---|---:|---|
| none (concept test) | `run-7ggwxtdb66n0g3193j54w3ehvk` | `c27ac81bfbe9` | 240 | 0.327 → 0.327 → 0.327 → 0.327 |
| word of mouth | `run-534wjbgqys8z9sf4jp902crjbe` | `f7f53cfeaaf0` | 343 | 0.323 → 0.306 → 0.309 → 0.294 |
| social feed | `run-5rgfer3kt1md2xxj5ph1mnzghn` | `84fd4e74a7f0` | 503 | 0.327 → 0.523 → 0.474 → 0.458 |
| forum | `run-22f5zkndtr48x6hq1knen2zz9p` | `b384b688a7fd` | 445 | 0.327 → 0.476 → 0.442 → 0.435 |
| all three | `run-1mz1wd7pp4q25hb0ytgc1hp471` | `7545440b56ad` | 961 | 0.327 → 0.463 → 0.439 → 0.439 |

Adoption is share-weighted top-two-box purchase intent (ADR 0007). By audience at the last wave:

| Study | parents of young kids | early in their career |
|---|---:|---:|
| none | 0.355 | 0.290 |
| word of mouth | 0.323 | 0.256 |
| social feed | 0.434 | 0.490 |
| forum | 0.435 | 0.435 |
| all three | 0.425 | 0.457 |

**Spread.** Word of mouth alone started from its launch reach — 6 personas (10% of 60) at tick 0 — and grew to 28,
44 and 50 reached at the later waves, 97 deliveries in all. The feed reached 55 of 60 by tick 2 and everyone by
tick 4 (789 exposures, 91 of them in-network — posts by ties and follows — the rest recommended by TwHIN-BERT
interest × recency); the forum reached 40 by tick 2 and everyone by tick 4 (615 exposures, ranked by hot score).
With all three, 285 word-of-mouth deliveries reached every persona beside the platforms. Channel purchases (6 `buy`
actions with all three) were counted as behaviour, never as intent.

**Reached against unreached.** At tick 2, the personas a platform had reached stated higher intent than those it had
not: feed 0.533 against 0.396, forum 0.520 against 0.384. Under word of mouth the reached were lower at launch
(0.232 for the 6 told first-hand, against 0.338) and converged with the unreached as reach grew.

**No channels is flat.** The concept test's four waves are identical to the last digit. A wave only reads, so a
persona nothing reached sends the same prompt at every wave, and the engine's replicate-safe cache returns the same
answer at no cost. Identical prompts are the direct evidence that answering left no trace in memory or beliefs.

## What a wave costs

New Study states a wave's size before launch: 60 answers per wave, 240 for this schedule, each one chat call and one
embedding. Measured:

- A wave paid in full (the aborted first concept test's tick-0 wave): **$0.0030** for 60 personas — 119 Nova Micro
  calls including repairs and 184 Titan embeddings, about $0.00005 an answer.
- Waves whose personas had lived in a channel cost $0.0031–$0.0044 (feed, forum, all three at ticks 2–5); waves
  whose personas were unchanged were cache hits at $0.
- Channel activity over the whole horizon cost $0.0002 (word of mouth) to $0.016 (all three).

Recorded spend over every M15 run of the day, including the superseded and interrupted ones: about **$0.15**.

## What broke, and what was fixed

The measurement found four real defects. Each is fixed, tested and committed:

1. **A wave answered from the tick's opening state** (`682ae86`). The runner built every job in a tick from the state
   the tick opened with, so a persona that reacted on a channel answered that tick's wave without it. First seen in
   the numbers: the six personas told at launch answered the tick-0 wave exactly as in the concept test. The four
   channel studies were re-run on the fix; the six now answer 0.232, not 0.29.
2. **The validator refused a wave after word of mouth replied to the concept** (`47b3f63`). It required every view
   to show the replies visible to it, but a wave shows the concept alone. Survey views are now checked to be bare.
3. **A no-channel study authored belief-shift findings** (`a9c3f62`) from survey answers, which move no belief.
4. **Feed edges were reported as word-of-mouth deliveries** (`f0b5ef8`); the digest now counts word-of-mouth edges
   only, and each channel's spread in its own field.

And three operational problems, none of them the engine's to fix:

- Without RUN.md's Titan settings the first concept test was rate-limited: waves at ticks 2–5 went unscored
  (`embedding_failure`), and analysis stopped. With them there was no throttling at all.
- A background time limit stopped the gateway mid-run; the word-of-mouth run lost 13 of its tick-5 answers to failed
  chat calls (a failed call records only its cost). That run was superseded.
- A network outage (DNS could not resolve Bedrock) stopped the feed re-run mid-tick. It resumed from its last closed
  tick and completed; a run stopping on an unreachable endpoint, rather than recording a thinned wave, is intended.

## What this does not show

- **Which channel mix sells better.** One seed, 60 personas, one population: the differences above are not
  estimates of anything. Replicates and larger populations are what would make them so.
- **That repeated SSR is valid.** The paper's evidence is for a one-shot survey; every report says so.
- **The retirees.** The audience set gives *early career* and *retirees* the same filter (`region: North America`),
  so the digest — which assigns audiences by filter — puts every retiree with the early-career audience even though
  the draw placed 18 retirees. The population does not record which audience drew each persona, so analysis cannot
  tell them apart. That is a gap in Who you study's drafting and in the population contract, not in M15.
- **TwHIN-BERT exactly as OASIS ran it.** Its checkpoint has no pooler weights, so `pooler_output` passes a layer
  OASIS re-randomises on every start; here it is seeded, so runs reproduce. transformers stays below 5, which would
  silently drop the checkpoint's relative position embeddings.
