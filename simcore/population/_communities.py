"""Communities: who ended up talking to whom, discovered from the graph with Leiden.

A partition is a result, never an input: the graph is generated and the communities are found in it,
so a split that cuts across the declared audiences is findable. Leiden runs seeded across a
resolution search, and the qualifying partition with the highest modularity is chosen — enough
communities, each holding at least a share of the population, so a small study is not structurally
doomed. A graph that yields no qualifying partition is still valid; it simply has no communities, and
polarization is then reported as not measurable rather than as a measured zero."""

from collections import Counter
from collections.abc import Sequence

import igraph as ig
import leidenalg

from simcore.schemas import Community, Persona, SocialGraph

# A partition qualifies only when it is substantial: a modularity floor, a count band, and a size
# floor expressed as a share so the floor scales with the study rather than fixing a count.
MODULARITY_FLOOR = 0.4
COMMUNITY_SHARE_FLOOR = 0.05
MIN_COMMUNITIES = 4
MAX_COMMUNITIES = 8
RESOLUTIONS = (0.5, 0.75, 1.0, 1.25, 1.5)


def detect(personas: Sequence[Persona], graph: SocialGraph, *, population_seed: int) -> tuple[Community, ...]:
    """The qualifying partition with the highest modularity across the resolution search, or none."""
    network = _network(personas, graph)
    best: tuple[float, list[int]] | None = None
    for gamma in RESOLUTIONS:
        modularity, membership = _partition(network, gamma, population_seed)
        if not _qualifies(modularity, membership, len(personas)):
            continue
        if best is None or modularity > best[0] + 1e-12:
            best = (modularity, membership)
    if best is None:
        return ()
    return _communities(best[1], personas)


def _network(personas: Sequence[Persona], graph: SocialGraph) -> ig.Graph:
    index = {persona.persona_id: position for position, persona in enumerate(personas)}
    network = ig.Graph(n=len(personas), edges=[(index[edge.u], index[edge.v]) for edge in graph.edges], directed=False)
    network.es["weight"] = [edge.weight for edge in graph.edges]
    return network


def _partition(network: ig.Graph, gamma: float, seed: int) -> tuple[float, list[int]]:
    partition = leidenalg.find_partition(
        network, leidenalg.RBConfigurationVertexPartition, weights="weight", resolution_parameter=gamma, seed=seed
    )
    membership = list(partition.membership)
    return float(network.modularity(membership, weights="weight")), membership


def _qualifies(modularity: float, membership: Sequence[int], size: int) -> bool:
    sizes = Counter(membership)
    return (
        modularity >= MODULARITY_FLOOR
        and MIN_COMMUNITIES <= len(sizes) <= MAX_COMMUNITIES
        and all(count >= COMMUNITY_SHARE_FLOOR * size for count in sizes.values())
    )


def _communities(membership: Sequence[int], personas: Sequence[Persona]) -> tuple[Community, ...]:
    groups: dict[int, list[int]] = {}
    for position, community in enumerate(membership):
        groups.setdefault(community, []).append(position)
    ordered = sorted(groups.values(), key=min)
    return tuple(
        Community(
            community_id=f"community-{number}",
            member_ids=tuple(personas[position].persona_id for position in positions),
        )
        for number, positions in enumerate(ordered, start=1)
    )
