"""Trajectories per audience and per community per tick: a derived shape in analysis.

Matches the same quantities recomputed from raw events: per audience and per community,
the mean belief (overall and per dimension) per tick across closed ticks.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from simcore.schemas import (
    BeliefDim,
    EventFilter,
    FrozenDict,
    NonNegativeInt,
    SimBaseModel,
)
from simcore.schemas.run import WorldId
from ._audience import audience_of_persona


class TrajectoryPoint(SimBaseModel):
    """One aggregate point at a given tick for an audience or community."""

    tick: NonNegativeInt
    mean_belief: float
    dimensions: FrozenDict[str, float] = FrozenDict({})
    count: NonNegativeInt = 0


class WorldTrajectories(SimBaseModel):
    """Trajectories per audience and per community across a world's ticks."""

    world_id: WorldId
    audiences: FrozenDict[str, tuple[TrajectoryPoint, ...]] = FrozenDict({})
    communities: FrozenDict[str, tuple[TrajectoryPoint, ...]] = FrozenDict({})


def trajectories(
    view: Any,
    *,
    scenario: Any,
    population: Any,
    world_id: str | None = None,
) -> WorldTrajectories:
    """Compute per-tick trajectories per audience and per community from a world's trace view.

    Every quantity matches the same quantity computed from raw belief_snapshot events.
    """
    events = view.events(EventFilter.model_validate({"kinds": ("belief_snapshot",)}))
    
    # Map personas to audience and community
    audiences_spec = tuple(population.pack.brief.audiences)
    audience_of: dict[str, str | None] = {}
    for persona in population.personas:
        audience_of[persona.persona_id] = audience_of_persona(
            persona, audiences_spec, population.pack.ontology
        )

    community_of: dict[str, str] = {}
    for community in population.communities:
        for member_id in community.member_ids:
            community_of[member_id] = community.community_id

    # Group snapshots by tick
    # (tick, audience) -> list of dimensions dict
    aud_by_tick: dict[tuple[int, str], list[dict[str, float]]] = defaultdict(list)
    comm_by_tick: dict[tuple[int, str], list[dict[str, float]]] = defaultdict(list)
    all_ticks: set[int] = set()
    found_world_id = world_id

    for event in events:
        if event.payload.kind != "belief_snapshot" or event.persona_id is None:
            continue
        if found_world_id is None:
            found_world_id = event.world_id
        tick = event.tick
        all_ticks.add(tick)
        beliefs = event.payload.beliefs
        dims = {}
        for dim, val in beliefs.dimensions.items():
            key = dim.value if hasattr(dim, "value") else str(dim)
            dims[key] = float(val)

        aud = audience_of.get(event.persona_id)
        if aud is not None:
            aud_by_tick[(tick, aud)].append(dims)

        comm = community_of.get(event.persona_id)
        if comm is not None:
            comm_by_tick[(tick, comm)].append(dims)

    sorted_ticks = sorted(all_ticks)
    all_audiences = sorted({aud for aud in audience_of.values() if aud is not None})
    all_communities = sorted({c.community_id for c in population.communities})

    audience_trajectories: dict[str, list[TrajectoryPoint]] = {}
    for aud in all_audiences:
        points = []
        for tick in sorted_ticks:
            dim_list = aud_by_tick.get((tick, aud), [])
            if not dim_list:
                continue
            count = len(dim_list)
            # Compute mean per dimension
            dim_means: dict[str, float] = {}
            for dim_key in ("value", "fit", "trust"):
                vals = [d[dim_key] for d in dim_list if dim_key in d]
                if vals:
                    dim_means[dim_key] = sum(vals) / len(vals)
            overall = sum(dim_means.values()) / len(dim_means) if dim_means else 0.0
            points.append(
                TrajectoryPoint(
                    tick=tick,
                    mean_belief=overall,
                    dimensions=FrozenDict(dim_means),
                    count=count,
                )
            )
        audience_trajectories[aud] = tuple(points)

    community_trajectories: dict[str, tuple[TrajectoryPoint, ...]] = {}
    for comm in all_communities:
        points = []
        for tick in sorted_ticks:
            dim_list = comm_by_tick.get((tick, comm), [])
            if not dim_list:
                continue
            count = len(dim_list)
            dim_means = {}
            for dim_key in ("value", "fit", "trust"):
                vals = [d[dim_key] for d in dim_list if dim_key in d]
                if vals:
                    dim_means[dim_key] = sum(vals) / len(vals)
            overall = sum(dim_means.values()) / len(dim_means) if dim_means else 0.0
            points.append(
                TrajectoryPoint(
                    tick=tick,
                    mean_belief=overall,
                    dimensions=FrozenDict(dim_means),
                    count=count,
                )
            )
        community_trajectories[comm] = tuple(points)

    return WorldTrajectories(
        world_id=found_world_id or "world-default",
        audiences=FrozenDict(audience_trajectories),
        communities=FrozenDict(community_trajectories),
    )
