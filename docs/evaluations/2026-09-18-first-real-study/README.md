# Evaluation: the first whole study on a real model

*2026-09-18 · brief → population → world → agent → trace, nothing faked · AWS Bedrock · Ministral 3 8B and Titan Text Embeddings v2*

## Why this run

Eight modules were finished and the engine had never called a model end to end. `inference` had
met a real endpoint in the holdout and `elicitation` had met one in the anchor checks, but
`population`, `world`, `agent`, `runner` and `trace` had only ever run against fakes — and
`agent` is where that mattered most, because its prompts had never been answered by anything
that could disagree with them.

The point of this run was not a finding about the product. It was to find out what a fake had
been hiding.

## What ran

| | |
|---|---|
| Brief | `examples/code_review_ai.yaml` — an AI code-review assistant, priced at $19 |
| Personas | Stack Overflow rows from the MatrAIx corpus, sampled and gated by `population`, sparse fields completed by the model |
| Chat | `mistral.ministral-3-8b-instruct` on Bedrock, $0.15 / 1M in and out |
| Embeddings | `amazon.titan-embed-text-v2:0`, $0.02 / 1M in |
| Route | Local LiteLLM proxy over AWS credentials — no API key, one base URL, retries and cache off |
| Prices | Declared on the pins from the AWS Pricing API, us-east-1 standard on-demand, 2026-09-18 |
| Purchase intent | Not scored: no anchor version passes its check (ADR 0029), so verbatims are recorded unscored (ADR 0032) |

`run_study.py` beside this file is the script; it writes the report the numbers below come from.

## What a fake had been hiding

Three defects, each invisible to every boundary test and obvious within one real call.

**1. The persona was never shown the concept.** The prompt carried the impression and the view as
serialized JSON, so a persona saw stimulus ids, an `impression_id` and a `contexts` field — and
nothing that said what the product *was*. The first real answer reacted to the plumbing:

> "The fact that you've shared my current beliefs and impressions — like the trust score of
> 0.70 — feels like a great way to build transparency … I'm curious about the 'contexts' field
> in the view — what kind of data is being stored there?"

A fake answered from the ids and never noticed. The prompt now carries what each stimulus says,
its id so a reaction can name its subject, and the public counts beside it.

**2. Every answer was refused as unparseable.** The model wrapped its JSON in a markdown fence,
which the turn parser rejected — although the engine already owns a tolerant parser that the
projection path adopted after a real run tripped over exactly this. Sixty personas, sixty
guardrail violations, and the answers were all fine.

**3. A long answer arrives as broken JSON.** The verbatim ran past the token ceiling and the
object was cut off mid-string, so a good answer became `unparseable_output` through no fault of
the model. The question now asks for one or two sentences.

A fourth came from the runner rather than the agent: a changed anchor pin slipped past the
resume refusal, which checked the brief, ontology, population, scenario, pins and engine version
but not everything else the configuration hash covers, and failed instead deep inside the
registry with a hash-to-hash message naming nothing.

## What the platform taught us

**Titan Text Embeddings v2 allows 60 requests per minute on this account**, and the engine's rate
limiter counts *its own HTTP requests* — but the gateway fans one batched embedding call into one
provider call per text. A batch of 64 therefore looks like one request to the limiter and like 64
to Bedrock, and the quota is blown while the engine believes it is well inside it. Running with
one text per request and 50 requests per minute holds. The limiter counting texts rather than
requests is recorded as a follow-up; until then, a study against a quota this tight sets
`SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE=1`.

**A cached answer is not a run.** An early attempt reported a complete study in 0.2 seconds: the
engine's own response cache, populated by earlier attempts, served every turn. The report now
counts cost records by route, so a reader can tell a study that happened from one that was
replayed.

## Results

<!-- filled from report.json -->

## Caveats, stated plainly

- **This says nothing about the product.** One small population, one cheap model, one short
  horizon. It is a test of the engine, not a concept test.
- **Purchase intent was not elicited or scored.** The turns asked for reactions; no anchor
  version passes its check, so nothing in this run produces a rating distribution, and adoption
  cannot be computed from it.
- **The trust level stays `UNCALIBRATED`** (ADR 0008). Nothing here is evidence that these
  personas answer as the people behind their rows would.
- **The conditioning effect is still owed.** This run shows conditioning reaching the model; it
  does not measure what conditioning does to the answers, which needs the two-arm evaluation
  `plans/m6-agent.md` records.
