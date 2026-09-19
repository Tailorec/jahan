"""The trace summary: one frozen model joining the five shapes of a run's record.

`TraceSummary` answers what the interface's trace, belief and verbatim panels need —
belief histories, word-of-mouth edges, verbatims grouped, event counts per kind and
costs per role — each from the shape that owns it. It reaches storage only through
the five shapes (`events`, `beliefs`, `edges`, `verbatims`, `resolve`): no path, no
frame, no second way in. Two summaries of one trace are identical, so a diff means
a difference in the record.
"""

from typing import Self

from pydantic import Field, model_validator

from .base import FrozenDict, HashDigest, NonNegativeInt, RunId, SimBaseModel
from .query import BeliefHistory, TraceEdge, VerbatimGroup
from .run import WorldId


class CostByRole(SimBaseModel):
    """What one inference role billed: calls, tokens and the known cost.

    A cost nobody knows stays absent rather than becoming zero; `unknown_calls`
    says how many calls it covers.
    """

    role: str
    calls: NonNegativeInt = 0
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    cost: float | None = None
    unknown_calls: NonNegativeInt = 0

    @model_validator(mode="after")
    def _an_absent_cost_states_its_coverage(self) -> Self:
        if self.cost is None and self.calls > 0 and self.unknown_calls == 0:
            raise ValueError("a cost absent over calls with no unknown call says nothing about what it covers")
        return self


class WorldTraceSummary(SimBaseModel):
    """One world's share of the summary: its counts, histories, edges and verbatims."""

    world_id: WorldId
    event_counts: FrozenDict[str, NonNegativeInt] = FrozenDict({})
    max_tick: NonNegativeInt = 0
    belief_total_personas: NonNegativeInt = 0
    belief_histories: tuple[BeliefHistory, ...] = ()
    edges: tuple[TraceEdge, ...] = ()
    verbatim_groups: FrozenDict[str, tuple[VerbatimGroup, ...]] = FrozenDict({})


class TraceSummary(SimBaseModel):
    """The five shapes of a run's record, joined once and frozen.

    Belief histories come from `beliefs`, edges from `edges`, verbatim groups from
    `verbatims`, event counts and costs from `events`. Nothing else is read.
    """

    run_id: RunId
    worlds: tuple[WorldId, ...] = ()
    per_world: tuple[WorldTraceSummary, ...] = ()
    costs: tuple[CostByRole, ...] = ()
    recorded_cost: float = Field(default=0.0, ge=0.0)
    unknown_cost_calls: NonNegativeInt = 0
    trace_hash: HashDigest | None = None

    @model_validator(mode="after")
    def _one_summary_per_world(self) -> Self:
        seen = sorted(world.world_id for world in self.per_world)
        if sorted(self.worlds) != seen:
            raise ValueError(
                f"one summary per world of the run: worlds {sorted(self.worlds)} but summaries for {seen}"
            )
        if len(set(seen)) != len(seen):
            raise ValueError(f"a world is summarised once, got {seen}")
        return self


__all__ = ["CostByRole", "TraceSummary", "WorldTraceSummary"]
