# ConsumerSim — Engine Architecture (OSS)

**Status:** v1 (open-source codebase architecture for `sim_engine/`)
**Scope:** this document specifies only the modules that ship in the open-source engine. Everything Pro-gated (calibration/validation, scenario search beyond grid sweep, analyst-debate reporting, retail-shelf pricing) has been moved to `../ideas/PRO_ARCHITECTURE.md` — same module IDs, so the two documents stay cross-referenceable.
**Related docs:** `SALVAGE.md` (OSS-scoped salvage inventory, same directory) · `OSSARCH.md` (open-core split, positioning, Mermaid diagrams, repo layout) · `../ideas/STRATEGY.md` (business/market context) · `../ideas/PRO_ARCHITECTURE.md` (everything removed from this document)
**Inference substrate:** OSS / OpenAI-compatible inference router (decided — see §4): one model-agnostic gateway (hosted OpenRouter-style or self-hosted LiteLLM/vLLM) that can serve Bedrock models *and* any other provider model behind one interface.

---

## 1. Repository layout

The OSS-scoped repository tree (with Pro-gated folders/stubs annotated) lives in `OSSARCH.md` §2 — not duplicated here to avoid drift. In short: `simcore/{schemas,brief,coreset,personas,llm,cognition,world,execution,search,trace,reporting}/` ship as open-source Python (`uv`-managed, Python 3.12+), with `search/` and `reporting/`'s Pro-only sub-modules present only as typed interfaces that raise `ProFeatureError` (see `OSSARCH.md` §2's design rule).

Core dependencies: `pyarrow` (coreset), `networkx` + `leidenalg` (graph/segments), `openai` pkg (OpenAI-compatible router client — works against OpenRouter, LiteLLM, vLLM, and most managed gateways), optional `boto3` (direct-Bedrock adapter for batch/embeddings), `pydantic` (schemas). SQLite for env state and traces until scale demands otherwise.

---

## 2. Module inventory (OSS)

Legend: **SRC** = salvaged source · phase = when the module lands (spec §6).

| # | Module | Layer | Source | Phase | One-line purpose |
|---|---|---|---|---|---|
| M1 | `schemas/` | cross | NEW | 0 | Pydantic contracts: ProductBrief, Persona, Exposure, Reaction, TraceEvent, ScenarioConfig, ReportFinding |
| M2 | `brief/` | L1 | NEW | 1 | Brief intake, provenance tagging, assumption ledger, category ontology |
| M3 | `coreset/loader` | L2 | **MatrAIx** | 0 | Packed-4-bit decode, postings-index segment filter, shard reader |
| M4 | `coreset/sampling` | L2 | **MatrAIx** + NEW | 0 | Segment→row-id resolution, cohort assembly, distribution gates (χ²/KS vs calibration_targets.json) |
| M5 | `personas/projection` | L2 | NEW | 0 | 1,290-attr → Persona record; sparse-completion policy w/ `synthesized` tagging |
| M6 | `personas/graph` | L2 | NEW + Leiden paper | 2 | Social graph attach (tie strength), Leiden segmentation, segment cards |
| M7 | `llm/router` | cross | NEW + **MatrAIx model_client** | 0 | Provider-agnostic Tier A/B + judge + embeddings via OpenAI-compatible router; retries, token accounting, model pinning, per-role provider routing, fake mode |
| M8 | `cognition/agent` | L3 | **OASIS** agent + **MatrAIx** persona templates | 1 | Persona-conditioned agent turn: perceive → retrieve memory → Tier A/B → Reaction |
| M9 | `cognition/ssr` | L3 | **SSR paper** | 0 | Textual elicitation → router embedding → anchor cosine → Likert pmf (≥6 reference sets) |
| M10 | `cognition/memory` | L3 | **Generative Agents** paper | 2 | Memory stream (recency×importance×relevance), reflections, belief dimensions |
| M11 | `cognition/skills` | L3 | **CUT from v1** | — | Not built in OSS or Pro — see `../ideas/PRO_ARCHITECTURE.md` for the full rationale and return criteria |
| M12 | `world/env` | L4 | **OASIS** | 1 | PettingZoo-style env server, action spaces, SQLite platform state |
| M13 | `world/platforms` | L4 | **OASIS** | 2 | SurveyRoom, SocialFeed, ForumPlatform (`reddit_global` + `community_scoped` presets), WOM. *(RetailShelf is Pro-only — see `../ideas/PRO_ARCHITECTURE.md`.)* |
| M14 | `world/recsys` | L4 | **OASIS** | 2 | Info filter: hot-score (verbatim math), interest-match via router embeddings, exposure budgets. All 4 OASIS modes salvaged; `twhin`/`random` land Phase 2 late |
| M15 | `world/schedule` | L4 | **OASIS clock** + pandemic-ABM paper | 2 | Activation probabilities + intervention schedules (teaser/launch/promo initially; influencer/competitor_move/shock land as OSS matures) |
| M16 | `execution/scheduler` | L5 | NEW | 1 | RunConfig expansion: variants × seeds × cohorts → world run plan |
| M17 | `execution/costs` | L5 | NEW + **MatrAIx usage** | 1 | Budget governor, per-tier spend ledger, degradation paths |
| M18 | `execution/cache` | L5 | NEW | 1 | Prompt-hash response cache, embedding cache, coreset decode cache |
| M19 | `trace/store` | cross | NEW + **OASIS db shape** | 1 | Append-only TraceEvents + run registry (config hash, seeds, model pins, cost) |
| M20 | `search/rollout` | L5 | generic (ASAL-adjacent pattern) | 1 | Batch world runner: N configs × seeds → OutcomeDigests, ships as grid sweep + measured heatmap + rule-based risk flags |
| M21/M22/M23 | `search/{opt,illuminate,judge}` | L6 | ASAL | **Pro** | Auto-proposal, MAP-Elites illumination, LLM-judge — see `../ideas/PRO_ARCHITECTURE.md` |
| M24 | `validation/bench` | L7 | — | **Pro** | Human-vs-synthetic benchmark harness — see `../ideas/PRO_ARCHITECTURE.md` |
| M25 | `validation/calibrate` | L7 | — | **Pro** | Calibration loop, trust-tier transitions — see `../ideas/PRO_ARCHITECTURE.md` |
| M26 | `reporting/analysts` | L8 | TradingAgents pattern | **Pro** | Bull/bear analyst-debate reporting — see `../ideas/PRO_ARCHITECTURE.md` |
| M27 | `reporting/build` | L8 | NEW | 1 | Report renderer: rankings, segment cards, objections, trust labels, validation plan — v1 also authors findings deterministically (M26's duty, absorbed) |
| M28 | `scripts/` CLI | — | NEW | 0+ | `coreset-gate`, `ssr-replica`, `concepts run`, `sweep run` ship in OSS; `benchmark run`, `calibrate` are Pro-gated (see §7) |

---

## 3. Module specs — detailed (OSS modules only)

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

**Licensing note:** do not bundle the parquet shards in this repository — download at first run so end users accept the HF dataset's own terms directly. See `OSSARCH.md` §4.3 for the full pre-launch licensing checklist (currently the one blocking item before public release).

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
6. Fake mode: deterministic canned completions keyed by `prompt_hash` — this is what lets the OSS quickstart run end-to-end with zero API keys (see `OSSARCH.md` §9 / `mockups/oss/quickstart.html`), and gives CI parity with the mockups.

**In →** role, messages (from M8 context assembly), pins
**Out →** `Completion` / `list[embedding]` + COST events.

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
2. `ssr_score(free_text)`: embed text once → per reference set: `softmax(cosine(v, anchor_i)/τ)` over 5 anchors → average R sets → `PMF5`. τ calibrated on held-out human data — the calibration step itself is a Pro-tier activity (`../ideas/PRO_ARCHITECTURE.md` M25); OSS ships with a documented default τ.
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

### M12 — `world/env` (OASIS COPY/ADAPT · Phase 1) — world orchestration

**Does:** the PettingZoo-style step loop that ties platforms, filter, clock, and agents together. Fork of `oasis/environment/env.py` with CAMEL stripped, M7 injected.

**How:** `reset(RunConfig)` instantiates platforms (M13), info filter (M14), clock (M15), agents from cohort (M8) with per-world state; `step(tick, actions)`: apply actions to platforms → platform state updates (SQLite) → compute next-tick stimuli → return `WorldDelta`. Deterministic under (config, seeds); straggler-aware (worlds of different variants finish at different ticks — world-day = max over live worlds).

**In →** `RunConfig`, per-tick `dict[Agent, Action]`. **Out →** `WorldDelta {new_posts, state_updates, stimuli_for_next_tick}`.

---

### M13 — `world/platforms` (OASIS COPY/ADAPT · Phase 2) — the OSS environments

Each platform = action handlers + an exposure source; all state in the world SQLite DB with provenance columns.

| Platform | Mechanics | Actions |
|---|---|---|
| **SurveyRoom** (P1) | isolated: every sampled persona receives the stimulus, no social signals; the calibration-baseline environment | answer (SSR always applied) |
| **SocialFeed** (P2, X-like) | broadcast posts, comments, likes/reposts/quotes; exposure via M14 rec_matrix; social-proof counters | post, comment, like, repost, quote, follow |
| **ForumPlatform** (P2) — one class, two presets | `reddit_global`: any agent, any thread, hot-score ranking (OASIS verbatim) · `community_scoped`: threads = Leiden communities, membership enforced, recency + consensus ranking (reply recency + agreement ratio), no hot-score | create_post, reply, vote |
| **WOM** (P2) | graph channel, not a platform: after a reaction, `wants_to_talk(reaction, peer)` gate (sentiment strength > θ_s AND tie > θ_t, rng) → `deliver(peer, message)` creates next-tick Exposure(reason="wom", tie) | send (implicit) |

*(RetailShelf is Pro-only — pricing decisions need willingness-to-pay grounding from the Pro calibration loop to be credible. Full spec in `../ideas/PRO_ARCHITECTURE.md`.)*

**In →** per-tick actions, intervention stimuli (M15). **Out →** `WorldDelta` + next-tick candidate stimuli + provenance-tagged rows (persona row id, stimulus id, claim ids).

---

### M14 — `world/recsys` (OASIS COPY/ADAPT · Phase 2) — info filter

**Does:** decides which stimuli each activated agent sees — the engine's attention economy. Salvages all four OASIS modes; embedder branches swapped to the router.

**How (modes, from OASIS `recsys.py`):**
- `random` — uniform sample; kept as the control arm (isolates filter-driven vs organic outcomes).
- `reddit_hot` — hot-score **copied verbatim**: engagement counts with time decay; drives herding.
- `twitter` — interest-match: cosine(profile_embedding (M5), post_embedding) ranking.
- `twhin` — personalized graph-aware: follower-graph signals (generated degrees, M6) + posting history + like-scores.

Exposure budget: max E stimuli per agent per tick (default 3); beyond budget, lowest-scored dropped with reason logged. Post embeddings computed at creation (cached); user profile embeddings cached per cohort.

**In →** activated agents, platform stimulus tables, mode + params (from ScenarioConfig). **Out →** `list[Exposure]` (with reason + attention scores) → M8.

---

### M15 — `world/schedule` (OASIS clock + pandemic-ABM · Phase 2) — time & interventions

**How:**
1. Activation clock (fork of `oasis/clock/clock.py`): per-agent `p_act(tick)` = involvement × daily-rhythm profile; seeded sampling; activation counts feed the cost governor.
2. Intervention scheduler: `interventions` from ScenarioConfig injected at tick start — each kind carries an adoption/decay model (promo: uplift with τ-decay; launch: teaser/announce). Pandemic-ABM paper's intervention-interplay semantics: interventions compose, they don't overwrite. Intervention kinds beyond launch/promo (influencer, competitor_move, shock) land as the OSS engine matures.

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

**Does:** append-only TraceEvents + run registry; the store every other module reads for explanation.

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

**In →** TraceEvents from all modules. **Out →** trace queries, registry entries, export tables.

---

### M20 — `search/rollout` (generic · Phase 1) — batch world runner

**Does:** run N ScenarioConfigs × seeds → OutcomeDigests. Every multi-variant study needs this; the ASAL-derived auto-search machinery (M21–M23) is Pro-only (see `../ideas/PRO_ARCHITECTURE.md`).

**How:** worker pool over M16's scheduler (2 workers default); per world: reduced or full tick run per config class (baseline = full 30 ticks; grid sweep = configurable); digest builder (adoption = share-weighted mean PI; polarization = size-weighted JSD between segment PMFs; objections from verbatim clustering; anomalies = tick-level PI jumps > 2σ + comment-sentiment divergence).

The **rule-based risk flags** ship here in OSS: per world, per tick, |Δ mean_PI| > 2σ over trailing window → `herding` flag; comment-sentiment split (bimodal valence) > threshold → `backlash` flag; flagged ticks annotated on trajectories and surfaced in the report risk register — no judge model involved. This is the OSS pattern borrowed from ASAL's `main_sweep_gol.py` (brute-force discrete sweep) — see `SALVAGE.md`.

**In →** `list[ScenarioConfig]`, `CohortManifest`, budget. **Out →** `list[OutcomeDigest]` (+ per-seed adoption lists for σ) → registry + exports.

---

### M27 — `reporting/build` (NEW · Phase 1) — the report renderer

**Does:** digests + trace views → the report object (rankings, segment cards, objection clusters, risk register, scenario atlas, validation plan, method disclosure). **In OSS this module also authors the findings** (the Pro-tier M26 analyst-debate is an optional upgrade, not a requirement): deterministic extraction from prebuilt trace views — objection clusters from verbatim embeddings, belief-delta chains from beliefs.parquet, WOM paths from edges.parquet — with every claim resolved to trace IDs by the builder itself.

**How:** template-versioned renderer; **trust guard at the door**: refuses any finding missing trust_tier/provenance/evidence IDs; refuses quantitative claims without trace resolution (author-then-validate in one pass); emits both markdown (human) and JSON (UI/mockups parity). Always ends with the recommended real-world validation section (invariant: nothing auto-crowned). Risk register is populated from M20's rule-based anomalies (deterministic), not from a debate.

**In →** `list[OutcomeDigest]`, trace views (events/beliefs/edges parquet). **Out →** `Report {sections, findings, trust_statement, method_disclosure}` (md + json), report registry entry.

*Note: in OSS, every report is `trust_tier="exploratory"` — the category/customer/prospective tiers require the Pro calibration loop (M24/M25, `../ideas/PRO_ARCHITECTURE.md`) and are never claimed by the open-source renderer on its own.*

---

### M28 — `scripts/` CLI (NEW · all phases) — entrypoints

| Command | Modules | Phase-0/1 signature |
|---|---|---|
| `coreset-gate` | M3, M4 | `coreset-gate --brief brief.yaml --n 1500 --seed 4021` → GateReport + cohort manifest |
| `ssr-replica` | M7, M9 | `ssr-replica --anchors PI-oralcare-v3 --cohort manifest.json` → distribution notebook |
| `concepts run` | M2, M16, M19, M27 | `concepts run brief.yaml` → report.md/json + run_id |
| `sweep run` | M20 (+ grid sweep) | `sweep run --grid grid.yaml --budget 42` → sweep heatmap json |

`benchmark run` (M24) and `calibrate` (M25) are Pro-gated: present in the CLI, but print an upgrade message and do not execute — see `../ideas/PRO_ARCHITECTURE.md` and `OSSARCH.md` §7.

All commands print `run_id` and refuse to proceed past any failed gate (exit codes distinguish gate-failure from crash).

---

### Salvage cross-reference

Per-module source details live in `SALVAGE.md` (exact repo paths, verdicts, adaptation notes): M3/M4/M5 ← MatrAIx §3.1/3.4 · M7 ← MatrAIx §3.2 · M8 ← MatrAIx §3.3 + OASIS §1 · M12/M13/M14/M15/M19 ← OASIS §1 · M20 ← ASAL (one pattern only, `main_sweep_gol.py`) · M9/M10 ← papers (no code exists — spec §2 recipes are the source). Pro-tier salvage (ASAL → M21–M23, MatrAIx self-report → M25) lives in `../ideas/PRO_ARCHITECTURE.md`.

---

## 4. Inference layer (OSS / [OI]-compatible router) — call-site map

One router (M7) fronts every model call; roles route to different provider models by config:

| Role | Default route (swappable via config) | Call sites |
|---|---|---|
| Tier-B cognition | Claude / GPT / Gemini via **OpenRouter** or direct provider | M8 first impressions, conversations, reflections, purchases |
| Tier-A cognition | **Persona-8B**: OpenRouter-hosted, vLLM self-host, or Bedrock Custom Model Import — Phase-0 microbenchmark decides; Nova Micro / GPT-4o-mini fallback | M8 bulk ticks |
| SSR + info-filter embeddings | one pinned embedding model (OpenAI, Voyage, Bedrock Titan/Cohere — any, but **one** for anchors + responses + recsys) | M9, M14 |
| Content safety | router-side moderation (OpenAI/Bedrock Guardrails) or LLM-based safety check | generated posts/comments before trace write |
| Batch | router provider batch APIs, or direct-Bedrock adapter for large sweeps | M20 |
| Telemetry | router usage payloads → M17 cost governor; per-provider spend tracked separately | all |

**Adapter shape:** `[OI]-compatible` chat endpoint is the primary interface (OpenRouter, LiteLLM proxy, vLLM, and most managed gateways all speak it). Two optional adapters: `bedrock_direct.py` (boto3 — for Batch Inference + Bedrock-native embeddings/guardrails when a route needs them) and `embeddings.py` (provider-specific embedding endpoints). Swapping providers = config change, zero call-site changes.

*(The Judge role — temp-0 JSON model with cited evidence — is Pro-only, feeding M23; not part of the OSS router's default role set.)*

---

## 5. Cross-cutting contracts (from spec §5.4)

1. **No unprovenanced numbers** — every report claim → trace IDs + trust tier.
2. **Grounded ≠ synthesized** — coreset facts vs LLM-completed fields never mix silently.
3. **Replayability** — `run_id` + seeds + model pins + prompt-template hashes reproduce runs.
4. **Nothing auto-crowned** — winners/risks are hypotheses; the report ends in the next real-world test.

These are enforced in code: schemas carry the fields; `trace/` persists them; `reporting/build` refuses untrusted numbers.

---

## 6. Phase → module map (OSS)

| Phase | Modules | Exit artifact |
|---|---|---|
| 0 (wks 1–2) | M1, M3, M4, M5, M7, M9, M28 | `coreset-gate` report + `ssr-replica` notebook (distributions realistic, persona-conditioning signature reproduced) |
| 1 (wks 3–6) | M2, M8, M12, M16, M17, M18, M19, M27 | `concepts run brief.yaml` → ranked report <30 min / <$20 |
| 2 (wks 7–12) | M6, M10, M13, M14, M15 | WOM/feed/forum world; herding event explainable via traces; seeds reproducible |
| 3 (wks 13–18) | M14 (twhin/random modes), M15 (full intervention kinds), M20 grid-sweep feature | Sweep heatmap over user grid; rule-based risk flags live |

Phase 4 (calibration/validation) and the Phase 4+ analyst-debate upgrade are Pro-tier — see `../ideas/PRO_ARCHITECTURE.md`.

---

## 7. Testing strategy

- **Golden runs:** seeded world runs snapshotted (final PMFs, event counts, cost) — any change to prompts/models/policies must diff consciously.
- **Property tests:** SSR pmfs sum to 1; distribution gate catches injected positivity-collapse; dedupe rejects near-duplicates; cost governor degrades not fails.
- **Fake-mode CI:** full pipeline in CI with fake router; real-model runs are a manual, logged benchmark class.

---

## 8. v1 scope cuts (OSS-relevant only)

| Module | v1 status | Why cut | Return trigger |
|---|---|---|---|
| M11 skills | **Cut** (neither OSS nor Pro) | Optimization not capability; mining pre-calibration traces bakes biases in | ≥20 validated studies + ≥30% Tier-A token savings without fidelity loss — full spec in `../ideas/PRO_ARCHITECTURE.md` |
| M14 `twhin`/`random` modes | **Deferred → Phase 2 late / 3** | Two modes (reddit_hot + twitter) suffice for early OSS world dynamics; `random` is a control arm needed once calibration work begins | Graph-personalized mode when WOM depth matters; control arm needed for the Pro calibration phase |
| M15 intervention kinds | **Trimmed** | OSS ships launch + promo only; influencer/competitor_move/shock need risk-register work that lands with the Pro tier | R-register expansion work |

The Pro-relevant rows removed from this table (M26 analysts, M21 opt, M22 illuminate, M23 judge, M13 RetailShelf, and the M11-adjacent per-agent graph memory idea) are specified in `../ideas/PRO_ARCHITECTURE.md`.
