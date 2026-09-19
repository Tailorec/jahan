"""A digest of one world: everything derived from a single world's trace view.

Reads turns for the action mix and belief movement, edges for word-of-mouth reach, and
intent where any exists — masses per audience and per community with their shares and
sizes when it does, the unmeasured reason when it does not. Pure function of the view
plus the scenario it ran and the population it ran over; no model calls.
"""

from collections import Counter

from simcore.schemas import (
    BeliefDim,
    EventFilter,
    OutcomeDigest,
    Scenario,
)
from simcore.schemas.enums import RUNG_ORDER
from simcore.schemas import Population as PopulationModel

from ._audience import audience_of_persona
from ._movement import signed_moves


def digest(view, *, scenario: Scenario, population: PopulationModel, seed: int,
           pinned_embed_model: str | None = None) -> OutcomeDigest:
    """Describe one world's run. The view is scoped to that world; the scenario and replicate
    seed name it, and the derived world id is checked against the world the view read.

    When the run's pinned embedding model is given, a turn scored in another embedding
    space is refused rather than mixed into the masses.
    """
    from simcore.schemas import canonical_hash
    from simcore.schemas.run import derive_world_id

    events = view.events(EventFilter())
    turns = [event for event in events if event.payload.kind == "turn" and event.persona_id is not None]
    turns.sort(key=lambda event: event.seq)

    scenario_hash = canonical_hash(scenario)
    world_id = derive_world_id(scenario, seed, population.manifest.population_hash)
    read_worlds = {event.world_id for event in events}
    if read_worlds and read_worlds != {world_id}:
        raise ValueError(
            f"a digest describes one world: asked for {world_id} but the view read {sorted(read_worlds)}"
        )
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
        if pinned_embed_model is not None and reaction.intent.embed_model_id != pinned_embed_model:
            raise ValueError(
                f"a turn scored in {reaction.intent.embed_model_id}, "
                f"but the run pins {pinned_embed_model} for every embedding"
            )
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

    # The scalar the herding rule is measured against, over turns and reflections alike.
    moves = [move for _, _, move in signed_moves(events)]
    belief_move_mean = sum(moves) / len(moves) if moves else 0.0

    edges = view.edges()
    wom_deliveries = sum(edge.count for edge in edges)
    wom_reach = len({edge.v for edge in edges})

    rungs = sorted(
        {event.payload.rung for event in events if event.payload.kind == "degraded"},
        key=lambda rung: RUNG_ORDER.index(rung),
    )

    if scored:
        audience_pmfs = {name: _mean(masses) for name, masses in sorted(audience_turns.items()) if masses}
        weighted = sum(weights[name] for name in audience_pmfs)
        community_pmfs = {name: _mean(masses) for name, masses in sorted(community_turns.items()) if masses}
        community_sizes = {name: community_population[name] for name in community_pmfs}
        polarization_reason = _polarization_reason(community_pmfs, population)
        if audience_pmfs and weighted > 0.0:
            audience_shares = {name: weights[name] / weighted for name in audience_pmfs}
            unmeasured_reason = None
        else:
            # Turns were scored, but adoption is share-weighted over audiences (ADR 0007) and none
            # of them carries a weighted mass. That is unmeasured with a reason, not a zero.
            named = ", ".join(sorted(weights)) or "none declared"
            audience_pmfs, audience_shares = {}, {}
            unmeasured_reason = (
                f"{len(scored)} turns scored purchase intent, but no persona answering fell in an "
                f"audience this scenario weights ({named}); adoption is share-weighted over audiences"
            )
    else:
        audience_pmfs, audience_shares, community_pmfs, community_sizes = {}, {}, {}, {}
        polarization_reason = _polarization_reason({}, population)
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
        "seed": seed,
        "world_id": world_id,
        "audience_pmfs": audience_pmfs,
        "audience_shares": audience_shares,
        "community_pmfs": community_pmfs,
        "community_sizes": community_sizes,
        "turns_without_intent": unscored,
        "unmeasured_reason": unmeasured_reason,
        "polarization_reason": polarization_reason,
        "turn_count": turn_count,
        "action_mix": dict(sorted(action_mix.items())),
        "belief_movement_mean": {dim: (sum(values) / len(values) if values else 0.0) for dim, values in sorted(movement.items())},
        "belief_movement_abs": {dim: (sum(values) / len(values) if values else 0.0) for dim, values in sorted(absolute.items())},
        "belief_move_mean": belief_move_mean,
        "wom_deliveries": wom_deliveries,
        "wom_reach": wom_reach,
        "rungs": [rung.value for rung in rungs],
    })


def _polarization_reason(community_pmfs: dict, population) -> str | None:
    """Why polarization could not be measured, when it could not.

    It compares communities, so it needs two of them carrying masses. A population whose graph
    formed no qualifying partition has none at all — every community must clear a share of the
    population, so one small remainder discards the whole partition — and that is a different
    absence from a run that scored no intent (ADR 0038).
    """
    if len(community_pmfs) >= 2:
        return None
    formed = len(population.communities)
    if formed == 0:
        return (
            "the population formed no communities, so there are 0 with response masses and "
            "polarization has nothing to compare"
        )
    return (
        f"{len(community_pmfs)} of the population's {formed} communities carry a response mass, "
        "and polarization compares at least two"
    )


def _mean(masses: list[tuple[float, ...]]) -> tuple[float, float, float, float, float]:
    points = [sum(mass[point] for mass in masses) / len(masses) for point in range(5)]
    total = sum(points)
    shaped = tuple(point / total for point in points)
    return (shaped[0], shaped[1], shaped[2], shaped[3], shaped[4])
