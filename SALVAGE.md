# Salvage Inventory — OASIS · ASAL · MatrAIx

**Status:** v2 · companion to `FINAL_ARCH.md`, whose twelve module names are used throughout. The older `M1`–`M28` numbering is retired; `FINAL_ARCH.md` §3 carries the mapping.
**Scope:** everything salvaged into the engine. Rows marked `deferred` feed capabilities parked in `FINAL_ARCH.md` §12 — they are recorded here so the mapping survives, not because they ship now.
**Ground truth:** re-verified against local clones on 2026-09-14 — OASIS `0004f5b`, ASAL `677ba0e`, MatrAIx `3633d8d`, MiroFish `39d8491` — and against the `MatrAIx2026/MatrAIx_Persona_1M` dataset card, `persona_codes.schema.json`, `calibration_targets.json`, `RESULTS.md` and `manifest.json` on 2026-09-15. Earlier claims corrected by that pass are marked **corrected**.
**Licenses:** OASIS Apache-2.0 · ASAL Apache-2.0 · MatrAIx code MIT · MiroFish **AGPL-3.0** (no code salvaged, §4) · MatrAIx Persona 1M dataset **`matraix-research-only`: non-commercial research use**, subsets inherit the terms, upstream sources add their own (Wikipedia CC BY-SA 4.0, Stack Overflow ODbL, PRISM CC BY-NC, Amazon Reviews research use, NORC terms for GSS). The engine is a research instrument (ADR 0016). It never bundles the shards and no corpus row enters the repository, the Dataset Viewer sample included — the user fetches shards explicitly (`hf download …`) into a cache outside the repository and accepts the dataset's own terms, and `HfCoresetSource` reads that cache, verifying every file against `manifest.json` on each use and downloading nothing on its own (ADR 0016, ADR 0020); a synthetic source keeps the quickstart working regardless (`FINAL_ARCH.md` §4).
**Verdict key:** COPY (use code, light touch) · ADAPT (reimplement following the pattern/shape) · SKIP (wrong modality/scale/purpose)

---

## 1. OASIS — `github.com/camel-ai/oasis` (Apache-2.0, `pip install camel-oasis`)

Feeds modules: **`agent`, `world`, `trace`**. Fully redistributable — Apache-2.0 permits forking, modifying, and relicensing under Apache-2.0 with attribution. Keep license headers intact in every forked file; CAMEL-AI attribution lives in `NOTICE.md`.

**Corrected — how deep the coupling runs.** OASIS requires Python < 3.12 and pins `camel-ai`, `neo4j` and `sentence-transformers`, so it can be copied with attribution but never installed as a dependency of this engine (Python ≥ 3.12). Its agents subclass CAMEL's `ChatAgent` and act through CAMEL `FunctionTool` calls with a `BaseModelBackend`/`ModelManager`; the package itself never calls `ModelFactory` (only its examples do). Adopting its agents therefore means rewriting the agent loop onto our router, not swapping a model call.

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `oasis/environment/env.py`, `env_action.py`, `make.py` | **COPY/ADAPT** | `world` | PettingZoo-style `reset()/step(actions)` with per-agent `LLMAction`/`ManualAction`. Fork into `simcore/world/`; swap CAMEL model calls → our ModelRouter (`inference`); our `Environment` interface wraps it |
| `oasis/social_agent/agent_graph.py` | **COPY/ADAPT** | `agent`/`world` | **Corrected:** an **igraph** agent graph with an optional Neo4j backend, not networkx. **Input adapter:** OASIS expects connections/edges as input — we generate them (`population`: seeded topology + tie strengths from attribute homophily/embedding similarity) and inject. twhin-mode follower counts = generated degree centralities. No persona-invention: profiles come from coreset rows |
| `oasis/social_agent/agents_generator.py` | **ADAPT** | `agent` | generation *pipeline shape* only; inputs become coreset rows |
| `oasis/social_agent/agent.py`, `agent_action.py`, `agent_environment.py` | **ADAPT** | `agent` | agent↔action↔env indirection. **Corrected:** `SocialAgent` subclasses CAMEL `ChatAgent` and dispatches actions as `FunctionTool` calls, so this is a rewrite onto our router, not a copy. `PURCHASE_PRODUCT` and `INTERVIEW` already exist; extend with ask_peer and reject. **Shipped (M6 `agent`):** the shape only — batch turns through `ChatPort`, the agent proposing actions the world disposes; no CAMEL, no tools, no swallowed errors |
| `oasis/social_platform/platform.py` | **COPY** | `world` | platform ops over SQLite (posts/comments/likes/rec_matrix). Add provenance columns (persona row id, stimulus provenance) at write time. **Forum scoping:** one `ForumPlatform` subclass with two presets — `reddit_global` (OASIS behavior as-is) and `community_scoped` (thread visibility = Leiden communities, recency+consensus ranking) — mechanically similar, dynamically distinct (slow consensus hardening vs hot-score herding) |
| `oasis/social_platform/database.py`, `channel.py` | **COPY** (`world`) / **ADAPT** (`trace`) | `world`/`trace` | async-safe channel dict + db wrapper; already trace-shaped. The `trace` store (`simcore/trace/store.py`) is new code following that shape — tick-atomic SQLite while live, fanned-out Parquet once finished — with no forked lines; `world`'s platform state keeps the COPY verdict |
| `oasis/social_platform/recsys.py` | **ADAPT** | `world` | **Corrected:** the module imports torch, sentence-transformers and a twhin-bert model at import time, so extract the scoring functions rather than copying the file. **Keep hot-score math verbatim** (Reddit mode, log-based time-decay). Salvage all 4 rec modes: Twitter (interest-match), Twhin-Bert (graph+history personalized), Reddit (hot-score), Random (baseline/control arm) + trace-aware personalized fn — embedder branches swapped to router embeddings (single pinned model). Keep `rec_matrix` max-len + score-normalization logic |
| `oasis/social_platform/process_recsys_posts.py` | **ADAPT** | `world` | post-vector generation — swap embedder to `inference` |
| `oasis/social_platform/typing.py` | **ADAPT** | `world` | `ActionType` enum (**corrected: 32 actions**, including `PURCHASE_PRODUCT`, `INTERVIEW` and five group actions) → subset + extension; `RecsysType` (TWITTER/TWHIN/REDDIT/RANDOM) → our filter modes, all four retained |
| `oasis/social_platform/platform_utils.py` | **COPY** | `world` | helpers |
| `oasis/clock/clock.py` | **ADAPT** | `world` | **Corrected:** a 33-line time-scaling clock (a speed multiplier and a step counter). Activation probabilities are not implemented upstream — only a TODO in `agents_generator.py` — so activation is ours to build; add straggler-aware tick semantics (variant worlds finish at different ticks); the scenario declares the tick unit |
| `oasis/environment/graph utils` (networkx usage in agent_graph) | **ADAPT** | `population` | graph container only — topology is OURS: seeded two-layer build (Watts–Strogatz strong ties for clustering + preferential attachment weak ties for hub tail) with category-fitted params, homophily rewiring, tie-strength weights `0.45×emb-cos + 0.35×homophily + 0.20×strong`; full procedure in `FINAL_ARCH.md` §5.3. Gates: degree KS, clustering ±0.05, giant component ≥98%, graph hash in the population manifest |
| `oasis/social_platform/config/user.py` | **ADAPT** | `agent` | profile config shape |
| Interview action (in platform action set) | **COPY** | `world` | SurveyRoom answer elicitation |
| `generator/` (LLM user generation) | **SKIP** | — | grounded coreset sampling replaces persona invention |
| 1M-agent async inferencer machinery | **SKIP** (now) | — | our scale is 10²–10³ agents; revisit if partner scale demands |
| CAMEL `ModelFactory` dependency | **SKIP** | `inference` | **Corrected:** the OASIS package does not use `ModelFactory`; only its examples do. Taking CAMEL for model access would pull in its agent framework for a transport. **Reviewed 2026-09-16:** OASIS has no inference layer of its own — models are created in user scripts, `SocialAgent` passes `scheduling_strategy='random_model'` so one persona's calls can land on different models, interviews call CAMEL's private `_aget_model_response` because CAMEL memory cannot be stopped from updating, `perform_action_by_llm` catches every exception and returns it as a value, and there are no retries, caching, seeds or cost accounting. Only its pattern is taken: async fan-out behind one `asyncio.Semaphore`. Model access is one OpenAI-compatible endpoint (ADR 0021) |

---

## 2. ASAL — `github.com/SakanaAI/asal` (Apache-2.0, JAX)

Nothing is copy-pasted: JAX/CLIP is the wrong modality, so anything used here is reimplemented in plain Python. Only the sweep pattern ships now; the illumination and optimisation algorithms map to `analysis` and are deferred (`FINAL_ARCH.md` §12).

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `main_sweep_gol.py` | **ADAPT (pattern)** | `runner`/`cli` | **Corrected:** the script scores the novelty of Game of Life rule sets with JAX, CLIP and evosax. The only transferable idea is iterating a grid of configurations, which needs no salvage; nothing is copied |

---

## 3. MatrAIx — `github.com/MatrAIx-ai/MatrAIx-Persona-8B` (MIT) + HF `MatrAIx2026/MatrAIx_Persona_1M`

Biggest salvage. Feeds **`population`, `inference`, `agent`, `elicitation`, `runner`**.

### 3.1 Dataset & schema (COPY)

| Artifact | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_codes.schema.json` (1,290-field codebook + packing spec) | **USED** | `ports/decoder` | the contract for decode + Persona projection. Verified: format `persona_codes` v2, `code_base` 0, nibble packing, 645 bytes per row, each field with `id`, `label`, `category`, `values` (at most 16). It documents none of the three decoding rules the shipped shards actually follow (see below). Its value lists, not the repo's `persona/schema/dimensions.json`, are the completion value sets — the repo file drifts from the data |
| `data/persona-1m-0000..0009.parquet` (packed 4-bit, null-bitmap, `attribute_overrides`, per-field `grounding`, `descriptions`, `metadata_json`) | **USED** | `ports/hf` | 999,847 personas, 4.17 GB Zstandard across ten shards; 656.01/1,290 populated on average. Read with pyarrow (the `datasets` lib can't open the packed layout). **Source counts (from `manifest.json`):** wiki 323,438 · synthetic 400,000 · amazon 97,915 · stackoverflow 113,120 · gss 63,532 · prism 1,487 · real_human_survey 355. **Sources are segregated across shards by row range, not one source per shard** — a single shard carries several sources (measured: shard 0004 is amazon + stackoverflow, shard 0005 is stackoverflow + gss + prism + real_human_survey), so a row's source is read from each row's own `source` column, never from which shard it sits in. **Human sources are sparse, synthetic complete:** mean populated attributes measured gss 14.6 · amazon 24.9 · stackoverflow 77.2 · prism 178 · wiki 460 · synthetic 1,290. **Calibrated to the 2024 global population including children** — only real-survey minors were removed, so a demographic gate can see `Under 5` on a `wiki` entity. **Not the Dataset Viewer's `sample/sample.parquet`**, a decoded 999-row preview outside the release. **Not bundled** — `HfCoresetSource` reads shards a user fetched explicitly; the engine downloads nothing (ADR 0016) |
| the three decoding rules the dataset card omits | **VERIFIED** | `ports/decoder` | **Codes are 4-bit, indexed from zero** (`code_base: 0` — a one-indexed reading gets 0/8 on entities whose sex is not in doubt), **two to a byte, low nibble first**; **the null bitmap is the sole authority on presence** — `populated_attribute_count` equals its present-count on 586/586 sampled rows, never the non-zero-code count — and **an absent bitmap means fully populated**, which is how the 400,000 synthetic rows survive; **`attribute_overrides` supersede the code**, sit on code 0 without exception (345,483/345,483), and are out of vocabulary without exception — most are structured missingness (`null`, `Not applicable`, `No coding activity`) folding to absent, a few are real values the enum cannot express (`65+`, `Adult children`) and decode as absent, never admitted raw or guessed into a band — and are counted as unexpressible, since dropping them removes exactly the oldest respondents (336 Stack Overflow rows in shard 0005). The vocabulary is checked before the sentinels: 435 codebook values are words like `None`. Ignoring the overrides mislabels ~40% of `wiki` rows as toddlers |
| `indexes/postings.sqlite` (named by `indexes/manifest.json`) + `manifest.json` | **SKIP** | `ports/index_catalog` | **Corrected:** the release's index is 2,636 MB, not "~1 MB", and ships no small count table. The engine builds its own postings from the cached shards' packed arrays for the attributes and sources a study names, saves them beside the cache keyed by the manifest's shard digests, and verifies the saved archive's digest on each load — 2.66 MB for the Stack Overflow example's eight attributes. `manifest.json` is **USED** for every digest |
| `calibration_targets.json`, `audit.json`, `RESULTS.md` | **USE** | `population` | **Corrected:** these are *global population* margins (UN WPP 2024 for age and region, UN/World Bank for gender and urbanicity), not category targets. They match the shape of `CategoryTargets` and can serve as a general-population reference. `RESULTS.md` reports `age_bracket` known in 70.5% of rows |
| Per-row `source` and per-field `grounding` provenance | **USE** | `ports/hf`/`population` | `grounding` carries per-field `evidence`, `confidence` and `assignment_type`. **Corrected (ADR 0017):** the open question about "what grounded means for synthetic rows" is settled — the adapter grades a field from source *and* assignment type together: in the survey sources `gss`/`stackoverflow`/`prism`/`real_human_survey` a value is `MEASURED` when the instrument recorded it (`direct`, `structured_claim`, or no grounding entry — `real_human_survey` has none) and `EXTRACTED` when a model inferred it (`summary_inference`, `unsupported`: 15% of Stack Overflow's `att_ai`); `wiki`/`amazon` → `EXTRACTED` (a model reading text); `synthetic` → `SYNTHESIZED`; an unknown source is never `MEASURED`. PRISM's `direct` evidence is a rendered questionnaire (*"A 35-44-year-old man based in Canada."*). A source-level label would be false for the two sources where it matters: `gss` and `amazon` both report `direct`, and within `wiki` 49% of grounding is `unsupported` |

### 3.2 Playground package (`packages/playground/src/playground/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_model.py` | **ADAPT (CLI only)** | `cli` | **Corrected:** it resolves one persona model from arguments and environment variables. Model pins change results, so they are recorded in `RunConfig`, never read from the environment inside the engine; this precedence may only seed CLI defaults that are then recorded |
| `model_client.py` | **ADAPT** | `inference` | **Corrected:** not a router core. It is a JSON-mode client factory: provider-prefixed ids (`dashscope/`, `gemini/`/`google/`, `openrouter/`, `xai/`, `deepseek/`, `zai/`, `openai/`) mapped to OpenAI-compatible base URLs, plus raw Anthropic Messages calls. It has no retries, fallback, caching, coalescing, embeddings, Bedrock or vLLM. **Withdrawn (ADR 0021):** the base-URL table is no longer needed — the engine talks to one base URL the user configures, and a gateway owns provider translation |
| `openai_client.py` | **COPY/ADAPT** | `inference` | verified: `coerce_json` + request timeouts are kept. The client itself is not: the engine's transport is `httpx`, because the request bytes must be exactly what is hashed, response headers carry the served model and gateway cost, and a provider SDK retries on its own (ADR 0021). **Shipped (M4):** `coerce_json` salvaged into `simcore/inference/_parsing.py`; timeouts became `httpx` execution settings |
| `llm_usage.py` | **ADAPT** | `runner` | per-completion token/usage accounting → cost governor ledger. **Corrected:** prices come from LiteLLM (`completion_cost`, `model_cost`), so copying it takes a LiteLLM dependency. Its `cost_source` idea is kept without the dependency: a cost is `gateway`-reported, from a `price_table` the study declares, or `unknown` — never an estimate presented as a price. **Shipped (M4):** `CostSource` and `served_model_id` on every cost event; token accounting and estimates live in the inference limiter; budget refusal of `unknown` stays owed to `runner` (PRD M4 story 15, deferred) |
| `survey_task_content.py` | **COPY/ADAPT** | `world` (SurveyRoom) | questionnaire YAML → task content; instrument registry pattern |
| `survey_list_meta.py` | **COPY** | `world` | questionnaire list metadata |
| `inprocess/survey_eval.py` | **ADAPT** | `world` | batch survey execution + structured answer validation; strip Harbor eval framing, add SSR instructions (free-text intent, no numbers) |
| `structured_exposure.py` | **ADAPT** | `trace` | exposure-record shape — reconcile with our `Exposure` schema before adopting |
| `scoring.py`, `budget.py` | **ADAPT** | `runner` | budget-accounting plumbing patterns |
| `persona_catalog.py`, `persona_model.py` resolution | **ADAPT** | `population` | persona-pool selection patterns |
| Web/playground app, Harbor runtime, remote_runner | **SKIP** | — | eval-infrastructure framing is orthogonal to market simulation |

### 3.3 Persona agents (`environment/agents/matraix/agents/persona/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `templating.py` | **ADAPT** | `agent` | **Corrected:** 70 lines of Jinja glue rendering persona **YAML** files. The prompt-engineering asset is the three templates in `templates/` (`persona_system`, `persona_instruction`, `persona_macros`), `src/matraix/persona_dimension_catalog.py` (454 lines), and `persona/schema/dimensions.json` — 1,290 dimensions with a `phrase` per dimension ("aged {value}"), the natural seed for rendering a persona block. **Shipped (M6 `agent`):** the phrase style only — one `- attribute: value` line per ontology-selected attribute in relevance order, rendered once per persona per run through a runner-held cache |
| `json_survey.py` | **ADAPT** | `agent`/`elicitation` | persona-conditioned JSON survey answering; add SSR free-text mode (no numeric elicitation) |

**Corrected — SSR has code.** `FINAL_ARCH.md` once said the SSR method had no implementation. The authors published `pymc-labs/semantic-similarity-rating` (Apache-2.0). Its `compute.py` is **ADAPT — port with attribution** (ADR 0026): similarity `(1 + cosine) / 2`, subtract-the-minimum normalisation per anchor set, mean across sets, then temperature — not the softmax the architecture had specified. **Shipped (M5)** as `simcore/elicitation/_compute.py`, with the attribution and licence notice in the source and the reference's known answers as boundary tests. Its `response_rater.py` is **SKIP**: it runs its own `sentence-transformers` model, bypassing the pinned embedding endpoint. The paper's anchor statements were never published, and were tuned on the paper's own evaluation surveys (ADR 0027).
| `user_sim.py` | **ADAPT** | `agent` | chat-style persona simulation — conversation turns in WOM/forum. **Shipped (M6 `agent`):** the turn shape only — perceive, answer, remember — as batch jobs carrying their own state |
| `mixin.py`, `loader.py` | **COPY/ADAPT** | `agent` | persona-agent composition + loading |
| `browser_use.py`, `computer_1.py`, `cocoa.py`, `claude_code.py`, `codex.py`, … | **SKIP** | — | web/OS agent environments — orthogonal |

### 3.4 Backend services (**corrected path:** `application/playground/backend/service/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `build_persona_1m_indexes.py` | **COPY/ADAPT** | `population` | builds the postings index for the exact HF dataset — if we ever rebuild indexes (e.g., extra fields), this is the tool |
| `persona_1m_index.py`, `persona_1m_pool.py` | **COPY/ADAPT** | `population` | index querying + persona pool management against packed shards |
| `bundle_catalog.py`, `catalog_index.py` | **ADAPT** | `world` | content-bundle cataloging for stimuli (concepts, claims, creatives) |
| `job_aggregation.py`, `jobs.py` | **ADAPT** | `runner`/`trace` | job/run aggregation patterns → our run registry |
| `llm_usage_view.py` | **ADAPT** | `runner` | usage reporting views |
| `config.py` | **ADAPT** | `inference` | env/config resolution patterns |
| everything Harbor/web/appworld | **SKIP** | — | web-task eval machinery |

### 3.4a Found while verifying

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `persona/validation/scripts/decode_persona_1m.py` | **ADAPT** | `ports` (coreset adapter) | a 37-line reference decoder matching the dataset card: nibbles low first, set null-bitmap bit means missing, schema from the Hub |
| `application/playground/litellm/config.yaml`, `run_proxy.sh` | **ADAPT (pattern)** | `inference`/`runner` | a LiteLLM proxy used as one global rpm/tpm limiter for every concurrent run, because bursts hit provider 429s. Kept as documentation: the engine always runs its own adaptive request and token limiter, and several engine processes share the gateway's limits as a common ceiling. **Shipped (M4)** as `docs/inference.md`: LiteLLM (retries, fallbacks, cache off; shared rpm/tpm), vLLM and Ollama configurations |
| `persona/schema/dimensions.json` | **ADAPT** | `authoring` (ADR 0014) | the 1,290-dimension catalogue with labels, categories, values, phrases and defaults — the codebook ADR 0014's ontology drafting needs, available in the code repo. Drifts from the release codebook in places |

### 3.5 Persona-8B model weights (HF)

| Verdict | → Module | Notes |
|---|---|---|
| **ADAPT** | `inference` Tier-A | serving options in order: **OpenRouter-hosted Persona-8B** (zero serving infra, OSS provider) → **self-hosted vLLM** (OpenAI-compatible; cheapest at volume) → Bedrock Custom Model Import (if enterprise route requires AWS residency) → Nova Micro / GPT-4o-mini fallback. Phase-0 tick-fidelity microbenchmark decides; benchmark *distribution* fidelity, not chat quality |

---

## 4. MiroFish — `github.com/666ghj/MiroFish` (**AGPL-3.0**)

**No code salvaged.** AGPL would bind the whole engine if any of its code were copied in; it is studied as prior art only, and anything it suggests is rebuilt clean-room.

It is the closest existing product: seed documents → LLM-generated ontology of entity and relation types → Zep Cloud graph memory → **LLM-invented agent profiles** → OASIS simulations (`camel-oasis` as a package) → a 2,600-line report agent, served by Flask over the OpenAI SDK. Its central choices are the ones this engine's ADRs reject — personas invented by a model rather than sampled from records, an ontology generated without a corpus to ground it (contrast ADR 0014), and hosted memory — which makes it the natural comparison for whether grounding changes the findings.

---

## 5. Cross-repo rules

1. **One inference module over one endpoint** — no repo talks to a model provider directly, and none imports a provider SDK; all calls go to one OpenAI-compatible endpoint the user runs, so token accounting, pinning, served-model verification and trace hashes are universal. Bedrock is reached through the user's gateway (LiteLLM by default) — the protocol is the lock-in boundary, not a vendor (ADR 0021).
2. **Forked OASIS code lives in `simcore/world/`** with license headers intact + a `NOTICE.md` crediting CAMEL-AI and MatrAIx (Apache-2.0/MIT require attribution).
3. **Re-benchmark after every salvage** — copied code changes behaviour. With no calibration harness (deferred, `FINAL_ARCH.md` §12), golden-run regression tests (`FINAL_ARCH.md` §8) are the referee. A salvage that changes golden-run output gets reviewed and re-committed deliberately, not silently.
4. **No persona-invention code from any repo** — grounded sampling only (anti-collapse + provenance invariants, spec §5.4).
5. **Upstream tracking:** OASIS and MatrAIx are actively maintained (OASIS releases monthly; MatrAIx iterates the dataset). Pin upstream SHAs in this file's future PRs; review upstream diffs quarterly for recsys/clock fixes worth re-porting.

---

## 6. Salvage → phase summary (OSS)

| Phase | Salvage pulled |
|---|---|
| 0 | MatrAIx index/pool + codebook schema (`population`); `openai_client.py` (`coerce_json`) + `llm_usage.py`'s cost-source idea (`inference`, cost accounting into `runner`); SSR harness uses router embeddings |
| 1 | OASIS env/clock/agent-graph fork (`world`/`agent`); MatrAIx survey content + eval (`world`); Tier-A serving decision (OpenRouter/vLLM/Bedrock CIM microbenchmark) |
| 2 | OASIS platform/db/recsys (`world`/`trace`); hot-score verbatim; embeddings swapped to router; moderation on |
| 3 | No ASAL salvage beyond the grid-sweep pattern already in `runner` |

Salvage for deferred capabilities — MatrAIx's self-report runtime for a future calibration loop, and ASAL's illumination and optimisation algorithms — is listed in §2 and §3 with a `deferred` target, and pulled only if `FINAL_ARCH.md` §12's return criteria are met.
