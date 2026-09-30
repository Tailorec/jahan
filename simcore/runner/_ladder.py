"""The degrade ladder: the budget as behaviour.

80% warn, 95% freeze optional tier-B work, 100% subsample activation,
beyond that pause. A rung belongs to the run: every live world takes it at
its next tick and records it; a resume applies the recorded rung rather than
recomputing it. Thresholds and the subsample are configuration, not code.
"""

from __future__ import annotations

from simcore.schemas import DegradationRung, TraceEvent

from ._ledger import pessimistic_figure
from ._plans import LadderConfig, TickPlan


def rung_for(ratio: float, ladder: LadderConfig) -> DegradationRung | None:
    """The rung in force at a spend ratio. Pause fires beyond its threshold."""
    if ratio > ladder.pause_at:
        return DegradationRung.PAUSE
    if ratio >= ladder.subsample_at:
        return DegradationRung.SUBSAMPLE_ACTIVATION
    if ratio >= ladder.freeze_at:
        return DegradationRung.FREEZE_OPTIONAL_TIER_B
    if ratio >= ladder.warn_at:
        return DegradationRung.WARN
    return None


def plan_for(rung: DegradationRung | None, ladder: LadderConfig) -> TickPlan:
    """The frozen per-tick plan for a rung: activation, tier-B freeze, rung."""
    if rung is DegradationRung.WAVE_UNAFFORDABLE:
        # A world paused before its wave runs nothing after: no activation, tier B frozen.
        return TickPlan(activation_rate=0.0, tier_b_frozen=True, rung=rung)
    if rung is DegradationRung.SUBSAMPLE_ACTIVATION or rung is DegradationRung.PAUSE:
        return TickPlan(activation_rate=ladder.subsample_rate, tier_b_frozen=True, rung=rung)
    if rung is DegradationRung.FREEZE_OPTIONAL_TIER_B:
        return TickPlan(activation_rate=ladder.base_activation_rate, tier_b_frozen=True, rung=rung)
    if rung is DegradationRung.WARN:
        return TickPlan(activation_rate=ladder.base_activation_rate, tier_b_frozen=False, rung=rung)
    return TickPlan(activation_rate=ladder.base_activation_rate, tier_b_frozen=False, rung=None)


def recorded_rungs(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> list[DegradationRung]:
    """Rungs a world recorded, in sequence order."""
    out: list[DegradationRung] = []
    for event in sorted(events, key=lambda e: e.seq):
        if event.payload.kind == "degraded":
            out.append(event.payload.rung)
    return out


def last_recorded_rung(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> DegradationRung | None:
    rungs = recorded_rungs(events)
    return rungs[-1] if rungs else None
