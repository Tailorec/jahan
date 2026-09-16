# PRD — M5 `elicitation`: what a persona said, as a rating distribution

## Problem Statement

A study's headline number is adoption: the share of personas answering 4 or 5 on a five-point purchase-intent
scale. Nothing in the engine can yet produce that scale. Asking a model for a number fails in a known way —
answers collapse onto safe middle ratings, so every simulated population looks lukewarm and alike — so the
architecture chose Semantic Similarity Rating: the persona answers in its own words, and the words become a
distribution by embedding similarity to anchor statements for each point.

The grill found the method as specified was not the method that was validated. The architecture computed
`softmax(cosine / τ)` inside each anchor set and said no implementation existed; the authors' published code
subtracts the least similar anchor's similarity and normalises, averages across sets, and applies temperature
once, after. The paper's anchor statements were never published, and were tuned on the same 57 surveys used to
evaluate them. The human surveys themselves are private, so the architecture's gate "against published human
data" has nothing to run against. And neither of Bedrock's OpenAI-compatible endpoints serves embeddings, while
OpenAI's embedding model the paper used is not offered on AWS.

One defect predates the module: the inference client from M4 does not satisfy `EmbedPort`. The port promises an
array and a `model_id`; the client returns an `EmbeddingResult` and has no `model_id`. A population built with
embeddings through a real client would fail, and every test passes only because it uses `FakeEmbed`.

The risk this module addresses is a confident, unvalidated number. A wrong formula, anchors tuned to their own
test, a model-written "4/5" scored as if it were prose, or an embedding model changed between anchors and
responses would each produce a plausible adoption figure with nothing to show it was wrong.

## Solution

One module, batch-first like inference, computing exactly what the paper validated and claiming no more than can
be checked.

`score(responses, construct) -> outcomes` returns one outcome per response in request order — an `SsrResult` or a
recorded elicitation failure. The computation is ported from the authors' `compute.py` with attribution (ADR 0026).
Anchors are the engine's own, hand-written to the paper's description, frozen and pinned by hash before they are
validated, and never tuned on the data that judges them (ADR 0027). A check needing no human data must pass before
an anchor version can be pinned. The mapping claim — SSR recovers the rating a person gave from what they wrote —
is validated on a few hundred human product reviews; the simulation claim is recorded as owed (ADR 0028).
Embeddings come from Titan Text Embeddings v2 through a local LiteLLM proxy, and whether SSR survives that
substitution is part of what the validation measures.

## User Stories

**The computation**

1. As a methodologist, I want the engine to compute the published SSR formula exactly, so the paper's evidence can
   be cited at all.
2. As a maintainer, I want the port checked against the reference implementation's known answers, so a
   transcription error cannot pass as the method.
3. As a researcher, I want ε and temperature to be recorded study parameters defaulting to the paper's values, so a
   change is visible wherever the result travels.
4. As an analyst, I want each response's raw per-set similarities recorded, so changing ε or temperature later is
   arithmetic on the trace, not a re-embedding.
5. As an analyst, I want the headline distribution computed from the per-set distributions, so it can never
   disagree with them.

**Anchors**

6. As a methodologist, I want anchor statements hand-written to the paper's description, in six sets of varied
   wording, so no single phrasing decides a result.
7. As a methodologist, I want an anchor version frozen and identified by content hash before anything validates it,
   so no reported agreement is a fit to its own test.
8. As a maintainer, I want a changed statement to be a new version rather than an edit, so a pinned run can never
   silently score against different anchors.
9. As a researcher, I want an anchor version refused for pinning until a ladder of graded responses scores in
   order, rank order is stable across sets, and varied responses do not collapse, so broken anchors fail before a
   study relies on them.
10. As a researcher, I want one domain-independent purchase-intent family shared by categories, with a category
    able to name its own later, so anchors are written and checked once.

**What gets scored**

11. As a methodologist, I want the elicitation question owned by this module, versioned and hashed, so its wording
    is part of the method rather than a detail of prompt assembly.
12. As a methodologist, I want a response carrying a rating-like number recorded as an elicitation failure, so no
    model-emitted rating is ever scored as prose.
13. As an analyst, I want responses scored in batches with results in request order, so a tick's thousands of
    reactions are one operation and never reordered.
14. As an operator, I want an embedding failure to cost only the chunk it happened in, recorded as failures, so one
    bad call does not lose a tick.
15. As a methodologist, I want anchors and responses embedded by the same pinned model with no fallback, and a
    mismatch refused, so every similarity compares like with like.
16. As an operator, I want anchor embeddings computed once per run and cached by anchor hash and model, so scoring
    thousands of responses does not re-embed the anchors each time.

**Validation**

17. As a researcher, I want SSR scored on a few hundred public human reviews balanced across stars — log loss, Brier
    score and rank correlation against a baseline that ignores the text — so the mapping claim is measured on real
    human ground truth.
18. As a researcher, I want that validation to use a satisfaction anchor set frozen before it runs, so it validates
    the mechanism without pretending to validate purchase-intent anchors.
19. As a researcher, I want the validation run through the real embedding model from one command, with its result
    written as a report, so the Titan substitution is measured rather than assumed.
20. As a reader of results, I want the simulation claim recorded as owed and the trust level left uncalibrated, so
    no study reads a mapping result as proof that simulated purchase intent matches people's.

**The embedding port**

21. As a maintainer, I want the inference client to satisfy the embedding port, so a real client can be passed
    wherever the fake is.

## Implementation Decisions

**The embedding port.** `EmbedPort` returns what the client already produces: the vectors in input order, the
pinned and served model, and the cost of every batch. `FakeEmbed` and population's embedding step move to that
shape, and a test passes the real client, over a scripted transport, wherever the fake is accepted. This lands
first, because elicitation is built on it.

**The computation.** A port of the reference `compute.py`, with attribution: similarity `(1 + cosine) / 2`;
per-set `p_i = (γ_i − γ_min + ε·[i is the least similar]) / (Σγ − 5·γ_min + ε)`; mean across sets; then `p^(1/T)`
renormalised, one-hot at the maximum when T = 0. The reference implementation's tests become known-answer tests.
No dependency on the package or on `sentence-transformers`.

**Anchors.** Immutable JSON under `anchors/<construct>/<version>.json`: the construct, the version, six sets of five
statements, and nothing else. The content hash is the identity `RunConfig.anchor_set_hashes` pins. Purchase intent
and satisfaction are written now. Anchor embeddings are computed once per run and cached by anchor hash and
embedding model.

**The anchor check.** A command that runs a frozen ladder of graded responses (strictly increasing expected score),
Spearman rank stability across the six sets (above 0.8), and non-collapse (varied responses give distributions that
differ), against the real embedding model, and writes its result beside the anchor version. A version without a
passing result cannot be pinned. The ladder is itself frozen, and a version is never revised to make the check pass
on the same ladder.

**The question and numbers.** A versioned, hashed question template per construct, based on the paper's *"How
likely are you to purchase the product?"* with an instruction to answer briefly in the persona's own words without
numbers or ratings. `agent` includes it verbatim. A response matching a rating pattern — a digit on a one-to-five or
one-to-ten scale, a fraction, a percentage, a star count — is an elicitation failure with no distribution.

**The contract.** `SsrResult` renames `tau` to `temperature`, gains `epsilon` and `per_set_similarities`, and
computes `pmf` as temperature applied to the mean of `per_set_pmfs`. An elicitation failure names its kind — numeric
answer, embedding failure, empty response — and never carries a distribution. `RunConfig` gains per-construct
elicitation parameters (temperature, ε), hashed. `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities
are re-pinned.

**Batching.** `score(responses, construct)` embeds responses in capped chunks through the port; a chunk whose
embedding call fails records its responses as embedding failures, and the rest proceed. Results return in request
order.

**The mapping validation.** A command that draws about 500 human product reviews balanced across star ratings from
a public reviews dataset, downloaded at run time and never committed; embeds them through the pinned model; scores
SSR's distributions against the stars with log loss, Brier score and Spearman correlation of the expected rating;
and reports them beside a baseline that ignores the text. It writes a report naming the anchor version and hash, the
embedding model served, ε, temperature, the sample and its seed. The dataset's location and terms are confirmed when
the command is built.

**The embedding route.** Titan Text Embeddings v2 through a local LiteLLM proxy that also serves the chat models, one
base URL for both. The gateway documentation gains the Titan embedding entry.

## Testing Decisions

Boundary tests through `score`, the anchor check and the validation command. The formula is tested against the
reference implementation's own cases and against hand-computed examples, including ε = 0 zeroing the least similar
anchor within a set and T = 0 producing a one-hot. The anchor check is tested against anchors deliberately broken in
known ways — reversed, duplicated, all synonyms of one point — each of which must fail. Numeric detection is tested
on a table of rating-like and innocent strings. Order, chunk failure isolation and the model-mismatch refusal use
`FakeEmbed` with injected failures; the port's agreement with the real client uses a scripted HTTP transport. The
suite never reaches a network; the real-model anchor check and validation run when a user configures an endpoint.

The tests carrying the most weight are the ones this module exists for: the port reproduces the reference
implementation exactly; broken anchors fail the check; a "4/5" answer is never scored; re-scoring recorded
similarities under a new ε or temperature reproduces a fresh scoring exactly; and the real client satisfies the
embedding port.

## Out of Scope

The simulation claim's human benchmark — a purchase-intent study with real respondents — which ADR 0028 records as
owed. Constructs beyond purchase intent. Experiments with the question's wording. Tuning ε or temperature. Assembling
a persona's turn, which belongs to `agent`. Category-specific anchor families.

## Further Notes

`FINAL_ARCH.md` §5.5, `SALVAGE.md` and `CONTEXT.md` are reconciled with ADR 0026–0028 ahead of this PRD. The
`EmbedPort` mismatch was found while writing it and belongs to M4; it is fixed here because elicitation is its first
real consumer.
