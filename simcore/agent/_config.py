"""The agent's configuration: tier routing, budgets, templates, anchors and seeds.

The routing table is data a study can change, not code: which turn tasks deserve the
stronger tier-B model is a study decision. Everything seeded derives from the run seed
and a named purpose, so adding a draw cannot shift an existing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from simcore.schemas import InferenceRole, TurnTask


# `{first_seen, conversation, reflection, purchase, claim_audit}` answer on tier B;
# everything else answers on tier A. A study overrides this table, never the code.
DEFAULT_TIER_ROUTING: dict[TurnTask, InferenceRole] = {
    TurnTask.FIRST_SEEN: InferenceRole.TIER_B,
    TurnTask.CONVERSATION: InferenceRole.TIER_B,
    TurnTask.REFLECTION: InferenceRole.TIER_B,
    TurnTask.PURCHASE: InferenceRole.TIER_B,
    TurnTask.CLAIM_AUDIT: InferenceRole.TIER_B,
    TurnTask.REACTION: InferenceRole.TIER_A,
    TurnTask.PROBE: InferenceRole.TIER_A,
}


@dataclass(frozen=True)
class AgentConfig:
    """What a study decides about its turns; the engine's defaults apply where it is silent."""

    tier_routing: dict[TurnTask, InferenceRole] = field(default_factory=lambda: dict(DEFAULT_TIER_ROUTING))
    # Token budgets per tier for one assembled context; memories drop before beliefs.
    token_budget: dict[InferenceRole, int] = field(
        default_factory=lambda: {InferenceRole.TIER_A: 2048, InferenceRole.TIER_B: 8192}
    )
    template_id: str = "persona_turn"
    strict_template_id: str = "persona_turn_strict"
    reflection_template_id: str = "persona_reflection"
    probe_template_id: str = "persona_probe"
    max_tokens: int = 512
    run_seed: int = 0
    horizon_ticks: int = 30
    # Retrieval: recency time constant as a share of the horizon, and top-k per tier.
    tau_r_share: float = 0.25
    top_k: dict[InferenceRole, int] = field(
        default_factory=lambda: {InferenceRole.TIER_A: 3, InferenceRole.TIER_B: 8}
    )
    # Reflection: base cadence in ticks, jittered per persona from the run seed.
    reflection_interval: int = 6
    reflection_jitter: int = 2
    reflection_delta_threshold: float = 0.3
    memory_cap: int = 50
    # Character probe: share of activated personas, asked every this many ticks.
    probe_share: float = 0.02
    probe_every_ticks: int = 10
    probe_questions: int = 2
    # Purchase intent: the pinned anchor set per construct, empty when none is pinned.
    anchor_set_ids: dict[str, str] = field(default_factory=dict)
    anchor_versions: dict[str, str] = field(default_factory=dict)
    anchor_hashes: dict[str, str] = field(default_factory=dict)
    anchors_dir: str = "anchors"
    category: str = ""

    def tier_for(self, task: TurnTask) -> InferenceRole:
        return self.tier_routing.get(task, InferenceRole.TIER_A)
