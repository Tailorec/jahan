# Salvage Inventory — OASIS · ASAL · MatrAIx

**Status:** v2 · companion to `FINAL_ARCH.md`, whose twelve module names are used throughout. The older `M1`–`M28` numbering is retired; `FINAL_ARCH.md` §3 carries the mapping.
**Scope:** everything salvaged into the engine. Rows marked `deferred` feed capabilities parked in `FINAL_ARCH.md` §12 — they are recorded here so the mapping survives, not because they ship now.
**Ground truth:** repo trees verified via GitHub API (main branches, Feb 2026 snapshots); HF dataset card + `persona_codes.schema.json` read.
**Licenses:** OASIS Apache-2.0 · MatrAIx MIT · MatrAIx Persona-1M dataset: confirm commercial terms before public/paid deployment — resolve before public release. The engine never bundles the shards — `CoresetSource` downloads them at first run so users accept the dataset's own terms, and a synthetic fallback source keeps the quickstart working regardless (`FINAL_ARCH.md` §4).
**Verdict key:** COPY (use code, light touch) · ADAPT (reimplement following the pattern/shape) · SKIP (wrong modality/scale/purpose)

---

## 1. OASIS — `github.com/camel-ai/oasis` (Apache-2.0, `pip install camel-oasis`)

Feeds modules: **`agent`, `world`, `world`, `world`, `world`, `trace`**. Fully redistributable — Apache-2.0 permits forking, modifying, and relicensing under Apache-2.0 with attribution. Keep license headers intact in every forked file; CAMEL-AI attribution lives in `NOTICE.md`.

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `oasis/environment/env.py`, `env_action.py`, `make.py` | **COPY/ADAPT** | `world` | PettingZoo-style `reset()/step(actions)` with per-agent `LLMAction`/`ManualAction`. Fork into `simcore/world/`; swap CAMEL model calls → our ModelRouter (`inference`); our `Environment` interface wraps it |
| `oasis/social_agent/agent_graph.py` | **COPY/ADAPT** | `agent`/`world` | networkx agent graph + container. **Input adapter:** OASIS expects connections/edges as input — we generate them (`population`: seeded topology + tie strengths from attribute homophily/embedding similarity) and inject. twhin-mode follower counts = generated degree centralities. No persona-invention: profiles come from coreset rows |
| `oasis/social_agent/agents_generator.py` | **ADAPT** | `agent` | generation *pipeline shape* only; inputs become coreset rows |
| `oasis/social_agent/agent.py`, `agent_action.py`, `agent_environment.py` | **COPY/ADAPT** | `agent` | agent↔action↔env indirection; extend ActionType with non-platform verbs (buy, ask_peer, reject) |
| `oasis/social_platform/platform.py` | **COPY** | `world` | platform ops over SQLite (posts/comments/likes/rec_matrix). Add provenance columns (persona row id, stimulus provenance) at write time. **Forum scoping:** one `ForumPlatform` subclass with two presets — `reddit_global` (OASIS behavior as-is) and `community_scoped` (thread visibility = Leiden communities, recency+consensus ranking) — mechanically similar, dynamically distinct (slow consensus hardening vs hot-score herding) |
| `oasis/social_platform/database.py`, `channel.py` | **COPY** | `world`/`trace` | async-safe channel dict + db wrapper; already trace-shaped — extend, don't rewrite |
| `oasis/social_platform/recsys.py` | **ADAPT** | `world` | **Keep hot-score math verbatim** (Reddit mode, log-based time-decay). Salvage all 4 rec modes: Twitter (interest-match), Twhin-Bert (graph+history personalized), Reddit (hot-score), Random (baseline/control arm) + trace-aware personalized fn — embedder branches swapped to router embeddings (single pinned model). Keep `rec_matrix` max-len + score-normalization logic |
| `oasis/social_platform/process_recsys_posts.py` | **ADAPT** | `world` | post-vector generation — swap embedder to `inference` |
| `oasis/social_platform/typing.py` | **ADAPT** | `world` | `ActionType` enum (23 actions) → subset + extension; `RecsysType` (TWITTER/TWHIN/REDDIT/RANDOM) → our filter modes, all four retained |
| `oasis/social_platform/platform_utils.py` | **COPY** | `world` | helpers |
| `oasis/clock/clock.py` | **COPY/ADAPT** | `world` | tick clock + activation probabilities; add straggler-aware tick semantics (variant worlds finish at different ticks); the scenario declares the tick unit |
| `oasis/environment/graph utils` (networkx usage in agent_graph) | **ADAPT** | `population` | graph container only — topology is OURS: seeded two-layer build (Watts–Strogatz strong ties for clustering + preferential attachment weak ties for hub tail) with category-fitted params, homophily rewiring, tie-strength weights `0.45×emb-cos + 0.35×homophily + 0.20×strong`; full procedure in `FINAL_ARCH.md` §5.3. Gates: degree KS, clustering ±0.05, giant component ≥98%, graph hash in the population manifest |
| `oasis/social_platform/config/user.py` | **ADAPT** | `agent` | profile config shape |
| Interview action (in platform action set) | **COPY** | `world` | SurveyRoom answer elicitation |
| `generator/` (LLM user generation) | **SKIP** | — | grounded coreset sampling replaces persona invention |
| 1M-agent async inferencer machinery | **SKIP** (now) | — | our scale is 10²–10³ agents; revisit if partner scale demands |
| CAMEL `ModelFactory` dependency | **DECIDE Phase 1** | `inference` | it already supports `AWS_BEDROCK` platform type; default plan is own wrapper (cost/trace instrumentation close to the metal). Spike both, keep the thinner one |

---

## 2. ASAL — `github.com/SakanaAI/asal` (Apache-2.0, JAX)

Nothing is copy-pasted: JAX/CLIP is the wrong modality, so anything used here is reimplemented in plain Python. Only the sweep pattern ships now; the illumination and optimisation algorithms map to `analysis` and are deferred (`FINAL_ARCH.md` §12).

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `main_sweep_gol.py` | **ADAPT (pattern)** | `runner`/`cli` | brute-force discrete sweep — the one ASAL pattern the OSS engine uses (grid sweep over user-specified configs). Nothing copy-pasted — JAX/CLIP is the wrong modality; reimplemented in plain Python |

---

## 3. MatrAIx — `github.com/MatrAIx-ai/MatrAIx-Persona-8B` (MIT) + HF `MatrAIx2026/MatrAIx_Persona_1M`

Biggest salvage. Feeds **`population`, `inference`, `agent`, `elicitation`, `runner`**.

### 3.1 Dataset & schema (COPY)

| Artifact | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_codes.schema.json` (1,290-field codebook + packing spec) | **COPY** | `population` | the contract for decode + Persona projection |
| `data/persona-1m-*.parquet` (packed 4-bit, null-bitmap, `attribute_overrides`) | **USE** | `population` | read with pyarrow (datasets lib can't open it); sparse `.get()` semantics; ~656/1290 avg populated. **Not bundled in this repo** — reached through `CoresetSource`, which downloads from HF at first run so users accept the dataset's own terms (`FINAL_ARCH.md` §4) |
| `indexes/postings.sqlite` + `indexes/manifest.json` | **USE** | `population` | value→row-id filtering without 4 GB scans |
| `calibration_targets.json`, `audit.json`, `RESULTS.md` | **USE** | `population` | distribution-gate targets; audit trail reference |
| Per-row `source` / `grounding` provenance | **USE** | `population`/`trace` | powers `grounded` vs `synthesized` labeling end-to-end |

### 3.2 Playground package (`packages/playground/src/playground/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `persona_model.py` | **COPY/ADAPT** | `inference` | model-ID resolution precedence (CLI → env → config → default) — reuse verbatim for per-role model pinning (tier_a/tier_b/embed) |
| `model_client.py` | **COPY** | `inference` | **Provider-agnostic router core:** their multi-provider client — provider-prefixed model resolution (`dashscope/…`, `gemini/…`, `openrouter/…`, `xai/…`, `deepseek/…`, `zai/…`), JSON coercion, per-provider timeouts — is exactly our shape. Keep ALL provider branches; add `bedrock/` (via OpenRouter/LiteLLM route or boto3 adapter) and a `vllm/` local branch for Persona-8B |
| `openai_client.py` | **COPY/ADAPT** | `inference` | their `coerce_json` + request-timeout patterns; the OpenAI-compatible client is the router's primary transport (works against OpenRouter/LiteLLM/vLLM alike) |
| `llm_usage.py` | **COPY/ADAPT** | `runner` | per-completion token/usage accounting → cost governor ledger |
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
| `templating.py` | **COPY/ADAPT** | `agent` | 1,290-dim profile → structured prompt sections. This is the hardest prompt-engineering problem they already solved |
| `json_survey.py` | **ADAPT** | `agent`/`elicitation` | persona-conditioned JSON survey answering; add SSR free-text mode (no numeric elicitation) |
| `user_sim.py` | **ADAPT** | `agent` | chat-style persona simulation — conversation turns in WOM/forum |
| `mixin.py`, `loader.py` | **COPY/ADAPT** | `agent` | persona-agent composition + loading |
| `browser_use.py`, `computer_1.py`, `cocoa.py`, `claude_code.py`, `codex.py`, … | **SKIP** | — | web/OS agent environments — orthogonal |

### 3.4 Backend services (`application/backend/service/`)

| Repo path | Verdict | → Module | Notes |
|---|---|---|---|
| `build_persona_1m_indexes.py` | **COPY/ADAPT** | `population` | builds the postings index for the exact HF dataset — if we ever rebuild indexes (e.g., extra fields), this is the tool |
| `persona_1m_index.py`, `persona_1m_pool.py` | **COPY/ADAPT** | `population` | index querying + persona pool management against packed shards |
| `bundle_catalog.py`, `catalog_index.py` | **ADAPT** | `world` | content-bundle cataloging for stimuli (concepts, claims, creatives) |
| `job_aggregation.py`, `jobs.py` | **ADAPT** | `runner`/`trace` | job/run aggregation patterns → our run registry |
| `llm_usage_view.py` | **ADAPT** | `runner` | usage reporting views |
| `config.py` | **ADAPT** | `inference` | env/config resolution patterns |
| everything Harbor/web/appworld | **SKIP** | — | web-task eval machinery |

### 3.5 Persona-8B model weights (HF)

| Verdict | → Module | Notes |
|---|---|---|
| **ADAPT** | `inference` Tier-A | serving options in order: **OpenRouter-hosted Persona-8B** (zero serving infra, OSS provider) → **self-hosted vLLM** (OpenAI-compatible; cheapest at volume) → Bedrock Custom Model Import (if enterprise route requires AWS residency) → Nova Micro / GPT-4o-mini fallback. Phase-0 tick-fidelity microbenchmark decides; benchmark *distribution* fidelity, not chat quality |

---

## 4. Cross-repo rules

1. **One model router (`inference`)** — no repo talks to a model provider directly; all calls flow through the provider-agnostic router so token accounting, pinning, and trace hashes are universal. Bedrock models remain reachable through the router (OpenRouter/LiteLLM route or boto3 adapter) — the router is the lock-in boundary, not a vendor.
2. **Forked OASIS code lives in `simcore/world/`** with license headers intact + a `NOTICE.md` crediting CAMEL-AI and MatrAIx (Apache-2.0/MIT require attribution).
3. **Re-benchmark after every salvage** — copied code changes behaviour. With no calibration harness (deferred, `FINAL_ARCH.md` §12), golden-run regression tests (`FINAL_ARCH.md` §8) are the referee. A salvage that changes golden-run output gets reviewed and re-committed deliberately, not silently.
4. **No persona-invention code from any repo** — grounded sampling only (anti-collapse + provenance invariants, spec §5.4).
5. **Upstream tracking:** OASIS and MatrAIx are actively maintained (OASIS releases monthly; MatrAIx iterates the dataset). Pin upstream SHAs in this file's future PRs; review upstream diffs quarterly for recsys/clock fixes worth re-porting.

---

## 5. Salvage → phase summary (OSS)

| Phase | Salvage pulled |
|---|---|
| 0 | MatrAIx index/pool + codebook schema (`population`); `model_client.py` + `openai_client.py` + `llm_usage.py` (`inference`, cost accounting into `runner`); SSR harness uses router embeddings |
| 1 | OASIS env/clock/agent-graph fork (`world`/`agent`); MatrAIx survey content + eval (`world`); Tier-A serving decision (OpenRouter/vLLM/Bedrock CIM microbenchmark) |
| 2 | OASIS platform/db/recsys (`world`/`trace`); hot-score verbatim; embeddings swapped to router; moderation on |
| 3 | No ASAL salvage beyond the grid-sweep pattern already in `runner` |

Salvage for deferred capabilities — MatrAIx's self-report runtime for a future calibration loop, and ASAL's illumination and optimisation algorithms — is listed in §2 and §3 with a `deferred` target, and pulled only if `FINAL_ARCH.md` §12's return criteria are met.
