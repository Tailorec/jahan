"""A digest of one world: everything derived from a single world's trace view.

Reads turns for the action mix and belief movement, edges for word-of-mouth reach, and
intent where any exists — masses per audience and per community with their shares and
sizes when it does, the unmeasured reason when it does not. Pure function of the view
plus the scenario it ran and the population it ran over; no model calls.
"""

from collections import Counter
from collections.abc import Mapping

from simcore.schemas import (
    BeliefDim,
    EventFilter,
    OutcomeDigest,
    Scenario,
)
from simcore.schemas.enums import RUNG_ORDER
from simcore.schemas import Population as PopulationModel

from ._audience import audience_of_persona

_MEANINGFUL_ACTIONS = ("answer", "post", "comment", "like", "repost", "quote", "follow")


def _persona_values(persona) -> dict:
    return {**persona.conditioning, **persona.attributes}


def digest(view, *, scenario: Scenario, population: PopulationModel) -> OutcomeDigest:
    """Describe one world's run. The view is scoped to that world; the scenario names it."""
    from simcore.schemas import canonical_hash

    events = view.events(EventFilter())
    turns = [event for event in events if event.payload.kind == "turn" and event.persona_id is not None]
    turns.sort(key=lambda event: event.seq)

    scenario_hash = canonical_hash(scenario)
    weights = dict(scenario.audience_weights) if scenario.audience_weights is not None else {}
    if not weights:
        shares = dict(population.pack.brief.audience_shares or {})
        weights = {name: float(share) for name, share in shares.items()}

    communities = {member: community.community_id for community in population.communities for member in community.member_ids}
    community_population = Counter(communities.values())
    audiences = tuple(population.pack.brief.audiences)
    audience_of = {}
    for persona in population.personas:
        audience_of[persona.persona_id] = audience_of_persona(persona, audiences, population.pack.ontology)

    # Intent: one mean mass per scored turn, grouped; unscored turns are counted, never zeroed.
    scored: list[tuple[str, tuple[float, ...]]] = []
    audience_turns: dict[str, list[tuple[float, ...]]] = {}
    community_turns: dict[str, list[tuple[float, ...]]] = {}
    for event in turns:
        reaction = event.payload.turn.reaction
        if reaction.intent is None:
            continue
        mass = tuple(reaction.intent.pmf)
        scored.append((event.persona_id, mass))
        audience = audience_of.get(event.persona_id)
        if audience is not None and audience in weights:
            audience_turns.setdefault(audience, []).append(mass)
        community = communities.get(event.persona_id)
        if community is not None:
            community_turns.setdefault(community, []).append(mass)

    turn_count = len(turns)
    unscored = turn_count - len(scored)
    action_mix = Counter(event.payload.turn.reaction.action.value for event in turns)

    movement: dict[str, list[float]] = {dim.value: [] for dim in BeliefDim}
    absolute: dict[str, list[float]] = {dim.value: [] for dim in BeliefDim}
    for event in turns:
        change = event.payload.turn.reaction.belief_change
        for dim in BeliefDim:
            delta = float(change.dimensions.get(dim, 0.0))
            movement[dim.value].append(delta)
            absolute[dim.value].append(abs(delta))

    edges = view.edges()
    wom_deliveries = sum(edge.count for edge in edges)
    wom_reach = len({edge.v for edge in edges})

    rungs = sorted(
        {event.payload.rung for event in events if event.payload.kind == "degraded"},
        key=lambda rung: RUNG_ORDER.index(rung),
    )

    if scored:
        audience_pmfs = {name: _mean(masses) for name, masses in sorted(audience_turns.items()) if masses}
        if audience_pmfs:
            total = sum(weights[name] for name in audience_pmfs)
            audience_shares = {name: weights[name] / total for name in audience_pmfs}
        else:
            audience_shares = {}
        community_pmfs = {name: _mean(masses) for name, masses in sorted(community_turns.items()) if masses}
        community_sizes = {name: community_population[name] for name in community_pmfs}
        unmeasured_reason = None
    else:
        audience_pmfs, audience_shares, community_pmfs, community_sizes = {}, {}, {}, {}
        failure_kinds = Counter(
            (event.payload.turn.reaction.elicitation_failure.kind.value
             if event.payload.turn.reaction.elicitation_failure is not None else "unscored")
            for event in turns
        )
        leading = ", ".join(f"{kind} {count}" for kind, count in sorted(failure_kinds.items()))
        detail = f" ({leading})" if leading else ""
        unmeasured_reason = f"no turn carried purchase intent; {unscored} of {turn_count} turns went unscored{detail}"

    return OutcomeDigest.model_validate({
        "scenario_hash": scenario_hash,
        "tick_unit": scenario.tick_unit.value,
        "audience_pmfs": audience_pmfs,
        "audience_shares": audience_shares,
        "community_pmfs": community_pmfs,
        "community_sizes": community_sizes,
        "unscored_turns": unscored,
        "unmeasured_reason": unmeasured_reason,
        "turn_count": turn_count,
        "action_mix": dict(sorted(action_mix.items())),
        "belief_movement_mean": {dim: (sum(values) / len(values) if values else 0.0) for dim, values in sorted(movement.items())},
        "belief_movement_abs": {dim: (sum(values) / len(values) if values else 0.0) for dim, values in sorted(absolute.items())},
        "wom_deliveries": wom_deliveries,
        "wom_reach": wom_reach,
        "rungs": [rung.value for rung in rungs],
    })


def _mean(masses: list[tuple[float, ...]]) -> tuple[float, float, float, float, float]:
    points = [sum(mass[point] for mass in masses) / len(masses) for point in range(5)]
    total = sum(points)
    shaped = tuple(point / total for point in points)
    return (shaped[0], shaped[1], shaped[2], shaped[3], shaped[4])
