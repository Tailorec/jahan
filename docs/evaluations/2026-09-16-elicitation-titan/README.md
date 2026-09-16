# Evaluation: elicitation against the real embedding model (attempted)

*2026-09-16 · M5 Phase 9 · anchor check + mapping validation on Titan Text Embeddings v2 · status: BLOCKED, no endpoint*

## What was attempted

The module was to be proven on the real embedding model: the anchor check on the purchase-intent
and satisfaction versions, and the mapping validation on ~500 human product reviews, through Titan
Text Embeddings v2 behind a local LiteLLM proxy, via the new `python -m simcore.elicitation` command.

The run was attempted and could not start. This environment provides no model endpoint and no
credentials: nothing answers at the LiteLLM default (`127.0.0.1:4000`), vLLM (`127.0.0.1:8000`) or
Ollama (`127.0.0.1:11434`) addresses, and no `SIMCORE_INFERENCE_BASE_URL`, `OPENAI_BASE_URL`,
`SIMCORE_INFERENCE_API_KEY` or AWS/Bedrock credentials are set. The probes and their `ConnectError`
outcomes are recorded here instead of a report with numbers in it.

## Status per gate

| Gate | Status | Consequence |
|---|---|---|
| Anchor check, `purchase_intent/v1` vs Titan v2 | NOT RUN | version is **not pinned** |
| Anchor check, `satisfaction/v1` vs Titan v2 | NOT RUN | version is **not pinned** |
| Mapping validation on real reviews via Titan v2 | NOT RUN | no mapping numbers exist |
| Mapping plumbing on the fake (CI) | PASSING | `tests/boundary/elicitation/test_validation.py`, deterministic |

Per ADR 0027 a version without a passing check result cannot be pinned, and the gate enforces it:
`assert_pinnable` refuses both families until a passing `v1.check.json` sits beside them. No check
record was written for the real anchors, and none is faked in.

## What is ready for the run

- `python -m simcore.elicitation --reviews reviews.jsonl --seed 7 --out mapping.json` draws a
  star-balanced sample from a run-time-downloaded JSONL file (`{text, stars}` per line), verifies the
  satisfaction anchors against their pinned hash, embeds through the pinned model, and reports SSR's
  log loss, Brier score and expected-rating rank correlation beside a text-blind uniform baseline.
- The anchor check entrypoint is `check_anchors("purchase-intent-v1", "purchase_intent", "v1", embed)` (and
  the same for satisfaction); it writes `anchors/<construct>/v1.check.json` and refuses to pin on failure.
- The gateway side is documented in `docs/inference.md` (Titan entry beside the chat models).

## Runbook (when access exists)

```bash
export SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1
export SIMCORE_INFERENCE_API_KEY=...   # if the proxy wants one
# 1. Anchor checks against the model the versions will be used with:
uv run python -c "
from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import ModelPins
from simcore.elicitation import check_anchors, assert_pinnable
pins = ModelPins.model_validate({'tier_a': 'tier-a/model', 'tier_b': 'tier-b/model',
    'embed': {'model_id': 'amazon.titan-embed-text-v2:0', 'serves': ['amazon.titan-embed-text-v2:0']}})
client = InferenceClient(pins, ExecutionSettings())
for construct, set_id in (('purchase_intent', 'purchase-intent-v1'), ('satisfaction', 'satisfaction-v1')):
    result = check_anchors(set_id, construct, 'v1', client)
    print(construct, result.passed, result.detail)
    assert_pinnable(set_id, construct, 'v1', embed_model_id='amazon.titan-embed-text-v2:0')
"
# 2. Mapping validation on downloaded human reviews (never committed):
uv run python -m simcore.elicitation --reviews /tmp/reviews.jsonl --seed 7 --out mapping.json
```

## Engine defects exposed by the real run

None — there was no real run. No code was changed on the basis of this attempt, so there is no
regression test owed to it. (Every defect found during the build already carries one; see the
`tests/boundary/elicitation/` suite.)

## Caveats, stated plainly

- The mapping claim is unmeasured on the real model: whether SSR recovers human ratings with Titan
  v2 and these anchors is unknown, not assumed.
- A passing mapping validation would still not establish the simulation claim. Reviews measure
  satisfaction with products people bought; the study needs purchase intent for products that do not
  exist yet, from simulated personas. That check needs a purchase-intent benchmark with real
  respondents and is recorded as owed (ADR 0028).
- The trust level stays `UNCALIBRATED` (ADR 0008). Nothing in this module produces the evidence a
  higher level requires.

## Dataset

No review dataset was downloaded and none is committed (ADR 0016). The validation command accepts any
star-balanced JSONL file at run time and records its location in the report. A suggested candidate for
the real run is a 5-star product-review corpus (e.g. Amazon Reviews); its exact location and terms are
to be confirmed and recorded in the mapping report when the run happens — not here, where asserting
them would be unverifiable.
