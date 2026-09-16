# Evaluation: elicitation against the real embedding model

*2026-09-17 · M5 Phase 9 · anchor check on Titan Text Embeddings v2 · both families FAILED, neither pinned · Bedrock spend < $0.01*

## Setup

| | |
|---|---|
| Embedding model | Amazon Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`), 1024 dims, `eu-north-1` |
| Route | Local LiteLLM proxy on `127.0.0.1:4000`, one base URL, retries/fallbacks/cache off (`/tmp/litellm_config.yaml`); engine pin `embed` serving `embed` |
| Vectors verified | Proxy vectors byte-identical to direct `bedrock-runtime` invocation on probes |
| Anchor versions | `purchase_intent/v1` (`7b253b23…09d516e`), `satisfaction/v1` (`85b73867…e5efe5eec69ce`) |
| Check parameters | ε = 0, temperature = 1 (the paper's defaults — the gate judges the version, not a tuning) |

## Outcome

Neither family passes the gate it must pass before pinning (ADR 0027). Both check records sit beside
their versions under `anchors/`; `assert_pinnable` refuses both.

**Purchase intent** — ladder strictly increasing ✓ (1.93 → 4.05), no collapse ✓ (0.73),
rank stability **0.500** ✗ (needs > 0.8). One set breaks ranks: set 4's top rung. Titan places the
ladder's top rung *"I would definitely buy this, certainly."* nearest to position 4,
*"I am inclined to try it."* (γ = 0.5959), ahead of position 5, *"I am eager to try it and will."*
(γ = 0.5870). All five similarities sit in a 0.09 band — Titan compresses near-paraphrases tightly,
so small wording differences decide the peak, and set 4 scores the top rung at 3.37, below rung 5's 3.95.

**Satisfaction** — rank stability **0.714** ✗, ladder not increasing ✗
(2.00, 2.26, 3.41, 3.59, **3.37**, 4.15, **3.89**). Rung 5 (*"somewhat satisfied"*) falls below rung 4
(*"acceptable … on the whole"*), and rung 7 (*"completely satisfied"*) below rung 6 (*"very pleased"*).
Same pattern as purchase intent: the top end of the scale does not order under Titan.

## Reading

This is the failure mode ADR 0027 warned about: the paper's reported agreement was tuned to its own
anchors on its own embedding model, and hand-written anchors to the paper's description do not transfer
to Titan v2 with rank stability. The headline means still increase, so a study scored on these anchors
would look plausible — which is exactly why the gate exists and why both versions stay unpinned. No
anchor, ε or temperature was adjusted on the basis of these numbers; a revision would be a new version,
and one fitted to this ladder would be a fit to its own test.

## What was not run, and why

The mapping validation was not run on real reviews. It requires a pinned satisfaction version with a
passing check (plan Phase 8), and none exists — scoring reviews against anchors the gate refused would
break the chain the design was built to enforce. No review dataset was downloaded and none is committed.
The command (`python -m simcore.elicitation --reviews reviews.jsonl --seed 7 --out mapping.json`) and the
runbook below stand ready for a future passing version.

## Engine defect the real run exposed

The first satisfaction run failed trivially ([2.75, 2.60, …]) because the check graded buy-intent prose
on satisfaction anchors: one ladder for every construct is a broken instrument. The check now carries a
frozen ladder and varied set per construct (`ladder_for` / `varied_for`, unknown constructs refused).
Fixed with tests that fail on the pre-fix code (`ladder_for` did not exist there), and the satisfaction
numbers above are from the corrected, frozen satisfaction ladder — a single run, no iteration.

## Runbook (re-run or next candidate)

```bash
export SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1
# 1. Anchor checks against the model the versions will be used with:
uv run python -c "
from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import ModelPins
from simcore.elicitation import check_anchors, assert_pinnable
pins = ModelPins.model_validate({'tier_a': 'tier-a/model', 'tier_b': 'tier-b/model',
    'embed': {'model_id': 'embed', 'serves': ['embed']}})
client = InferenceClient(pins, ExecutionSettings())
for construct, set_id in (('purchase_intent', 'purchase-intent-v1'), ('satisfaction', 'satisfaction-v1')):
    result = check_anchors(set_id, construct, 'v1', client)
    print(construct, result.passed, result.detail)
"
# 2. Only a passing version pins; only a pinned satisfaction version validates:
#    assert_pinnable(set_id, construct, 'v1', embed_model_id='embed')
#    uv run python -m simcore.elicitation --reviews /tmp/reviews.jsonl --seed 7 --out mapping.json
```

Per ADR 0028 the next embedding candidate, if these anchors are ever re-tested, is Cohere Embed v4.

## Caveats, stated plainly

- The mapping claim is unmeasured on any model: whether SSR recovers human ratings with these anchors
  is unknown, not assumed.
- A passing mapping validation would still not establish the simulation claim. Reviews measure
  satisfaction with products people bought; the study needs purchase intent for products that do not
  exist yet, from simulated personas. That check needs a purchase-intent benchmark with real
  respondents and is recorded as owed (ADR 0028).
- The trust level stays `UNCALIBRATED` (ADR 0008). Nothing in this module produces the evidence a
  higher level requires.

## Dataset

No review dataset was downloaded and none is committed (ADR 0016). The validation command accepts any
star-balanced JSONL file at run time and records its location in the report; the exact location and
terms are to be confirmed and recorded in the mapping report when that run happens.
