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
| Purchase intent | Not asked and not scored: no anchor version passes its check (ADR 0029), and this run's scenario elicits reactions |

`run_study.py` beside this file is the script; it writes the report the numbers below come from.

## What a fake had been hiding

Nine defects, in an engine with more than 1,500 passing tests. Each was invisible to every
boundary test and most were obvious within one real call.

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

**4. No belief moved in 400 turns.** The parser reads `belief_deltas`; the question never asked
for them. With beliefs frozen, reflection could only fire on its cadence, **word of mouth never
fired at all** — its gate is how strongly a reaction was felt — and a belief-shift finding had
nothing to find. The engine's whole social mechanism was inert while every test passed, because
the test fakes returned deltas nobody had requested.

**5. Every probe came back `(no answer)`**, the probe parser having kept the bare `json.loads`
the turn parser had just lost.

**6. The partition refused the world's honest view.** A feed affords likes and reshares, never
votes, so an upvote there changes no state and appears in no view — but the partition counted
every action as engagement whatever channel it happened on, and then refused the record:
*shows 0 upvotes, but 14 were visible*. Nobody had seen it because no persona had ever voted
until beliefs started moving.

**7. A view could not record who told you.** Word of mouth carries the tie to the teller, not the
author, so a peer passing on the study's own concept — which has no author — produced a view the
contract rejected. Found the first time word of mouth fired.

**8. A study could not ask for purchase intent.** The runner named the task itself, so every turn
was a reaction and adoption was unreachable from any configuration, even with anchors that pass.
What personas are asked is now one of the conditions a scenario describes.

**9. A resume refused without naming what moved.** The check covered the brief, ontology,
population, scenario, pins and engine version, but not the templates, anchor sets, budget or
seeds the configuration hash also covers — so a changed anchor pin failed deep inside the
registry with a hash-to-hash message naming nothing.

**Each fix exposed the next.** Fixing the prompt let personas answer; answering let beliefs move;
moving beliefs made personas vote and made word of mouth fire for the first time; voting hit the
affordance mismatch; word of mouth hit the teller rule. A fake supplies whatever the test author
imagined, so that chain never starts.

## What the platform taught us

**Titan Text Embeddings v2 allows 60 requests per minute on this account**, and the engine's rate
limiter counts *its own HTTP requests* — but the gateway fans one batched embedding call into one
provider call per text. A batch of 64 therefore looks like one request to the limiter and like 64
to Bedrock, and the quota is blown while the engine believes it is well inside it. Running with
one text per request and 50 requests per minute holds. The limiter counting texts rather than
requests is recorded as a follow-up; until then, a study against a quota this tight sets
`JAHAN_INFERENCE_EMBEDDINGS_BATCH_SIZE=1`.

**A cached answer is not a run.** An early attempt reported a complete study in 0.2 seconds: the
engine's own response cache, populated by earlier attempts, served every turn. The report now
counts cost records by route, so a reader can tell a study that happened from one that was
replayed.

## Results

200 personas drawn from Stack Overflow rows, three ticks on the social feed, every module real.
`reports/study-200-personas-3-ticks.json` is the report; `reports/before-the-fixes-200-personas.json`
is the same study before the fixes, kept because the difference is the point.

| | Before the fixes | After |
|---|---|---|
| Turns | 400 | 495 |
| Turns that moved a belief | **0** | **495** (mean move 0.32) |
| Reflections | 0 | 207 consolidated memories |
| Word-of-mouth deliveries | **0** | **113**, reaching 96 turns on the wom channel |
| Probe answers read | **0** | 18, all agreeing with the persona's own attributes |
| Guardrail violations | 60 of 60 (all false) | 6 of 495 (1.2%) |
| Record validates as a partition | refused twice | **4,052 of 4,052 events** |

**What the engine did.** 116 stimuli published — the concept, two claim posts, and 113 peer
replies personas wrote and other personas then saw. 495 turns across two channels (399 on the
feed, 96 by word of mouth). Actions spread across commenting, complaining, upvoting, asking a
peer and rejecting, rather than one action repeated. Verbatims group under the claims they are
about: 149 on C1, 11 on C2. Six turns invented something and were caught — five naming a
stimulus never shown, one unparseable after its retry.

**What it cost.** $0.085 metered; the registry recorded $0.0848 from the trace's own cost events,
which is the cross-check that the ledger sums what was actually billed. 812 chat calls and 1,204
embedding calls, 2,015 cost records, no failures. Four minutes to build the population, 30
minutes to run the study under Titan's 60-per-minute quota.

**A persona, in its own words:**

> "As a developer, I'm skeptical of AI in code reviews — especially when it requires new tooling.
> But if it *actually* catches bugs reviewers miss without adding noise, I'd try it."

> "This is just another attempt to automate away human judgment in code reviews."

The audience the brief asked for is AI skeptics among developers, and that is who answered.

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
