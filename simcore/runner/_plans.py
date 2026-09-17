"""Per-tick plans and the degrade ladder configuration.

The plan, not the config: each tick `world` and `agent` receive a frozen
plan (activation rate, tier routing, tier-B enabled). Degradation is a
different plan, never a mutated object shared across parallel worlds, and
neither module learns that budgets exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from simcore.schemas import DegradationRung, InferenceRole, TurnTask


@dataclass(frozen=True)
class TickPlan:
    """What one tick runs under: activation, tier-B freeze, and the rung in force."""

    activation_rate: float = 1.0
    tier_b_frozen: bool = False
    rung: DegradationRung | None = None


@dataclass(frozen=True)
class LadderConfig:
    """Where the ladder fires and what subsampling applies. Configuration, not code."""

    warn_at: float = 0.80
    freeze_at: float = 0.95
    subsample_at: float = 1.0
    subsample_rate: float = 0.40
    base_activation_rate: float = 1.0


def agent_routing_for(plan: TickPlan, base: dict[TurnTask, InferenceRole] | None = None) -> dict[TurnTask, InferenceRole]:
    """Tier routing under a plan: frozen plans route everything to tier A."""
    from simcore.agent import DEFAULT_TIER_ROUTING

    routing = dict(base) if base is not None else dict(DEFAULT_TIER_ROUTING)
    if plan.tier_b_frozen:
        return {task: InferenceRole.TIER_A for task in routing}
    return routing
