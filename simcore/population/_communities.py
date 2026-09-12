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

from simcore.schemas import Community, CommunityThresholds, Persona, SocialGraph


def detect(
    personas: Sequence[Persona],
    graph: SocialGraph,
    *,
    population_seed: int,
    thresholds: CommunityThresholds = CommunityThresholds(),
) -> tuple[Community, ...]:
    """The qualifying partition with the highest modularity across the resolution search, or none.

    What counts as substantial — the modularity floor, the community band, the share floor and the
    resolutions searched — is the study's to tune, and the defaults are what the engine used before."""
    network = _network(personas, graph)
    best: tuple[float, list[int]] | None = None
    for gamma in thresholds.resolutions:
        modularity, membership = _partition(network, gamma, population_seed)
        if not _qualifies(modularity, membership, len(personas), thresholds):
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


def _qualifies(
    modularity: float, membership: Sequence[int], size: int, thresholds: CommunityThresholds = CommunityThresholds()
) -> bool:
    sizes = Counter(membership)
    return (
        modularity >= thresholds.modularity_floor
        and thresholds.min_communities <= len(sizes) <= thresholds.max_communities
        and all(count >= thresholds.share_floor * size for count in sizes.values())
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
