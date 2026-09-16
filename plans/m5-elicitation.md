# Plan: M5 `elicitation` — what a persona said, as a rating distribution

> Source PRD: `docs/prd/M5-elicitation.md`
> Binding decisions: ADR 0026 (the paper's SSR formula), ADR 0027 (anchors frozen before validation, checked before pinning), ADR 0028 (the mapping claim validated, the simulation claim owed, Titan v2 through LiteLLM), ADR 0023 (batches answered in request order, failures as outcomes), ADR 0012 (the embedding role never falls back), ADR 0021 (one OpenAI-compatible endpoint), ADR 0008 (trust stays uncalibrated without a human benchmark), ADR 0016 (no dataset rows committed). `CONTEXT.md` (Construct, Anchor Set, Mapping Claim, Simulation Claim, Adoption). Where `FINAL_ARCH.md` §5.5 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **Batch first** — `score(responses, construct) -> outcomes`: one outcome per response in request order, an `SsrResult` or a recorded elicitation failure, never an exception for one response and never a silent gap.
- **The paper's computation, exactly** — similarity `(1 + cosine) / 2`; per anchor set, subtract the least similar anchor's similarity and normalise with ε; mean across sets; then temperature once. Ported from the authors' `compute.py` with attribution; no dependency on their package or on `sentence-transformers`.
- **Anchors are frozen versions** — immutable JSON under `anchors/<construct>/<version>.json`, identified by content hash, pinned by `RunConfig.anchor_set_hashes`. A changed statement is a new version. No anchor, ε or temperature is tuned on data that evaluates it.
- **A version must pass its check before it can be pinned** — a frozen ladder, rank stability across sets and non-collapse, against the real embedding model.
- **One embedding model, pinned, no fallback** — anchors and responses are embedded by the same model and a mismatch is refused. The route is Titan Text Embeddings v2 through a local LiteLLM proxy that also serves chat, one base URL.
- **No rating is ever scored** — a response carrying a rating-like number is a failure, not a distribution.
- **Two claims, kept apart** — the mapping claim is validated on human reviews; the simulation claim is owed, and the trust level stays uncalibrated.
- **Study parameters are recorded** — ε and temperature per construct live on `RunConfig`, hashed, defaulting to the paper's 0 and 1.
- **Contract amendments come first** — `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities are re-pinned rather than migrated.
- **Test posture** — boundary tests through `score`, the anchor check and the validation command; `FakeEmbed` for behaviour, a scripted HTTP transport where the real client must agree. The suite never reaches a network.

---

## Phase 1: The embedding port the real client satisfies

**User stories**: 21

### What to build

The seam every later phase embeds through, made true. The port promises what a real embedding call produces: the vectors in input order, the model that was pinned and the one that served, and what each batch cost. The deterministic fake and population's embedding step move to that shape, and the real inference client is shown to be accepted wherever the fake is.

### Acceptance criteria

- [x] The embedding port returns vectors in input order together with the pinned model, the served model and the cost records
- [x] The fake satisfies the port and stays deterministic across processes
- [x] The real inference client satisfies the port, asserted over a scripted transport
- [x] Population's embedding step accepts the real client and builds the same array shape it builds from the fake
- [x] Existing population tests pass unchanged in behaviour

---

## Phase 2: Contracts — the elicitation record, its failures and its parameters

**User stories**: 3, 4, 5

### What to build

The shapes the module records into. The elicitation record carries temperature and ε in place of τ, the raw similarity vector of every anchor set, and a headline distribution computed as temperature applied to the mean of the per-set distributions, so it can never disagree with them. A failed elicitation gains its own outcome naming what went wrong and carrying no distribution. Temperature and ε become per-construct study parameters on the run configuration.

### Acceptance criteria

- [x] The record carries temperature, ε, and one similarity vector of five per anchor set beside each set's distribution
- [x] The headline distribution is computed from the per-set distributions under the recorded temperature, and a contradicting stated value is refused
- [x] At least six anchor sets are still required
- [x] An elicitation failure names its kind — numeric answer, embedding failure, empty response — and cannot carry a distribution
- [x] Temperature and ε are per-construct run parameters, defaulting to 1 and 0, included in the run's hash
- [x] Pinned identities are re-pinned, with the change recorded in the commit that moves them

---

## Phase 3: The computation

**User stories**: 1, 2

### What to build

The paper's formula as pure arithmetic from similarities to distributions, proven before anything is layered on it. Similarity from cosine; per set, subtraction of the least similar anchor and normalisation with ε; the mean across sets; temperature applied once afterwards, with zero temperature giving a one-hot at the most likely point. It is checked against the reference implementation's own test cases and against hand-worked examples.

### Acceptance criteria

- [x] Similarity is `(1 + cosine) / 2` over normalised vectors
- [x] Per set, the least similar anchor receives exactly zero when ε is zero, and each set's distribution sums to one
- [x] ε adds to the least similar anchor and to the denominator exactly as the reference does
- [x] Temperature is applied once, after the mean across sets; zero temperature gives a one-hot, and a uniform distribution passes through unchanged
- [x] The port reproduces the reference implementation's known answers
- [x] The source carries the reference implementation's attribution and licence notice

---

## Phase 4: Anchors as frozen versions

**User stories**: 6, 7, 8, 10

### What to build

The anchor statements and the rules that keep them honest. An anchor version is a file naming its construct and version with six sets of five statements; its content hash is its identity; a run pins it by that hash; and an edited file is refused as the version it claims to be. The purchase-intent family and the satisfaction family used for validation are written now, to the paper's description — short, generic, domain-independent, with varied wording across sets.

### Acceptance criteria

- [x] An anchor version declares its construct and version and holds six sets of five statements, and anything else is refused
- [x] A version's identity is its content hash, and a run scoring against an unpinned or altered version is refused
- [x] Purchase-intent and satisfaction anchor versions exist, each with six sets whose wording is not a paraphrase of one set
- [x] Categories share the purchase-intent family by name, and an ontology can still name another version
- [x] No anchor file is modified after its version is first pinned, asserted against its recorded hash

---

## Phase 5: Scoring batches

**User stories**: 13, 14, 15, 16

### What to build

The module's interface end to end: responses in, outcomes out, in request order. Responses are embedded in capped chunks through the port; a chunk whose embedding fails records its responses as embedding failures while the rest are scored. Anchor embeddings are computed once per run and reused. Anchors and responses must come from the same pinned model, and a mismatch is refused.

### Acceptance criteria

- [x] A batch returns one outcome per response in request order
- [x] A failed embedding chunk records only its own responses as embedding failures, and every other response is scored
- [x] Anchor embeddings are computed once per run for an anchor version and model, and reused across batches
- [x] Anchors and responses embedded by different models are refused
- [x] An empty response is a failure, not a distribution
- [x] A scored response records its per-set similarities, and re-scoring them under a new ε or temperature reproduces a fresh scoring exactly

---

## Phase 6: The question and numeric answers

**User stories**: 11, 12

### What to build

What the persona is asked, and what happens when it answers with a number anyway. The question is a versioned, hashed template per construct, based on the paper's wording with an instruction to answer briefly in the persona's own words and without numbers or ratings. A response carrying a rating — a digit on a small scale, a fraction, a percentage, a star count — is an elicitation failure, never scored.

### Acceptance criteria

- [x] Each construct has a versioned question template identified by its content hash
- [x] The purchase-intent template is based on the paper's question and forbids numbers and ratings
- [x] Responses containing ratings such as "4/5", "8 out of 10", "90%" or "★★★★" are numeric-answer failures
- [x] Responses that merely mention numbers in passing — a price, a pack size, a year — are scored
- [x] No code path accepts a model-stated rating, asserted by a test over the module

---

## Phase 7: The anchor check

**User stories**: 9

### What to build

The gate an anchor version must pass before it can be pinned, needing no human data. A frozen ladder of graded responses must score in strictly increasing expected rating; rank order must be stable across the six sets; varied responses must produce distributions that differ. The check runs against the embedding model the version will be used with and records its result beside the version, and pinning refuses a version without a passing result.

### Acceptance criteria

- [x] A frozen ladder of graded responses must yield strictly increasing expected ratings
- [x] Rank order of the ladder is stable across anchor sets, with Spearman correlation above 0.8
- [x] Varied responses must not collapse to one distribution
- [x] Deliberately broken anchors — reversed, duplicated, all one point in different words — each fail the check
- [x] The result records the anchor version, its hash and the embedding model, and a version without a passing result cannot be pinned
- [x] The ladder is frozen, and nothing in the check can adjust an anchor

---

## Phase 8: The mapping validation

**User stories**: 17, 18, 19

### What to build

The measurement of the mapping claim. A command draws a few hundred public human product reviews balanced across star ratings, embeds them through the pinned model, scores SSR's distributions against the stars people gave — log loss, Brier score and rank correlation of the expected rating — and reports them beside a baseline that ignores the text. It uses the frozen satisfaction anchors, downloads the reviews at run time and commits none. The gateway guide gains the Titan embedding entry.

### Acceptance criteria

- [x] About 500 reviews are drawn balanced across the five star ratings, from a seed, and none is written into the repository
- [x] SSR's log loss, Brier score and expected-rating rank correlation are reported beside a text-blind baseline's
- [ ] The satisfaction anchors used are a pinned version with a passing anchor check
- [x] The report records the anchor version and hash, the served embedding model, ε, temperature, the sample size and seed
- [x] A fake that embeds identical text identically scores reviews against the anchors deterministically in CI
- [x] The gateway guide documents serving Titan Text Embeddings v2 through LiteLLM beside the chat models
- [ ] The dataset's location and terms are confirmed and recorded

---

## Phase 9: Real-model run and reconciliation

**User stories**: 19, 20

### What to build

The module proven on a real embedding model, and the documents in step. The anchor check runs on both anchor families and the mapping validation runs on reviews, through Titan behind LiteLLM, and the results are written up as an evaluation with their caveats. Whatever the result, the simulation claim stays recorded as owed and the trust level uncalibrated. Architecture, salvage and glossary are checked against what was built.

### Acceptance criteria

- [x] The anchor check passes on the purchase-intent and satisfaction versions against Titan Text Embeddings v2, or its failure is recorded and the version is not pinned
- [ ] The mapping validation runs on real reviews through the real embedding model, and its report is committed as an evaluation with its caveats
- [ ] Any engine defect the real run exposes is fixed with a test that fails on the old code
- [x] The evaluation states plainly that the mapping claim does not establish the simulation claim, and the trust level stays uncalibrated
- [x] `FINAL_ARCH.md` §5.5, `SALVAGE.md` and `CONTEXT.md` describe what was built, and no claim contradicts the code
