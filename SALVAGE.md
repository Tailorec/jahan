# Salvage Inventory — what we take from OASIS, ASAL, MatrAIx

**Status:** v1 · companion to `ARCHITECTURE.md` (module IDs M1–M28 referenced throughout)
**Ground truth:** repo trees verified via GitHub API (main branches, Feb 2026 snapshots); HF dataset card + `persona_codes.schema.json` read.
**Licenses:** OASIS Apache-2.0 · ASAL Apache-2.0 · MatrAIx MIT · MatrAIx Persona-1M dataset: confirm commercial terms before paid deployment (spec §9 Q4 — blocking).
**Verdict key:** COPY (use code, light touch) · ADAPT (reimplement following the pattern/shape) · SKIP (wrong modality/scale/purpose)

---

## 1. OASIS — `github.com/camel-ai/oasis` (Apache-2.0, `pip install camel-oasis`)

Feeds modules: **M8, M12, M13, M14, M15, M19**.

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `oasis/environment/env.py`, `env_action.py`, `make.py` | **COPY/ADAPT** | M12 | PettingZoo-style `reset()/step(actions)` with per-agent `LLMAction`/`ManualAction`. Fork into `simcore/world/`; swap CAMEL model calls → our ModelRouter (M7); our `Environment` interface (spec §3.5) wraps it |
| `oasis/social_agent/agent_graph.py` | **COPY/ADAPT** | M8/M12 | networkx agent graph + container. **Input adapter:** OASIS expects connections/edges as input — we generate them (M6: seeded topology + tie strengths from attribute homophily/embedding similarity) and inject. twhin-mode follower counts = generated degree centralities. No persona-invention: profiles come from coreset rows |
| `oasis/social_agent/agents_generator.py` | **ADAPT** | M8 | generation *pipeline shape* only; inputs become coreset rows |
| `oasis/social_agent/agent.py`, `agent_action.py`, `agent_environment.py` | **COPY/ADAPT** | M8 | agent↔action↔env indirection; extend ActionType with non-platform verbs (buy, ask_peer, reject) |
| `oasis/social_platform/platform.py` | **COPY** | M13 | platform ops over SQLite (posts/comments/likes/rec_matrix). Add provenance columns (persona row id, stimulus provenance) at write time. **Forum scoping:** one `ForumPlatform` subclass with two presets — `reddit_global` (OASIS behavior as-is) and `community_scoped` (thread visibility = Leiden communities, recency+consensus ranking) — mechanically similar, dynamically distinct (slow consensus hardening vs hot-score herding) |
| `oasis/social_platform/database.py`, `channel.py` | **COPY** | M13/M19 | async-safe channel dict + db wrapper; already trace-shaped — extend, don't rewrite |
| `oasis/social_platform/recsys.py` | **ADAPT** | M14 | **Keep hot-score math verbatim** (Reddit mode, log-based time-decay). Salvage all 4 rec modes: Twitter (interest-match), Twhin-Bert (graph+history personalized), Reddit (hot-score), Random (baseline/control arm) + trace-aware personalized fn — embedder branches swapped to router embeddings (single pinned model). Keep `rec_matrix` max-len + score-normalization logic |
| `oasis/social_platform/process_recsys_posts.py` | **ADAPT** | M14 | post-vector generation — swap embedder to M7 |
| `oasis/social_platform/typing.py` | **ADAPT** | M12/M13 | `ActionType` enum (23 actions) → subset + extension; `RecsysType` (TWITTER/TWHIN/REDDIT/RANDOM) → our filter modes, all four retained |
| `oasis/social_platform/platform_utils.py` | **COPY** | M13 | helpers |
| `oasis/clock/clock.py` | **COPY/ADAPT** | M15 | tick clock + activation probabilities; add straggler-aware world-day semantics (variant worlds finish at different ticks) |
| `oasis/environment/graph utils` (networkx usage in agent_graph) | **ADAPT** | M6 | graph container only — topology is OURS: seeded two-layer build (Watts–Strogatz strong ties for clustering + preferential attachment weak ties for hub tail) with category-fitted params, homophily rewiring, tie-strength weights `0.45×emb-cos + 0.35×homophily + 0.20×strong`; full procedure in ARCHITECTURE.md §M6. Gates: degree KS, clustering ±0.05, giant component ≥98%, graph hash in CohortManifest |
| `oasis/social_platform/config/user.py` | **ADAPT** | M8 | profile config shape |
| Interview action (in platform action set) | **COPY** | M13 | SurveyRoom answer elicitation |
| `generator/` (LLM user generation) | **SKIP** | — | grounded coreset sampling replaces persona invention |
| 1M-agent async inferencer machinery | **SKIP** (now) | — | our scale is 10²–10³ agents; revisit Phase 4+ if partner scale demands |
| CAMEL `ModelFactory` dependency | **DECIDE Phase 1** | M7 | it already supports `AWS_BEDROCK` platform type; default plan is own wrapper (cost/trace instrumentation close to the metal). Spike both, keep the thinner one |

## 2. ASAL — `github.com/SakanaAI/asal` (Apache-2.0, JAX)

Feeds modules: **M20, M21, M22, M23**. Nothing copy-pasted — JAX/CLIP is the wrong modality; we reimplement the *algorithms and interface discipline* in plain Python (`simcore/search/`).

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `substrates/*` (Init/Step/Render contract) | **ADAPT (pattern)** | M20 | substrate = market world: `init(scenario) → step(tick) → digest()`. Render→outcome digest is the key translation |
| `rollout.py` | **ADAPT (pattern)** | M20 | run-T-then-score shape = our surrogate world run + outcome digest |
| `main_opt.py` (CMA-ES / Sep-CMA-ES) | **ADAPT (v2)** | M21 | supervised-target optimizer over continuous θ (price, audience mix). v1 ships LLM-proposer + grid; port their parameterization/termination when v2 lands |
| `main_illuminate.py` | **ADAPT** | M22 | genetic illumination: mutate → rollout → keep diverse top-K. Archive keyed on measured (adoption, polarization) — JSD between segment PMFs (spec §3.7.1) — with outcome-embedding dedupe replacing CLIP |
| `main_sweep_gol.py` | **ADAPT (pattern)** | M21 | brute-force discrete sweep = Phase-1 grid fallback; also mirrors `scripts/sweep run` |
| `asal_metrics.py` | **ADAPT (pattern)** | M23 | FM-as-fitness structure: prompt → score over rollouts. Market version: judge rubrics (target/novelty/diversity/dynamics) with cited evidence, then router outcome-embeddings as v2 scorer |
| `foundation_models/clip.py`, `dino.py`, `pixels.py` | **SKIP** | — | image modality; "VLM role" = LLM-judge (v1) / text-embedding (v2) |
| All JAX substrate code (lenia, boids, nca, …) | **SKIP** | — | wrong substrate |

**Acceptance oracle:** our illumination should find ≥N distinct worlds within a run budget the way ASAL finds diverse Lenia lifeforms — same search behavior, different substrate. Mockup parity already exists (`mockups/sim.js` MiniAtlasSweep is the algorithm in miniature).

## 3. MatrAIx — `github.com/MatrAIx-ai/MatrAIx-Persona-8B` (MIT) + HF `MatrAIx2026/MatrAIx_Persona_1M`

Biggest salvage. Feeds modules: **M3, M4, M5, M7, M8, M9, M17, M25**.

### 3.1 Dataset & schema (COPY)

| Artifact | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_codes.schema.json` (1,290-field codebook + packing spec) | **COPY** | M3/M5 | the contract for decode + Persona projection |
| `data/persona-1m-*.parquet` (packed 4-bit, null-bitmap, `attribute_overrides`) | **USE** | M3 | read with pyarrow (datasets lib can't open it); sparse `.get()` semantics; ~656/1290 avg populated |
| `indexes/postings.sqlite` + `indexes/manifest.json` | **USE** | M4 | value→row-id filtering without 4 GB scans |
| `calibration_targets.json`, `audit.json`, `RESULTS.md` | **USE** | M4/M24 | distribution-gate targets; audit trail reference |
| Per-row `source` / `grounding` provenance | **USE** | M5/M19 | powers `grounded` vs `synthesized` labeling end-to-end |

### 3.2 Playground package (`packages/playground/src/playground/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_model.py` | **COPY/ADAPT** | M7 | model-ID resolution precedence (CLI → env → config → default) — reuse verbatim for per-role model pinning (tier_a/tier_b/embed/judge) |
| `model_client.py` | **COPY** | M7 | **Upgraded verdict (provider-agnostic router decision):** their multi-provider client — provider-prefixed model resolution (`dashscope/…`, `gemini/…`, `openrouter/…`, `xai/…`, `deepseek/…`, `zai/…`), JSON coercion, per-provider timeouts — is exactly our shape. Keep ALL provider branches; add `bedrock/` (via OpenRouter/LiteLLM route or boto3 adapter) and a `vllm/` local branch for Persona-8B |
| `openai_client.py` | **COPY/ADAPT** | M7 | their `coerce_json` + request-timeout patterns; the OpenAI-compatible client is the router's primary transport (works against OpenRouter/LiteLLM/vLLM alike) |
| `llm_usage.py` | **COPY/ADAPT** | M17 | per-completion token/usage accounting → cost governor ledger |
| `survey_task_content.py` | **COPY/ADAPT** | M13 (SurveyRoom) | questionnaire YAML → task content; instrument registry pattern |
| `survey_list_meta.py` | **COPY** | M13 | questionnaire list metadata |
| `inprocess/survey_eval.py` | **ADAPT** | M13 | batch survey execution + structured answer validation; strip Harbor eval framing, add SSR instructions (free-text intent, no numbers) |
| `structured_exposure.py` | **ADAPT** | M19 | exposure-record shape — reconcile with our `Exposure` schema before adopting |
| `self_report_runtime.py`, `self_report_task_config.py` | **ADAPT (Phase 4)** | M25 | self-report grounding ingestion — the pattern for paper-13 calibration loop |
| `scoring.py`, `budget.py` | **ADAPT** | M17/M24 | scoring plumbing + budget accounting patterns |
| `persona_catalog.py`, `persona_model.py` resolution | **ADAPT** | M4 | persona-pool selection patterns |
| Web/playground app, Harbor runtime, remote_runner | **SKIP** | — | eval-infrastructure framing is orthogonal to market simulation |

### 3.3 Persona agents (`environment/agents/matraix/agents/persona/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `templating.py` | **COPY/ADAPT** | M8 | 1,290-dim profile → structured prompt sections. This is the hardest prompt-engineering problem they already solved |
| `json_survey.py` | **ADAPT** | M8/M9 | persona-conditioned JSON survey answering; add SSR free-text mode (no numeric elicitation) |
| `user_sim.py` | **ADAPT** | M8 | chat-style persona simulation — conversation turns in WOM/forum |
| `mixin.py`, `loader.py` | **COPY/ADAPT** | M8 | persona-agent composition + loading |
| `browser_use.py`, `computer_1.py`, `cocoa.py`, `claude_code.py`, `codex.py`, … | **SKIP** | — | web/OS agent environments — orthogonal |

### 3.4 Backend services (`application/backend/service/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `build_persona_1m_indexes.py` | **COPY/ADAPT** | M3 | builds the postings index for the exact HF dataset — if we ever rebuild indexes (e.g., extra fields), this is the tool |
| `persona_1m_index.py`, `persona_1m_pool.py` | **COPY/ADAPT** | M3/M4 | index querying + persona pool management against packed shards |
| `bundle_catalog.py`, `catalog_index.py` | **ADAPT** | M13 | content-bundle cataloging for stimuli (concepts, claims, creatives) |
| `job_aggregation.py`, `jobs.py` | **ADAPT** | M16/M19 | job/run aggregation patterns → our run registry |
| `llm_usage_view.py` | **ADAPT** | M17 | usage reporting views |
| `config.py` | **ADAPT** | M7 | env/config resolution patterns |
| everything Harbor/web/appworld | **SKIP** | — | web-task eval machinery |

### 3.5 Persona-8B model weights (HF)

| Verdict | → Module | Notes |
|---|---|---|
| **ADAPT** | M7 Tier-A | serving options in order: **OpenRouter-hosted Persona-8B** (zero serving infra, OSS provider) → **self-hosted vLLM** (OpenAI-compatible; cheapest at volume) → Bedrock Custom Model Import (if enterprise route requires AWS residency) → Nova Micro / GPT-4o-mini fallback. Phase-0 tick-fidelity microbenchmark decides; benchmark *distribution* fidelity, not chat quality |

## 4. Cross-repo rules

1. **One model router (M7)** — no repo talks to a model provider directly; all calls flow through the provider-agnostic router so token accounting, pinning, and trace hashes are universal. Bedrock models remain reachable through the router (OpenRouter/LiteLLM route or boto3 adapter) — the router is the lock-in boundary, not a vendor.
2. **Forked OASIS code lives in `simcore/world/`** with license headers intact + a `NOTICE.md` crediting CAMEL-AI, Sakana AI, MatrAIx (Apache-2.0/MIT require attribution).
3. **Re-benchmark after every salvage** — copied code changes behavior; the calibration harness (M24) is the referee. A salvage that degrades KS/correlation-attainment gets reverted or fixed before merge.
4. **No persona-invention code from any repo** — grounded sampling only (anti-collapse + provenance invariants, spec §5.4).
5. **Upstream tracking:** OASIS and MatrAIx are actively maintained (OASIS releases monthly; MatrAIx iterates the dataset). Pin upstream SHAs in `SALVAGE.md` PRs; review upstream diffs quarterly for recsys/clock fixes worth re-porting.

## 5. Salvage → phase summary

| Phase | Salvage pulled |
|---|---|
| 0 | MatrAIx index/pool + schema (M3/M4); `model_client.py` + `openai_client.py` + `llm_usage.py` (M7/M17 — multi-provider router core); SSR harness uses router embeddings |
| 1 | OASIS env/clock/agent-graph fork (M12/M8); MatrAIx survey content + eval (M13); Tier-A serving decision (OpenRouter/vLLM/Bedrock CIM microbenchmark) |
| 2 | OASIS platform/db/recsys (M13/M14/M19); hot-score verbatim; embeddings swapped to router; moderation on |
| 3 | ASAL patterns → `simcore/search/*` (M20–M23); Batch Inference for sweeps |
| 4 | MatrAIx self-report runtime (M25); Persona-8B Tier-A finalized; judge benchmarked |
