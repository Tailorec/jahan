# ConsumerSim — Engine Architecture

**Status:** v1 (codebase architecture for `sim_engine/`)
**Related docs:** `SALVAGE.md` (exact salvage inventory, same directory) · `../ideas/technical_architecture_sim_engine.md` (design spec v2: layers, loops, schemas, trust model) · `../PRODUCT.md` / `../DESIGN.md` (product context)
**Inference substrate:** OSS / OpenAI-compatible inference router (decided — see §4): one model-agnostic gateway (hosted OpenRouter-style or self-hosted LiteLLM/vLLM) that can serve Bedrock models *and* any other provider model behind one interface.

---

## 1. Repository layout

```
sim_engine/
├── ARCHITECTURE.md            ← this document
├── SALVAGE.md                 ← salvage inventory (what we take from OASIS/ASAL/MatrAIx)
├── pyproject.toml             ← uv-managed package: consumersim
├── simcore/
│   ├── brief/                 ← L1: brief ingestion + provenance
│   ├── coreset/               ← L2: MatrAIx-1M loader, sampling, gates        [SALVAGE: MatrAIx]
│   ├── personas/              ← L2: projection, sparse completion, graph, Leiden
│   ├── llm/                   ← provider-agnostic model router + prompt registry  [NEW + SALVAGE: MatrAIx]
│   ├── cognition/             ← L3: tiered agent runtime, memory, skills, SSR
│   ├── world/                 ← L4: env server, platforms, info filter, time      [SALVAGE: OASIS]
│   ├── execution/             ← L5: scheduler, batching, caching, cost governor
│   ├── search/                ← L6: ASAL-style illuminate/optimize/sweep          [SALVAGE: ASAL patterns]
│   ├── validation/            ← L7: benchmarks, calibration loop, trust tiers
│   ├── reporting/             ← L8: report builder (v1: deterministic, citation-resolving); analyst debate = Phase 4+ upgrade
│   ├── trace/                 ← append-only event store + registry
│   └── schemas/               ← ProductBrief, Persona, ScenarioConfig, TraceEvent…
├── scripts/                   ← CLI entrypoints (phase 0/1: concepts run brief.yaml)
├── tests/                     ← unit + golden-run regression (seeded)
└── notebooks/                 ← analysis/verification notebooks
```

Python 3.12+, `uv`, no framework dependencies beyond: `pyarrow` (coreset), `networkx` + `leidenalg` (graph/segments), `openai` pkg (OpenAI-compatible router client — works against OpenRouter, LiteLLM, vLLM, and most managed gateways), optional `boto3` (direct-Bedrock adapter for batch/embeddings), `cmaes` (search v2), `pydantic` (schemas). SQLite for env state and traces until scale demands otherwise.

---

## 2. Module inventory

Legend: **SRC** = salvaged source · phase = when the module lands (spec §7).

| # | Module | Layer | Source | Phase | One-line purpose |
|---|---|---|---|---|---|
| M1 | `schemas/` | cross | NEW | 0 | Pydantic contracts: ProductBrief, Persona, Exposure, Reaction, TraceEvent, ScenarioConfig, ReportFinding |
| M2 | `brief/` | L1 | NEW | 1 | Brief intake, provenance tagging, assumption ledger, category ontology |
| M3 | `coreset/loader` | L2 | **MatrAIx** | 0 | Packed-4-bit decode, postings-index segment filter, shard reader |
| M4 | `coreset/sampling` | L2 | **MatrAIx** + NEW | 0 | Segment→row-id resolution, cohort assembly, distribution gates (χ²/KS vs calibration_targets.json) |
| M5 | `personas/projection` | L2 | NEW | 0 | 1,290-attr → Persona record; sparse-completion policy w/ `synthesized` tagging |
| M6 | `personas/graph` | L2 | NEW + Leiden paper | 2 | Social graph attach (tie strength), Leiden segmentation, segment cards. **Bridges the MatrAIx gap:** the dataset has no follower/following edges (population sample, not a network) — the graph is *generated* (seeded topology, category-fitted degree/clustering params) and injected into OASIS's agent_graph as connection input; twhin-mode follower counts = generated degree centralities. "Interests" are likewise not a field: OASIS's interest-match embeds profile text — we embed the decoded attribute profile (~656 attrs avg); sparse decision-relevant gaps go through the completion policy, tagged `synthesized` |
| M7 | `llm/router` | cross | NEW + **MatrAIx model_client** | 0 | Provider-agnostic Tier A/B + judge + embeddings via OpenAI-compatible router; retries, token accounting, model pinning, per-role provider routing, fake mode |
| M8 | `cognition/agent` | L3 | **OASIS** agent + **MatrAIx** persona templates | 1 | Persona-conditioned agent turn: perceive → retrieve memory → Tier A/B → Reaction |
| M9 | `cognition/ssr` | L3 | **SSR paper** | 0 | Textual elicitation → router embedding → anchor cosine → Likert pmf (≥6 reference sets) |
| M10 | `cognition/memory` | L3 | **Generative Agents** paper | 2 | Memory stream (recency×importance×relevance), reflections, belief dimensions |
| M11 | `cognition/skills` | L3 | **VOYAGER** paper | 3+ | Reaction-pattern library (trigger→response, embedding-keyed); post-MVP |
| M12 | `world/env` | L4 | **OASIS** | 1 | PettingZoo-style env server, action spaces, SQLite platform state |
| M13 | `world/platforms` | L4 | **OASIS** | 2 | One `ForumPlatform` class, presets: `reddit_global` (OASIS salvage: global posting, hot-score herding) and `community_scoped` (threads = Leiden communities, recency + consensus ranking, slow hardening — mechanically similar to Reddit, dynamically distinct). Plus SurveyRoom, WOM (graph channels), SocialFeed (X-like), RetailShelf |
| M14 | `world/recsys` | L4 | **OASIS** | 2 | Info filter: hot-score (verbatim math), interest-match via router embeddings, exposure budgets |
| M15 | `world/schedule` | L4 | **OASIS clock** + pandemic-ABM paper | 2 | Activation probabilities + intervention schedules (teaser/launch/promo/competitor/shock) |
| M16 | `execution/scheduler` | L5 | NEW | 1 | RunConfig expansion: variants × seeds × cohorts → world run plan |
| M17 | `execution/costs` | L5 | NEW + **MatrAIx usage** | 1 | Budget governor, per-tier spend ledger, degradation paths |
| M18 | `execution/cache` | L5 | NEW | 1 | Prompt-hash response cache, embedding cache, coreset decode cache |
| M19 | `trace/store` | cross | NEW + **OASIS db shape** | 1 | Append-only TraceEvents + run registry (config hash, seeds, model pins, cost) |
| M20 | `search/rollout` | L6 | **ASAL** | 3 | Candidate θ → surrogate world run → outcome digest |
| M21 | `search/opt` | L6 | **ASAL main_opt** | 3 | Supervised target search: v1 LLM-proposer + grid; v2 CMA-ES |
| M22 | `search/illuminate` | L6 | **ASAL main_illuminate** | 3 | MAP-Elites-style archive on adoption×polarization; embedding dedupe |
| M23 | `search/judge` | L6 | NEW (LLM-as-judge v1) | 3 | Rubric scoring (target/novelty/diversity/dynamics) with cited evidence; agreement checks |
| M24 | `validation/bench` | L7 | NEW + **SSR paper metrics** | 4 | KS similarity, correlation attainment, supervised baseline (LightGBM) |
| M25 | `validation/calibrate` | L7 | NEW + **MatrAIx self-report** | 4 | Persona-patch loop with held-out gates, anchor versioning, trust-tier transitions |
| M26 | `reporting/analysts` | L8 | **TradingAgents paper** | **4+ (deferred — not in v1)** | Segment/competitor/risk analysts + bull/bear debate over traces. v1 duty (finding authorship + citation resolution) absorbed by M27 |
| M27 | `reporting/build` | L8 | NEW | 1 | Report renderer: rankings, segment cards, objections, trust labels, validation plan |
| M28 | `scripts/` CLI | — | NEW | 0+ | `coreset-gate`, `ssr-replica`, `concepts run`, `sweep run`, `benchmark run` |

---

## 3. Module specs — detailed (every module: what it does, how, inputs, outputs)

Notation: **In →** / **Out →** are the typed structures at the module boundary (all defined in M1 unless marked local). Every module writes to the trace store and carries provenance fields per §5 contracts.

---

### M1 — `schemas/` (NEW · Phase 0) — the contracts

**Does:** single source of truth for every structure crossing a module boundary. Pure pydantic v2, zero logic, strict extra-field rejection. Everything below references these types.

**How:** one file per domain; enums for every closed set; validators enforce invariants (pmf sums to 1, provenance always present, seeds always set). Frozen where immutable.

**Core definitions (abridged):**

```python
class Provenance(StrEnum): USER="user"; PUBLIC="public"; SYNTHESIZED="synthesized"; CALIBRATED="calibrated"
class Tier(StrEnum): EXPLORATORY="exploratory"; CATEGORY="category"; CUSTOMER="customer"; PROSPECTIVE="prospective"
class TraceType(StrEnum): EXPOSURE|REACTION|SSR|BELIEF|REFLECTION|SOCIAL|CONVERSATION|PURCHASE|ENV_UPDATE|JUDGE|COST

class Claim(BaseModel):   id:str; text:str; provenance:Provenance; evidence_ref:str|None
class ProductBrief(BaseModel):
    product: ProductInfo                    # name, category, concept_text, concept_images[]
    claims: list[Claim]                     # ≥1; ids auto-assigned C1..Cn
    price: Price                            # point: float, currency, strategy: premium|mass|promo
    competitors: list[Competitor]           # name, price, claims
    target_market: TargetMarket             # geography, segment_filters: dict[attr_id, value]
    assumptions: list[Assumption]           # text + Provenance
    decision_question: str; study_type: Literal["concept","message","pricing","risk","launch"]

class Persona(BaseModel):
    id: str; matraix_row_id: str; source: str           # wiki|amazon|gss|prism|stackoverflow|survey|synthetic
    grounding: dict[str, GroundingEntry]                # per-field evidence + confidence (from coreset)
    provenance_patch: dict[str, Provenance]             # completed fields → SYNTHESIZED
    attributes: dict[str, str]                          # projected subset (ontology-selected)
    economics: Economics | None; media: Media | None    # present only if completed/priors
    beliefs_baseline: Beliefs                           # {claim, price, fit} priors
    profile_embedding: list[float]                      # for interest-match & tie strength

class Exposure(BaseModel):  tick:int; persona_id:str; stimulus_id:str; channel:Literal["survey","feed","forum","wom","shelf"]; attention:float; seen:bool; reason:Literal["interest","social_proof","random","wom","forum"]
class Reaction(BaseModel):  tick:int; persona_id:str; stimulus_id:str; free_text:str; pi_pmf:PMF5; action:ActionType; belief_deltas:dict[str,float]; tier:Literal["A","B"]

class TraceEvent(BaseModel):
    run_id:str; world_id:str; t:int; seq:int
    type:TraceType; persona_id:str|None
    payload:dict                                        # typed per TraceType (schema-validated by discriminator)
    model_id:str|None; prompt_template:str|None; prompt_hash:str|None; seed:int

class ScenarioConfig(BaseModel):                        # one θ
    variant_id:str; concept:ConceptCard; price:float
    claims_emphasis:list[str]; audience_mix:dict[str,float]      # seg_id → weight
    channel_plan:list[Literal["survey","wom","feed","forum","shelf"]]
    interventions:list[Intervention]                    # {tick, kind: teaser|launch|promo|influencer|competitor_move|shock, payload}
    recsys_mode:Literal["twitter","twhin","reddit_hot","random"]
    world_seed:int

class RunConfig(BaseModel):
    study_id:str; variants:list[ScenarioConfig]; seeds:list[int]
    cohort:CohortManifest; budget:Budget                # {usd_cap, tier_caps}
    model_pins:ModelPins; template_versions:dict[str,str]

class OutcomeDigest(BaseModel):
    run_id:str; world_id:str
    adoption:float                                      # share-weighted mean PI
    polarization:float                                  # size-weighted JSD across segment PMFs
    seg_pmfs:dict[str,PMF5]; adoption_curve:list[tuple[int,float]]
    objections:list[ObjectionCluster]                   # {label, mentions, severity, segments, verbatims[]}
    verbatims:list[str]; anomalies:list[Anomaly]        # {tick, kind: herding|backlash|flop, evidence}

class ReportFinding(BaseModel):
    kind:Literal["ranking","objection","segment","risk","recommendation"]
    statement:str; evidence_trace_ids:list[str]
    provenance:Provenance; trust_tier:Tier; confidence:float
    disconfirming_test:str
```

**Validators:** `PMF5` → all values > 0, Σ ∈ [0.999, 1.001]; `Provenance` mandatory on every claim/field-level structure; `RunConfig` refuses un-pinned model IDs.

**In →** nothing (definitions). **Out →** the types above, imported everywhere.

---

### M2 — `brief/` (NEW · Phase 1) — intake & ontology

**Does:** parse the user-authored brief into validated structures; build the category ontology (which attributes/fields matter for this category, which persona fields render into prompts, what stimulus types exist); maintain the assumption ledger.

**How:**
1. `yaml.safe_load` → `ProductBrief.model_validate` (strict: unknown keys rejected; claim IDs auto-assigned C1..Cn; URLs in evidence refs fetched and hashed at ingest).
2. Category ontology: versioned JSON per category — `attr_relevance` (which coreset attribute IDs feed the persona block, ranked), `stimulus_types`, `anchor_set_ref`, `completion_policy` (which Persona fields may be synthesized). Generated once by a Tier-B assisted draft + human review; extended per category, never per study.
3. Assumption ledger: every brief assumption becomes a first-class record surfaced in all reports.

**In →** `brief.yaml` (product, claims, price, competitors, target_market, assumptions, decision_question, study_type)
**Out →** `BriefPack {brief: ProductBrief, ontology: CategoryOntology, ledger: AssumptionLedger, brief_hash: sha256}` — `brief_hash` pins the brief into every downstream registry entry.

**Gotcha:** claims are the atomic stimuli units — platform posts, feed cards, and judge rubrics reference `Claim.id`, so re-ordering claims mid-study invalidates comparability (hash catches it).

---

### M3 — `coreset/loader` (MatrAIx COPY · Phase 0) — packed dataset decode

**Does:** local mirror + vectorized decode of the packed Persona-1M dataset; the only module that touches raw shards.

**How:**
1. Pre-download 10 Zstd parquet shards (4.17 GB) to `.cache/coreset/` (SHA-256 verified vs `manifest.json`).
2. `pyarrow.parquet.read_table(..., memory_map=True)` per shard.
3. Vectorized nibble decode (the fast path): attributes is a 645-byte packed column → `np.uint8` array; even-index fields = low nibble (`arr[::2] & 0x0F`), odd = high (`arr[1::2] >> 4`); gather values via schema codebook lookup tables (`np.array(col["values"])` as mapping arrays); apply null-bitmask (bit set = missing, LSB-first) via bit ops; overlay `attribute_overrides` for out-of-codebook values.
4. Grounding columns (`source`, `grounding`, `populated_attribute_count`) pass through untouched.
5. Decoded shards cached as Arrow tables keyed by shard SHA; LRU in-process.

**In →** `row_id: int` | `attr_filters: dict[attribute_id, value]`
**Out →** `DecodedRow {attributes: dict[fid, str], null_fields: list[fid], overrides_applied: list[fid], source: str, grounding: dict}` | filter mode: `np.ndarray` of candidate row ids.

**Perf gate:** decode 10k personas < 60 s cold, < 2 s warm (Phase-0 acceptance). Postings filter must not open data shards (index-only).

---

### M4 — `coreset/sampling` (MatrAIx + NEW · Phase 0) — cohort assembly + gates

**Does:** translate the brief's target segment into row-id sets, sample a stratified cohort, and gate its distributions against both the brief and the dataset's own calibration targets.

**How:**
1. `resolve_filter`: intersect postings sets per filter key (value → row-id list) — index-only, no shard scan.
2. Stratified sample: `np.random.Generator(seed)`; strata from brief segment proportions (or calibration targets when sampling general population); shortfall policy = widen filters (log degradation) — never silently drop.
3. Gates: categorical marginals → χ² goodness-of-fit vs target (p > 0.05 pass); continuous proxies → KS (≥ 0.80 pass); per-gate status pass/warn/fail; any fail = cohort rejected (never soft-pedaled).

**In →** `ProductBrief.target_market`, `n: int`, `seed: int`, `calibration_targets.json`
**Out →** `CohortManifest {cohort_id, row_ids: list[int], n, strata: dict, provenance_mix: dict, graph_seed: int, cohort_hash: sha256}` + `GateReport {attribute: {target, achieved, chi2_p, ks, status}}` — manifest hash pins the cohort into RunConfig (replayability).

---

### M5 — `personas/projection` (NEW · Phase 0) — Persona build + sparse completion

**Does:** decoded coreset rows → engine `Persona` records; executes the sparse-completion policy; computes profile embeddings.

**How:**
1. Projection: ontology `attr_relevance` selects which of the 1,290 fields map onto Persona fields (demographics, psychographics, category_behavior, media); 1:1 field mapping config, versioned.
2. Sparse completion: for fields in the policy's completable set AND missing → batched Tier-B structured calls (one call per ~25 personas of the same segment: fewer calls, consistent tone); outputs validated against field schemas; written to `provenance_patch[field] = SYNTHESIZED`. Policy defaults: economics/decision-rules/media completable; demographics/psychographics never.
3. Profile embedding: mean-pool router-EMBED vectors of the attribute text (the interest vector used by M14 interest-match and M6 tie strength).
4. Completion cache keyed by `(row_id, policy_version)`.

**In →** decoded rows (M3), ontology completion policy (M2), router (M7)
**Out →** `list[Persona]` + `CompletionLog {persona_id, field, applied: bool, tokens, cost}` — synthesized fields are visibly tagged end-to-end (invariant: grounded ≠ synthesized).

---

### M6 — `personas/graph` (NEW + Leiden paper · Phase 2) — graph generation & segmentation

**Does:** generate the social graph the dataset lacks; compute tie strengths; run Leiden; emit segment cards.

**How:**
1. `GraphSpec {n, category, seed, source: category_default|customer_referral|calibrated}` → parameter profile: `mean_degree_strong` (5–8), `mean_degree_weak` (40–80), `clustering_coef` (0.25–0.4), `power_law_exp` (2.1–2.5), `homophily` (0.55–0.7), `assortativity` (~0). `customer_referral` graphs → parameters *estimated* (degree MLE, transitivity, assortativity), `source="calibrated"`.
2. Two-layer topology (no single model gives clustering *and* hubs): Watts–Strogatz ring (k=strong-degree, rewire p tuned to `clustering_coef`) → preferential attachment (m tuned to tail exponent) → merge (strong edges flagged, 2× tie prior) → homophily rewiring pass (rewire weak edges within pre-Leiden attribute clusters at rate `homophily`). Seeded numpy Generator — bit-identical per seed.
3. Tie strength: `w = 0.45×cos(profile_emb_u, profile_emb_v) + 0.35×homophily(u,v) + 0.20×strong_flag` (embeddings from the pinned router model). Fixed at cohort build; weights may shift with interaction history during a run; topology never changes mid-study.
4. Leiden (`leidenalg`) over the weighted graph at resolution sweep γ ∈ {0.3, 0.5, 1.0}; select by modularity (≥0.4) + report practicality (4–8 segments, min ~80 personas). Partition hash → CohortManifest. Segment cards: Tier-B LLM names each community from its aggregated attribute profile (human-reviewable, versioned).

**In →** `CohortManifest`, personas (M5), embedder (M7), `GraphSpec`
**Out →** `SocialGraph {adjacency: dict[id, list[(peer_id, weight, strong)]]}, Segments {community_id → {member_ids, card, modularity}}, GraphHash`

**Gates:** degree KS vs power-law target; clustering ±0.05 of target; giant component ≥ 98%; no isolated nodes (isolates get one weak edge). **Why generated:** real follower graphs are unavailable per-cohort, not segment-matched, unauditable; generation makes hubness a controlled study variable.

---

### M7 — `llm/router` (NEW + MatrAIx model_client COPY · Phase 0) — provider-agnostic inference

**Does:** every model call in the engine flows through here, routed by role; token accounting, pinning, retries, caching hooks, fake mode.

**How (request lifecycle):**
1. `converse(role, messages, temp, max_tokens, template_id)` → resolve role→model from `ModelPins` (fail if unpinned).
2. Coalesce identical in-flight requests (50 ms window) → cache check (M18) → dispatch via OpenAI-compatible transport (OpenRouter/LiteLLM/vLLM all speak it) → optional `bedrock_direct` adapter for Batch/Native-embedding routes.
3. Retry: exponential backoff ×3, provider-aware (429/5xx); fallback route per role (e.g. tier_b: openrouter → direct provider) on repeated failure.
4. On completion: `Completion {text, tokens_in, tokens_out, cost_usd, provider, model_id, latency_ms, cache_hit}`; emit COST TraceEvent → M17; emit `(provider, model_id, template_id, prompt_hash)` → M19.
5. `embed(texts)` → pinned EMBED model, batched, cached.
6. Fake mode: deterministic canned completions keyed by `prompt_hash` — CI parity with mockups.

**In →** role, messages (from M8 context assembly), pins
**Out →** `Completion` / `list[embedding]` + COST events. Judge calls = Tier-B, temp 0, JSON schema enforced, cited-evidence requirement (M23).

---

### M8 — `cognition/agent` (OASIS agent shape + MatrAIx templates · Phase 1) — the persona turn

**Does:** one agent's reaction to one stimulus — the unit of simulation.

**How:**
1. Tier routing by event class: `{first_seen, conversation, reflection, purchase, claim_audit}` → **B**; everything else → **A**. Routing table is config, not code.
2. `react()`: `ctx = ContextBuilder.build(agent, stimulus, world_state, tier)` (M8/M10 section below) → `completion = router.converse(tier, ctx.messages, ...)` → parse per task type (SSR free text / comment text / purchase decision JSON) → SSR applied when the task asks PI (M9) → belief deltas applied (from template tone or parsed deltas) → `Reaction` emitted → M19 trace + `env.observe_action`.
3. Guardrails enforced at parse time: if free_text references a stimulus not in ctx → rejected, retried once with stricter instruction, then logged as violation (never silently kept).

**In →** `stimulus: Exposure`, `world_state` (read-only view), agent template + per-world state (M10)
**Out →** `Reaction {tick, persona_id, stimulus_id, free_text, pi_pmf, action, belief_deltas, tier}`

---

### M9 — `cognition/ssr` (SSR paper · Phase 0) — quantitative elicitation

**Does:** converts free-text intent into a Likert-5 probability mass — the engine's quantitative ground truth. Numeric elicitation is forbidden (paper 1's collapse signature).

**How:**
1. Anchor sets: per (construct, category), versioned JSON — `{construct, likert_map, reference_sets: R×5 statements, embeddings: R×5×dim}`; R ≥ 6 sets, Tier-B drafted, human-reviewed, embedded once with the pinned EMBED model (anchors and responses must share the model — mismatch invalidates the pmf).
2. `ssr_score(free_text)`: embed text once → per reference set: `softmax(cosine(v, anchor_i)/τ)` over 5 anchors → average R sets → `PMF5`. τ calibrated on held-out human data in Phase 4.
3. The free text is retained (objection mining corpus); the pmf is the number.
4. Elicitation prompt template: "respond in one short paragraph: how likely would you be to purchase? do not use numbers" + persona context (M8). Unconditioned personas rejected at the gate (paper 1: unconditioned → optimistic narrow distributions, ρ falls to ~50%).

**In →** `free_text: str`, `anchors: AnchorSet`, `embedder: ModelRouter`
**Out →** `pi_pmf: PMF5` + `per_set_pmfs` (diagnostics) — acceptance: distribution non-collapse, conditioning signature reproduced, rank stability Spearman > 0.8 across reference sets.

---

### M10 — `cognition/memory` (Generative Agents · Phase 2) — episodic + semantic memory

**Does:** per-agent event log, scored retrieval, reflections that compress episodes into beliefs.

**How:**
1. Episodic: `events(agent_id, tick, type, text, importance, emb)` in world `state.db`; appended on every exposure/reaction/conversation; capped per agent.
2. Retrieval: `score = exp(-Δtick/τ_r) × importance × cosine(emb_event, emb_stimulus)`; top-k per tier budget (A: 3, B: 8). τ_r ≈ horizon/4.
3. Reflection trigger: every ~6 ticks OR `|Δbelief| > 0.3` surprise. Tier-B call: recent episodes → new belief values + reflection sentence; belief deltas written (delta-encoded to beliefs.parquet); the reflection itself becomes a high-importance episodic event.
4. Beliefs: `{claim: float, price: float, fit: float, ...}` per agent per world — the semantic tier, read directly by Tier-A context (no retrieval cost).

**In →** agent state, stimulus embedding, router (Tier-B for reflections)
**Out →** `MemoryView {items: list[Event], beliefs: Beliefs, token_count: int}`; belief deltas → Reaction; reflections → TraceEvent(BELIEF/REFLECTION).

---

### M11 — `cognition/skills` (VOYAGER pattern · Phase 3+) — reaction patterns

**Does:** reusable (trigger → response) patterns so consistent persona archetypes don't need re-derivation each turn.

**How:** library table `{pattern_id, trigger_embedding, response_template, segment_applicability, success_stats}`; on turn: `cosine(trigger_embedding, ctx_emb) > τ` → template injected as an optional "known reaction" hint (token-budgeted). Mining: post-run extraction of recurring (context → reaction) pairs from traces; new patterns embedded and inserted; success stats updated from downstream PI movement.

**In →** context embedding, library table. **Out →** optional skill hints (list of template strings) — consumed by M8 prompt assembly.

---

### M12 — `world/env` (OASIS COPY/ADAPT · Phase 1) — world orchestration

**Does:** the PettingZoo-style step loop that ties platforms, filter, clock, and agents together. Fork of `oasis/environment/env.py` with CAMEL stripped, M7 injected.

**How:** `reset(RunConfig)` instantiates platforms (M13), info filter (M14), clock (M15), agents from cohort (M8) with per-world state; `step(tick, actions)`: apply actions to platforms → platform state updates (SQLite) → compute next-tick stimuli → return `WorldDelta`. Deterministic under (config, seeds); straggler-aware (worlds of different variants finish at different ticks — world-day = max over live worlds).

**In →** `RunConfig`, per-tick `dict[Agent, Action]`. **Out →** `WorldDelta {new_posts, state_updates, stimuli_for_next_tick}`.

---

### M13 — `world/platforms` (OASIS COPY/ADAPT · Phase 2) — the five environments

Each platform = action handlers + an exposure source; all state in the world SQLite DB with provenance columns.

| Platform | Mechanics | Actions |
|---|---|---|
| **SurveyRoom** (P1) | isolated: every sampled persona receives the stimulus, no social signals; the calibration-baseline environment | answer (SSR always applied) |
| **SocialFeed** (P2, X-like) | broadcast posts, comments, likes/reposts/quotes; exposure via M14 rec_matrix; social-proof counters | post, comment, like, repost, quote, follow |
| **ForumPlatform** (P2) — one class, two presets | `reddit_global`: any agent, any thread, hot-score ranking (OASIS verbatim) · `community_scoped`: threads = Leiden communities, membership enforced, recency + consensus ranking (reply recency + agreement ratio), no hot-score | create_post, reply, vote |
| **WOM** (P2) | graph channel, not a platform: after a reaction, `wants_to_talk(reaction, peer)` gate (sentiment strength > θ_s AND tie > θ_t, rng) → `deliver(peer, message)` creates next-tick Exposure(reason="wom", tie) | send (implicit) |
| **RetailShelf** (P4) | comparison-page stimulus: competitor prices, reviews written by other agents; buy/reject decisions; review reading = social proof ingestion | view, review_read, buy, reject |

**In →** per-tick actions, intervention stimuli (M15). **Out →** `WorldDelta` + next-tick candidate stimuli + provenance-tagged rows (persona row id, stimulus id, claim ids).

---

### M14 — `world/recsys` (OASIS COPY/ADAPT · Phase 2) — info filter

**Does:** decides which stimuli each activated agent sees — the engine's attention economy. Salvages all four OASIS modes; embedder branches swapped to the router.

**How (modes, from OASIS `recsys.py`):**
- `random` — uniform sample; **kept as the control arm** (isolates filter-driven vs organic outcomes).
- `reddit_hot` — hot-score **copied verbatim**: engagement counts with time decay; drives herding.
- `twitter` — interest-match: cosine(profile_embedding (M5), post_embedding) ranking.
- `twhin` — personalized graph-aware: follower-graph signals (generated degrees, M6) + posting history + like-scores.
Exposure budget: max E stimuli per agent per tick (default 3); beyond budget, lowest-scored dropped with reason logged. Post embeddings computed at creation (cached); user profile embeddings cached per cohort.

**In →** activated agents, platform stimulus tables, mode + params (from ScenarioConfig). **Out →** `list[Exposure]` (with reason + attention scores) → M8.

---

### M15 — `world/schedule` (OASIS clock + pandemic-ABM · Phase 2) — time & interventions

**How:**
1. Activation clock (fork of `oasis/clock/clock.py`): per-agent `p_act(tick)` = involvement × daily-rhythm profile; seeded sampling; activation counts feed the cost governor.
2. Intervention scheduler: `interventions` from ScenarioConfig injected at tick start — each kind carries an adoption/decay model (promo: uplift with τ-decay; influencer: reach pulse; competitor_move: counter-stimulus targeting; shock: negative review injection). Pandemic-ABM paper's intervention-interplay semantics: interventions compose, they don't overwrite.

**In →** ScenarioConfig.interventions, cohort activation profiles. **Out →** per-tick stimuli + activated agent list.

---

### M16 — `execution/scheduler` (NEW · Phase 1) — run orchestration

**Does:** RunConfig → world jobs → workers → finalized outputs.

**How:**
1. Expand: variants × seeds → world jobs (each: ScenarioConfig + cohort + world_seed).
2. Execute: asyncio worker per world (OASIS async env), 2 workers default; per-tick checkpoint (flush state.db + event batch).
3. Crash recovery: resume from checkpoint (registry knows last complete tick).
4. Finalize: export Parquet partitions (events/beliefs/edges), compute OutcomeDigest per world, write registry entry, update exports matrix.

**In →** `RunConfig`. **Out →** `list[OutcomeDigest]` + registry entries + `exports/{study_id}` rows + cost report.

---

### M17 — `execution/costs` (NEW + MatrAIx usage · Phase 1) — budget governor

**Does:** enforce budgets with degradation, never hard failure.

**How:** `CostGovernor.consume(cost_event)` from M7 → running totals per tier/world/study. Thresholds: 80% warn → 95% strict (freeze nonessential Tier-B: reflections, optional audits) → 100% degrade ladder: (1) freeze optional Tier-B, (2) activation subsample 0.62→0.40, (3) pause run (completed worlds kept — partial results are valid, labeled). Ledger persisted to registry (per-world, per-tier, per-provider).

**In →** COST TraceEvents from M7. **Out →** `{decision: allow|degrade(level)|halt, level}`; ledger queryable per run.

---

### M18 — `execution/cache` (NEW · Phase 1)

**Does:** dedupe identical inference/embedding work.

**How:** keys — chat: `sha256(provider, model_id, template_id, messages, temp)`; embed: `sha256(EMBED_model, text)`. Stores: per-run SQLite + in-process LRU. Invalidation: never within a run (pins are immutable); cross-run reuse only when model_id + template_version match. SSR anchor embeddings cached per anchor version. Hit-rate surfaced in run stats (Phase-1 gate: cache hit ≥ 30% on baseline reruns).

**In →** router lookup requests. **Out →** cached `Completion`/embedding + `cache_hit` flag.

---

### M19 — `trace/store` (NEW + OASIS db shape · Phase 1) — the audit spine

**Does:** append-only TraceEvents + run registry; the store every other module reads for explanation, and the calibration corpus.

**How/layout:**

```
trace/
├── registry.db            run_id → (config_hash, seeds, model_pins, template_hashes, cost, status)
├── world/{run_id}/        per-world partition (SQLite live → Parquet at completion)
│   ├── events.parquet     TraceEvents sorted by (agent_id, tick)
│   ├── beliefs.parquet    belief snapshots, delta-encoded per reflection
│   ├── edges.parquet      interaction graph (u, v, channel, count, last_tick)
│   └── state.db           live platform state during the run
└── exports/{study_id}/    cross-run matrix: one row per (matraix_row_id, run_id, variant, seed)
```

Sizing: 2k agents × 30 ticks ≈ 500k events/world ≈ 100–200 MB Parquet; verbose payloads (Tier-B verbatims) ≈ 7% of events. Context is never stored whole — parts + prompt hash only, history re-derivable from registry pins.

**In →** TraceEvents from all modules. **Out →** trace queries (M27's v1 builder reads via prebuilt views; analyst agents consume them in Phase 4+), registry entries, export tables.

---

### M20 — `search/rollout` (ASAL pattern · Phase 3) — candidate → digest

**Does:** one θ in, one measured outcome out — the unit of search.

**How:** surrogate cohort = stratified 200 from CohortManifest (sparse rows completed per policy); 3 world-seeds ensemble; reduced ticks (config, default 10) — mirroring `mockups/sim.js MiniAtlasSweep` (the reference implementation). Digest builder: adoption = share-weighted mean PI; polarization = size-weighted JSD across segment PMFs; objections = quick clustering of Tier-B verbatims; anomalies = tick-level PI jumps > 2σ.

**In →** `ScenarioConfig` (θ), surrogate cohort. **Out →** `OutcomeDigest` (+ per-seed adoption list for σ).

---

### M21 — `search/opt` (ASAL main_opt · Phase 3) — proposers & optimizers

**Does:** generate the next θ candidates.

**How:** v1 — LLM-proposer: prompt = archive summary (cells, configs, outcomes, empty cells) + search objective → JSON proposals (mutate existing configs / new), plus grid over discrete dims; v2 — `cmaes` over continuous dims (price, audience-mix ratios) with discrete dims fixed per CMA tier. Proposal validation: θ schema-checked, constraint-checked (price bounds, channel constraints from brief).

**In →** search space def, archive state, objective. **Out →** `list[ScenarioConfig]` candidates.

---

### M22 — `search/illuminate` (ASAL main_illuminate · Phase 3) — the atlas

**Does:** MAP-Elites-style archive over measured outcome space — filled cell = a distinct reachable market world.

**How:** 6×6 bins on (adoption, polarization) — both *measured* from digests (polarization = size-weighted JSD between segment PMFs, scaled 0–1). Insert if cell empty or fitness better; fitness = `2×adoption − 0.5×polarization − 0.4×risk`. Dedupe: cosine(flat segment PMFs) > 0.995 → same world id (semantic, not numeric diversity). Termination: budget or coverage plateau. Labels per cell: robust winner (adoption > 3.7 ∧ pol < 0.45), backlash (risk ∧ pol > 0.5), quiet flop (adoption < 2.9 ∧ pol < 0.4), split market (pol > 0.55 ∧ adoption > 3.2), niche. Wedge = highest-adoption contested world → human review, never auto-crowned. Reference implementation: `MiniAtlasSweep` in `mockups/sim.js`.

**In →** search space, budget, judge (M23). **Out →** `Atlas {cells, worlds, wedge, winners, failures}` + archived (θ, digest, trace) tuples.

---

### M23 — `search/judge` (NEW v1 · Phase 3) — LLM-as-judge

**Does:** scores runs where ASAL would use CLIP — text outcomes need a text judge.

**How:** outcome digest → structured JSON verdicts, each with cited evidence (digest line refs): `target_alignment` (0–1 vs target prompt), `novelty_late` (0–1, late-tick novelty), `pairwise_diversity` (vs archive members), `emergent_dynamics` (backlash|herd|hijack|polarization|none + rationale). Judge model pinned (temp 0); agreement: two calls (different seeds/models) within 0.15 → accept, else human review; calibration: judge scores checked against real outcomes once available — ranking worse than random ⇒ freeze v1, ship v2 embeddings (§3.7 of spec).

**In →** OutcomeDigest (+ archive context). **Out →** `JudgeVerdict {scores, evidence_refs, model_id, prompt_hash}`.

---

### M24 — `validation/bench` (SSR paper metrics · Phase 4) — benchmarks

**Does:** synthetic-vs-human benchmark in the paper-1 grammar; the trust-tier referee.

**How:**
1. Inputs: human study export (concept_id, n, pmf5, mean, rank — CSV/JSON with provenance) + matching synthetic runs (blind: predictions registered before outcome load).
2. Metrics: per concept `KS_sim = 1 − KS(pmf_human, pmf_syn)`; rank attainment `ρ = pearson(rank_syn, rank_human) / pearson(split-half human)` (test–retest ceiling); supervised baseline: LightGBM trained on half the human features → predict held-out (if it beats zero-shot SSR, per-category training becomes mandatory).
3. Output grades tier transitions; bias audit: per-segment signed bias table with mitigation policy.

**In →** human exports + synthetic digests. **Out →** `BenchmarkReport {per-concept rows, KS, ρ_attainment, baseline comparison, bias table, tier recommendation}` → registry.

---

### M25 — `validation/calibrate` (MatrAIx self-report pattern · Phase 4) — calibration loop

**Does:** turns human data into gated persona/anchor improvements — trust as a maintained feature.

**How:**
1. Patch mining: verbatims + cluster stats → Tier-B proposes persona patches (JSON: {target_segment, field, operation, evidence_refs}).
2. Gate: simulate held-out study with/without patch → accept iff ΔKS > +0.005; accepted patches versioned, applied to *future cohorts only*, logged with evidence; rejected patches retained as negative evidence.
3. Anchor updates: same gate on anchor-set changes.
4. Tier ladder: exploratory → category → customer → prospective; each transition requires its metric gate; **revocation** supported (later benchmark below floor ⇒ tier downgraded).

**In →** human studies (M24 inputs), current patches, anchor versions. **Out →** `PatchSet {accepted[], rejected[], evidence}`, new anchor versions, tier transitions → registry.

---

### M26 — `reporting/analysts` (TradingAgents pattern · **DEFERRED — Phase 4+ upgrade, not in v1**)

**v1 decision:** cut from the initial build. The v1 citation duty moves into M27: the report builder itself authors findings from prebuilt trace views (deterministic extraction of objection clusters, belief-delta chains, WOM paths) and resolves every claim to trace IDs before rendering — the trust invariant is enforced without the debate layer.

**Why it stays on the roadmap (not deleted):** the analyst debate earns its cost only once reports are trusted enough that *mechanistic explanation quality* is the bottleneck — (1) risk chains that averages hide ("the claim is the liability, not the product") need trace-reading agents to construct; (2) the bear role counters same-model-family self-consistency bias; (3) visible bull/bear disagreement communicates uncertainty better than a clean verdict. Revisit after Phase-4 calibration proves trust; the A/B is cheap (reports with vs without the analyst section, measure decision-usefulness).

**Spec (when built):**
- Roles: segment analyst, competitor analyst (counterfactual worlds), risk analyst — each gets prebuilt trace views + digest; cheap models for reading, frontier for synthesis.
- Debate: bull → bear (must cite risk-register evidence) → synthesis; every authored claim carries trace-ID citations, validated before M27 rendering.
- **In →** trace views, OutcomeDigest, risk register. **Out →** `list[ReportFinding]` (validated) + debate transcript (abridged into report).

---

### M27 — `reporting/build` (NEW · Phase 1) — the report renderer

**Does:** digests + trace views → the report object (rankings, segment cards, objection clusters, risk register, scenario atlas, validation plan, method disclosure). **In v1 it also authors the findings** (M26 deferred): deterministic extraction from prebuilt trace views — objection clusters from verbatim embeddings, belief-delta chains from beliefs.parquet, WOM paths from edges.parquet — with every claim resolved to trace IDs by the builder itself.

**How:** template-versioned renderer; **trust guard at the door**: refuses any finding missing trust_tier/provenance/evidence IDs; refuses quantitative claims without trace resolution (author-then-validate in one pass); emits both markdown (human) and JSON (UI/mockups parity). Always ends with the recommended real-world validation section (invariant: nothing auto-crowned). Risk register is populated from L6 anomalies + judge verdicts (deterministic), not from a debate.

**In →** `list[OutcomeDigest]`, trace views (events/beliefs/edges parquet), benchmark/calibration state (M24/M25). **Out →** `Report {sections, findings, trust_statement, method_disclosure}` (md + json), report registry entry.

---

### M28 — `scripts/` CLI (NEW · all phases) — entrypoints

| Command | Modules | Phase-0/1 signature |
|---|---|---|
| `coreset-gate` | M3, M4 | `coreset-gate --brief brief.yaml --n 1500 --seed 4021` → GateReport + cohort manifest |
| `ssr-replica` | M7, M9 | `ssr-replica --anchors PI-oralcare-v3 --cohort manifest.json` → distribution notebook |
| `concepts run` | M2, M16, M19, M27 | `concepts run brief.yaml` → report.md/json + run_id |
| `sweep run` | M20–M23 | `sweep run --space space.yaml --budget 42` → atlas.json |
| `benchmark run` | M24 | `benchmark run --human exports.csv --runs r1,r2` → BenchmarkReport |
| `calibrate` | M25 | `calibrate --patches queue.json` → PatchSet |

All commands print `run_id` and refuse to proceed past any failed gate (exit codes distinguish gate-failure from crash).

---

### Salvage cross-reference

Per-module source details live in `SALVAGE.md` (exact repo paths, verdicts, adaptation notes): M3/M4/M5 ← MatrAIx §3.1/3.4 · M7 ← MatrAIx §3.2 · M8 ← MatrAIx §3.3 + OASIS §1 · M12/M13/M14/M15/M19 ← OASIS §1 · M20–M22 ← ASAL §2 · M9/M10/M24 ← papers (no code exists — spec §2 recipes are the source). M26 deferred (see its section).


---

## 4. Inference layer (OSS / [OI]-compatible router) — call-site map
One router (M7) fronts every model call; roles route to different provider models by config:

| Role | Default route (swappable via config) | Call sites |
|---|---|---|
| Tier-B cognition | Claude / GPT / Gemini via **OpenRouter** or direct provider | M8 first impressions, conversations, reflections, purchases |
| Tier-A cognition | **Persona-8B**: OpenRouter-hosted, vLLM self-host, or Bedrock Custom Model Import — Phase-0 microbenchmark decides; Nova Micro / GPT-4o-mini fallback | M8 bulk ticks |
| SSR + info-filter embeddings | one pinned embedding model (OpenAI, Voyage, Bedrock Titan/Cohere — any, but **one** for anchors + responses + recsys) | M9, M14 |
| Judge | temp-0 JSON model with cited evidence, pinned per registry | M23 |
| Content safety | router-side moderation (OpenAI/Bedrock Guardrails) or LLM-based safety check | generated posts/comments before trace write |
| Batch | router provider batch APIs, or direct-Bedrock adapter for large sweeps/backtests | M20–M22, M24 |
| Telemetry | router usage payloads → M17 cost governor; per-provider spend tracked separately | all |

**Adapter shape:** `[OI]-compatible` chat endpoint is the primary interface (OpenRouter, LiteLLM proxy, vLLM, and most managed gateways all speak it). Two optional adapters: `bedrock_direct.py` (boto3 — for Batch Inference + Bedrock-native embeddings/guardrails when a route needs them) and `embeddings.py` (provider-specific embedding endpoints). Swapping providers = config change, zero call-site changes.

---

## 5. Cross-cutting contracts (from spec §5.4)

1. **No unprovenanced numbers** — every report claim → trace IDs + trust tier.
2. **Grounded ≠ synthesized** — coreset facts vs LLM-completed fields never mix silently.
3. **Replayability** — `run_id` + seeds + model pins + prompt-template hashes reproduce runs.
4. **Nothing auto-crowned** — winners/risks are hypotheses; the report ends in the next real-world test.

These are enforced in code: schemas carry the fields; `trace/` persists them; `reporting/build` refuses untrusted numbers.

---

## 6. Phase → module map (spec §7)

| Phase | Modules | Exit artifact |
|---|---|---|
| 0 (wks 1–2) | M1, M3, M4, M5, M7, M9, M28 | `coreset-gate` report + `ssr-replica` notebook (distributions realistic, persona-conditioning signature reproduced) |
| 1 (wks 3–6) | M2, M8, M12, M16, M17, M18, M19, M27 | `concepts run brief.yaml` → ranked report <30 min / <$20 |
| 2 (wks 7–12) | M6, M10, M13, M14, M15 | WOM/feed/forum world; herding event explainable via traces; seeds reproducible |
| 3 (wks 13–18) | M11, M20–M23 | Scenario atlas (≥30 distinct worlds), judge agreement ≥0.7 |
| 4 (wks 19–26) | M24, M25 | External human-study benchmark: KS ≥0.8, ρ ≥0.8 of ceiling; trust tiers enforced |
| 4+ upgrade | M26 (analyst debate) | Mechanistic-explanation quality A/B: reports with vs without analyst section |

---

## 7. Testing strategy

- **Golden runs:** seeded world runs snapshotted (final PMFs, event counts, cost) — any change to prompts/models/policies must diff consciously.
- **Property tests:** SSR pmfs sum to 1; distribution gate catches injected positivity-collapse; dedupe rejects near-duplicates; cost governor degrades not fails.
- **Fake-mode CI:** full pipeline in CI with fake router; real-model runs are a manual, logged benchmark class.
