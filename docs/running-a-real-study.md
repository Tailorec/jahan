# Running a real study, step by step

Everything here was run end to end on 2026-09-20. It uses real models through your own AWS account and the
real Persona 1M corpus. Nothing in it is a fake run.

**This is a research instrument (ADR 0016).** The corpus is `matraix-research-only`; you download it and accept
its terms yourself. Trust is `UNCALIBRATED`: no result here has been checked against human behaviour, so a
number from this engine is a demonstration that the pipeline runs, not a fact about a market.

## What you need

| | How to check |
|---|---|
| `uv` and Node 20+ | `uv --version`, `node --version` |
| AWS credentials with Bedrock access to **Amazon Nova Micro** and **Titan Text Embeddings v2** in `us-east-1` | `aws sts get-caller-identity` |
| The corpus, at least the shards you will draw from, plus `manifest.json` and `persona_codes.schema.json` | `ls ~/.cache/consumersim/coreset/*/data/` |
| ~7 GB of free RAM for the population draw | `free -g` |

Fetch a missing shard with the command the engine prints when it needs one:

```bash
hf download MatrAIx2026/MatrAIx_Persona_1M_Public_Release "data/persona-1m-0004.parquet" \
  --repo-type dataset --local-dir ~/.cache/consumersim/coreset/MatrAIx2026__MatrAIx_Persona_1M_Public_Release
```

You do **not** need all ten shards. Name the ones you have with `--shards` (step 5). Shard `0009` is synthetic and
is excluded by `--sources` below.

## 1. The model gateway (terminal 1)

The engine speaks two OpenAI-compatible endpoints and imports no provider SDK (ADR 0021). If you already have an
OpenAI-compatible endpoint, skip this and point `SIMCORE_INFERENCE_BASE_URL` at it in step 2. Otherwise this puts
one in front of Bedrock:

```bash
uvx --from "litellm[proxy]" litellm --config examples/litellm_bedrock.yaml --port 4000
```

Check it: `curl -s http://127.0.0.1:4000/v1/models | head -c 200`.

## 2. The engine API (terminal 2)

```bash
(ulimit -v 7500000; \
 SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1 \
 SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE=1 \
 SIMCORE_INFERENCE_REQUESTS_PER_MINUTE=50 \
 SIMCORE_INFERENCE_CONCURRENCY=4 \
 uv run --extra web python -m simcore.web --runs runs --port 8000)
```

* `ulimit -v` caps this process's memory. A corpus draw once took a 16 GB machine into swap and froze it; with the
  cap it fails cleanly instead.
* The batch size, requests-per-minute and concurrency settings exist because Titan v2's default Bedrock quota is
  60 requests per minute and the gateway turns one batched call into one provider call per text. If you raise your
  quota, raise these.
* The endpoint and key are **the server's** environment. The interface never asks for or shows a key.

## 3. The interface (terminal 3)

```bash
cd frontend && npm install
SIMCORE_WEB_URL=http://127.0.0.1:8000 npm run dev      # http://localhost:3000
```

## 4. Author the study in the interface

**Ontology builder** — choose which corpus attributes describe your audience.

1. Search the codebook. Each attribute shows its real value set.
2. **Check coverage before you choose.** Only 20 of the corpus's 1,290 attributes are populated for more than half
   of its measured personas; 659 sit between 10% and 50% and about 600 below 10%. An attribute that sounds right
   can be nearly empty (`habit_budget_tracking` is populated for 0.04%). The builder does not show coverage yet, so
   this is the one step that needs care: a study can pass every check and still be undrawable.
3. Save. The draft is validated against the codebook and stored as a new immutable version (ADR 0044); saving the
   same version twice is refused.

This study's ontology is `education_savings_app` 1.0.0, built on attributes that are densely populated
(`life_stage` 55%, `age_bracket` 82%, `region` 90%, `highest_education` 77%, `demo_employment_status` 84%).

**New study** — load `education_savings_app_persona1m`, or write your own brief. The brief names its audiences with
filters on corpus attributes, in the corpus's own labels. The assumption ledger shows what the brief took on faith.

## 5. Launch it

### From the interface

On **New study**, choose *Real* and fill in:

* the chat and embedding model to pin (the endpoint and key are the server's environment and are never a field);
* **Draw from these shards** and **Admit these persona sources** — the panel lists the shards this machine holds, from `/api/corpus`; tick
  the measured sources only (synthetic rows are refused after the draw is built);
* **Population seed** — the draw the gate previews is the draw the study uses;
* the scale (`/api/anchors` lists each version with its check verdict; the default is the newest that passed);
* the prices, if you want cost recorded, and a budget.

Then **Run gate** (it reads the real corpus with the same choices) and **Run real study**. The buttons stay
disabled and name the mistake until the form is sound.

### From the command line

The same study, as a command. Both write to `runs/`, so the interface shows either exactly alike.

```bash
(ulimit -v 7500000; \
 SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1 \
 SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE=1 \
 SIMCORE_INFERENCE_REQUESTS_PER_MINUTE=50 \
 SIMCORE_INFERENCE_CONCURRENCY=4 \
 uv run python -m simcore.cli concepts run examples/education_savings_app_persona1m.yaml \
   --n 500 --population-seed 4022 --seeds 4021,917731 --horizon 3 --tick-unit day \
   --shards 0000,0004,0005 --sources wiki,gss,amazon,stackoverflow \
   --anchor-version purchase_intent=v2 --elicits purchase --channel survey_room \
   --model amazon.nova-micro-v1:0 --embed-model amazon.titan-embed-text-v2:0 \
   --price-chat-in 0.035 --price-chat-out 0.14 --price-embed-in 0.02 \
   --budget 1.0 --out runs)
```

What each choice means:

* `--sources wiki,gss,amazon,stackoverflow` — the corpus carries synthetic rows beside measured ones, and a persona
  may not have synthesized demographics, so a draw that reaches them is refused. Name the measured sources.
* `--anchor-version purchase_intent=v2` — the scale that scores purchase intent. `v1` fails its own check (rank
  stability 0.500 against a 0.8 floor); `v2` passes (0.929).
* `--elicits purchase` — ask purchase intent, not a free reaction.
* `--seeds 4021,917731` — two replicate worlds, so the run can tell an audience difference from run-to-run noise.
* `--budget 1.0` — a ceiling in dollars. The ladder warns at 80%, freezes optional work at 95%, and pauses at 100%.
  Real spend for this study is about a cent.

The command first draws and **gates** a population. A refused draw exits with code 2, writes `gate-report.json`
and spends nothing. Do not loosen the gate to make it pass; re-draw with a different `--population-seed` and say
you did. (This study's first draw, seed 4021, was refused on `region` at p = 0.034; seed 4022 passed.)

## 6. Watch it

Open `http://localhost:3000`. Pages that work on a run in flight:

| Page | Shows |
|---|---|
| **Overview** | every run, its status and spend |
| **Population** | the gate results with statistics and thresholds, requested against achieved audience mix, the source mix, sample personas with each field's origin |
| **Simulation run** | live: status, last closed tick, turns landed, spend against the budget, degradation rung; **Cancel run** |
| **Trace explorer** | one persona's events, beliefs and verbatims |
| **Scenario atlas**, **Report**, **Calibration** | results and trust, once a world has finished |

A 500-persona world took about 45–50 minutes at Titan's quota (2026-09-20 run: 3 ticks, two scored ticks of 500 answers each). Cancelling loses at most the tick in flight and the run
can be resumed.

## 7. Reading the result

* **Adoption** is share-weighted top-two-box purchase intent from the scored answers. A quantity the run could not
  measure is stated as unmeasured, with the reason, not shown as zero.
* Read audience differences against the **replicate spread** between the two seeds, not against nothing.
* Every finding carries its evidence and the real-world test that would falsify it.
* Trust is stated once and is `UNCALIBRATED`.

## Known limits today

* The interface cannot launch a sweep (a grid of scenarios), force a resume past moved inputs, or set a cache path;
  use the command line for those.
* A study launched from the command line has no launch record, so restarting the engine API while it runs marks it
  `partial`. Resume it from the command line with the same arguments and `--run-id`.
* Non-survey channels (`social_feed`, `forum`, `wom`) are selectable but this guide does not exercise them.
* The ontology builder does not show attribute coverage (step 4).
* The run page shows the first world's id for any seed whose world has not finished.
* Communities often do not form on this corpus; polarization is then unmeasured, and says so.
* The measured personas are dominated by two survey sources: in this study 66% Stack Overflow developers and 26%
  US General Social Survey respondents. Audiences defined by dense demographic attributes are largely developers
  who happen to be parents or retirees. Say so wherever the result is quoted.
