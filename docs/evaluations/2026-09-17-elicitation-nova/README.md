# Evaluation: the anchor check on a second embedding model

*2026-09-17 · M5 Phase 9 · anchor check on Amazon Nova 2 multimodal embeddings · both families FAILED again, neither pinned · Bedrock spend < $0.01*

## Why this run

Both v1 anchor families failed the gate on Titan Text Embeddings v2
([Titan evaluation](../2026-09-17-elicitation-titan/README.md)). That left one question open: is the
failure Titan's or the anchors'? ADR 0027 allows re-checking an unchanged frozen version against another
model, so the same versions and the same frozen ladders were checked on a second, newer model. Nothing
was edited between the runs.

## Setup

| | |
|---|---|
| Embedding model | Amazon Nova 2 multimodal embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`), 3072 dims, `us-east-1` |
| Route | Local LiteLLM 1.101.0 proxy on `127.0.0.1:4000`; retries/fallbacks/cache off; LiteLLM sends `SINGLE_EMBEDDING`, `embeddingPurpose: GENERIC_INDEX`, 3072 dims for anchors and responses alike |
| Pin | `amazon.nova-2-multimodal-embeddings-v1:0` serving `amazon.nova-2-multimodal-embeddings-v1:0` (provider id, not an alias) |
| Pacing | Account quota is 20 requests/minute and LiteLLM sends one request per text: batch size 1, concurrency 1, engine limit 18 RPM |
| Anchor versions | `purchase_intent/v1` (`7b253b23…09d516e`), `satisfaction/v1` (`85b73867…e5efe5eec69ce`) — unchanged |
| Check parameters | ε = 0, temperature = 1 |

**Why not Cohere Embed v4**, the candidate ADR 0028 named: Cohere models on Bedrock are sold through AWS
Marketplace, and this account's subscription fails with `INVALID_PAYMENT_INSTRUMENT` (the agreement stays
`PENDING`). One probe call succeeded while the subscription was still being processed; later calls were
refused. Nova is Amazon's own model and needs no Marketplace subscription.

## Outcome

`check_results.json` holds both results; the records under `anchors/` now carry them, naming the provider
model, so `assert_pinnable` refuses both versions with a record it can read (the Titan records named the
alias `embed`, which the gate no longer accepts).

| Family | Ladder expected ratings (rungs 1→7) | Increasing | Rank stability | Collapse distance | Result |
|---|---|---|---|---|---|
| purchase intent | 1.96, 2.02, 3.28, 3.71, 3.78, 3.93, 3.95 | ✓ | **0.500** ✗ | 0.70 ✓ | FAIL |
| satisfaction | 1.91, 2.28, 2.93, 3.45, 3.50, **4.11, 3.87** | ✗ | **0.714** ✗ | 0.74 ✓ | FAIL |

Titan gave 1.93 → 4.05 and 0.500 for purchase intent, and 0.714 with rungs 6/7 inverted for satisfaction.
Two models from different generations, with different dimensions, fail in the same places.

## The engine was checked, not assumed

The two runs agreed so closely that an engine bug was the first hypothesis. `independent_recompute.py`
fetches raw vectors from the proxy without the engine and recomputes the paper's formula in numpy. It
reproduces the headline ratings to three decimals and the same minimum pairwise Spearman (0.500 at sets
1 and 4; 0.714 at sets 2 and 3). The numbers are Nova's, not an artefact of the engine.

## Where it breaks: per anchor set

Expected rating of each ladder rung under each set alone, and that set's Spearman against ladder order:

**Purchase intent**

| Set | Rungs 1→7 | ρ vs ladder |
|---|---|---|
| 0 | 2.16 2.25 3.28 3.65 3.72 3.91 4.17 | 1.000 |
| 1 | 2.10 2.08 3.36 3.64 3.70 3.88 4.49 | 0.964 |
| 2 | 1.78 1.71 3.03 3.58 3.83 4.02 3.94 | 0.929 |
| 3 | 2.17 1.85 3.05 3.71 3.86 4.18 4.23 | 0.964 |
| 4 | 2.04 2.35 3.65 3.87 3.91 **3.66 3.50** | **0.536** |
| 5 | 1.50 1.89 3.30 3.80 3.68 3.93 **3.38** | **0.750** |

Sets 4 and 5 are the ones worded without "buy": *"I am eager to try it and will."*, *"I have decided I want
this."*. The ladder's top rungs (*"I will very likely buy this."*, *"I would definitely buy this, certainly."*)
fall back toward the middle under them.

**Satisfaction**

| Set | Rungs 1→7 | ρ vs ladder |
|---|---|---|
| 0 | 2.05 2.21 3.13 3.77 3.73 4.25 3.83 | 0.929 |
| 1 | 1.94 2.57 3.16 3.66 3.66 4.27 4.26 | 0.929 |
| 2 | 1.90 2.28 3.17 3.73 3.74 4.15 3.68 | 0.786 |
| 3 | 2.26 2.03 **2.41 2.70 2.69** 3.98 4.03 | 0.929 |
| 4 | 1.54 2.59 3.23 3.50 3.44 4.11 3.69 | 0.929 |
| 5 | 1.76 1.99 2.46 3.34 3.75 3.87 3.72 | 0.893 |

Set 3 is framed by expectations (*"It met my expectations, no more."*), and it squeezes rungs 3–5 into
the middle; five of six sets put rung 7 (*"completely satisfied, it exceeded everything"*) below rung 6
(*"very pleased"*).

Every set does order its own five anchors correctly (each anchor's peak is its own point), so no set is
broken on its own terms.

## Reading

The failure belongs to the anchors and ladders, not to Titan. Two things combine:

1. **Sets that change the vocabulary.** A set phrased as trying, choosing or meeting expectations still
   orders its own statements, but it orders the ladder differently from sets phrased as buying or
   satisfaction. The paper asks for varied wording across sets; varying it this far changes what is measured.
2. **A top of the scale that embeddings cannot separate.** The upper four rungs share less than one point
   of the scale in eleven of the twelve set tables, so small wording effects reorder them. The minimum pairwise Spearman over 15 set pairs
   on seven rungs magnifies this: sets at 0.93 and 0.96 against the ladder can still disagree at 0.5
   with each other.

Neither the threshold, ε, the temperature nor any anchor was changed on the basis of these numbers.
Lowering the 0.8 threshold now would be tuning the gate to the result it just gave.

## What follows

- **v1 is finished.** Two models failed it, and it cannot be pinned.
- **The route forward is a v2 for each family, with a newly written ladder, both frozen before either is
  checked.** v2 cannot be checked on this ladder: the per-set tables above show which wordings fail it,
  so a v2 written after reading them would be fitted to its own test. The lessons that do carry over are
  about the design, not the wording: keep every set inside the construct's own vocabulary, and give the top
  of the ladder steps an embedding can tell apart.
- The mapping validation was not run on reviews: no satisfaction version is pinned. No review dataset was
  downloaded and none is committed (ADR 0016).

## Caveats, stated plainly

- Two models from one provider. They share nothing obvious, but a third provider's model was not
  reachable on this account.
- The ladder is the instrument as much as the anchors are; a ladder whose top rungs are near-synonyms
  would fail good anchors too. v2 has to face that on a new ladder, not this one.
- The mapping claim is unmeasured and the simulation claim stays owed (ADR 0028); the trust level stays
  `UNCALIBRATED` (ADR 0008).

## Reproducing

```bash
# proxy: model_name and model both amazon.nova-2-multimodal-embeddings-v1:0 (bedrock/ prefix on model), us-east-1
export JAHAN_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1
export JAHAN_INFERENCE_CONCURRENCY=1 JAHAN_INFERENCE_EMBEDDINGS_BATCH_SIZE=1 JAHAN_INFERENCE_REQUESTS_PER_MINUTE=18
uv run python -c "
from jahan.inference import ExecutionSettings, InferenceClient
from jahan.schemas import ModelPins
from jahan.elicitation import check_anchors
m = 'amazon.nova-2-multimodal-embeddings-v1:0'
client = InferenceClient(ModelPins.model_validate({'tier_a': 'tier-a/model', 'tier_b': 'tier-b/model',
    'embed': {'model_id': m, 'serves': [m]}}), ExecutionSettings.from_environment())
for set_id, construct in (('purchase-intent-v1', 'purchase_intent'), ('satisfaction-v1', 'satisfaction')):
    print(check_anchors(set_id, construct, 'v1', client, write_record=False))
"
# engine-free recomputation (caches vectors in the given directory, outside the repo):
uv run python docs/evaluations/2026-09-17-elicitation-nova/independent_recompute.py /tmp/nova-vectors
```
