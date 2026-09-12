"""The social graph: clustering from a ring lattice, a hub tail from preferential attachment, and a
homophily pass that rewires toward attribute-similar partners over sampled candidates.

Tie strength is attribute similarity weighted by the ontology's relevance order, quantised before it
becomes an edge so a graph's identity is its structure rather than the numeric path that produced it.
Similarity is read over a bounded sample per rewiring rather than every pair, because all-pairs is
billions of comparisons at the sizes this engine targets. The graph is judged on degree shape,
clustering and connectivity; a failure rejects the population."""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import networkx as nx

from simcore.schemas import (
    AttributeId,
    AttributeValue,
    BriefPack,
    GateFailure,
    GraphCheck,
    GraphGateResult,
    Persona,
    SocialEdge,
    SocialGraph,
)

# Tie strengths are quantised to this grid, and never zero, so two numeric builds of the same
# structure hash identically and no edge is recorded as weightless.
QUANTUM = 1000
CANDIDATE_SAMPLE = 16
CLUSTERING_FLOOR = 0.05
CONNECTIVITY_FLOOR = 0.98
HUB_TAIL_FLOOR = 1.8


@dataclass(frozen=True)
class GraphBuild:
    graph: SocialGraph
    results: tuple[GraphGateResult, ...]
    assortativity: float


def build_graph(
    pack: BriefPack,
    personas: Sequence[Persona],
    *,
    population_seed: int,
    homophily_strength: float,
    audience_of: Mapping[str, str] | None = None,
    candidate_sample_size: int = CANDIDATE_SAMPLE,
) -> GraphBuild:
    """The social structure over `personas`, built and judged; a failing gate rejects it."""
    n = len(personas)
    if n < 3:
        raise GateFailure("a social graph needs at least three personas")
    ontology, brief = pack.ontology, pack.brief
    generator = random.Random(f"population-graph:{population_seed}")

    edges = _ring_lattice(n, 4 if n > 5 else 2)
    edges |= {frozenset(edge) for edge in nx.barabasi_albert_graph(n, 2, seed=population_seed).edges()}
    edges = _rewire(edges, personas, ontology, homophily_strength, candidate_sample_size, generator)

    graph = SocialGraph(
        edges=tuple(
            SocialEdge(u=personas[u].persona_id, v=personas[v].persona_id, weight=_weight(personas[u], personas[v], ontology))
            for u, v in sorted(edges)
        )
    )
    if audience_of is not None and _restates_the_audiences(graph, audience_of):
        raise GateFailure("every tie stays within an audience, so the graph merely restates the declared audiences")
    results = judge(graph, n)
    if not all(result.passed for result in results):
        failed = [result.check.value for result in results if not result.passed]
        raise GateFailure(f"the generated graph fails its structural gates: {failed}")
    return GraphBuild(graph, results, _assortativity(graph))


def judge(graph: SocialGraph, n: int) -> tuple[GraphGateResult, ...]:
    """Degree shape, clustering and connectivity, each with its measured value and its floor."""
    network = nx.Graph()
    network.add_nodes_from(persona_id for edge in graph.edges for persona_id in (edge.u, edge.v))
    network.add_edges_from((edge.u, edge.v) for edge in graph.edges)
    component_sizes = [len(component) for component in nx.connected_components(network)]
    connectivity = max(component_sizes) / n if component_sizes else 0.0
    clustering = nx.average_clustering(network) if network.number_of_edges() else 0.0
    degrees = [degree for _, degree in network.degree()]
    mean_degree = sum(degrees) / len(degrees) if degrees else 0.0
    hub_tail = (max(degrees) / mean_degree) if mean_degree else 0.0
    return (
        GraphGateResult(kind="graph", check=GraphCheck.CONNECTIVITY, measured=connectivity, threshold=CONNECTIVITY_FLOOR),
        GraphGateResult(kind="graph", check=GraphCheck.CLUSTERING, measured=clustering, threshold=CLUSTERING_FLOOR),
        GraphGateResult(kind="graph", check=GraphCheck.DEGREE_SHAPE, measured=hub_tail, threshold=HUB_TAIL_FLOOR),
    )


def _assortativity(graph: SocialGraph) -> float:
    """How much attributes shaped the structure, as the mean tie strength the edges carry."""
    if not graph.edges:
        return 0.0
    return sum(edge.weight for edge in graph.edges) / len(graph.edges)


def _ring_lattice(n: int, k: int) -> set[frozenset[int]]:
    k = min(k, n - 1)
    return {frozenset((index, (index + step) % n)) for index in range(n) for step in range(1, k // 2 + 1)}


def _rewire(
    edges: set[frozenset[int]],
    personas: Sequence[Persona],
    ontology,
    strength: float,
    candidate_sample_size: int,
    generator: random.Random,
) -> set[frozenset[int]]:
    """Rewire a fraction of ties toward attribute-similar partners, sampling candidates not all pairs."""
    n = len(personas)
    neighbors = {node: set() for node in range(n)}
    for edge in edges:
        u, v = tuple(edge)
        neighbors[u].add(v)
        neighbors[v].add(u)
    order = sorted(edges)
    generator.shuffle(order)
    attempts = int(strength * len(edges))
    for edge in order[:attempts]:
        if edge not in edges:
            continue
        # Fix the higher-degree endpoint and move the other, so homophily does not erode the hubs
        # and never leaves a persona untied.
        u, v = sorted(tuple(edge), key=lambda node: (-len(neighbors[node]), node))
        if len(neighbors[v]) <= 1:
            continue
        candidates = [c for c in _sample_candidates(n, u, neighbors[u], candidate_sample_size, generator) if c != u]
        if not candidates:
            continue
        best = max(candidates, key=lambda candidate: _similarity(personas[u], personas[candidate], ontology))
        if _similarity(personas[u], personas[best], ontology) <= _similarity(personas[u], personas[v], ontology):
            continue
        edges.discard(edge)
        edges.add(frozenset((u, best)))
        neighbors[u].discard(v)
        neighbors[v].discard(u)
        neighbors[u].add(best)
        neighbors[best].add(u)
    return edges


def _sample_candidates(n: int, node: int, neighbors: set[int], count: int, generator: random.Random) -> list[int]:
    excluded = neighbors | {node}
    candidates: list[int] = []
    for _ in range(count * 2):
        candidate = generator.randrange(n)
        if candidate not in excluded and candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) == count:
            break
    return candidates


def _similarity(a: Persona, b: Persona, ontology) -> float:
    """Weighted attribute similarity in [0, 1] over the attributes both personas carry: categorical
    match or normalised ordinal proximity, each weighted by the ontology's relevance order so the most
    relevant shared attributes move the number most. Two personas identical on everything they both
    carry are fully similar, however many fields are absent for both."""
    matched = 0.0
    total = 0.0
    for rank, attribute in enumerate(ontology.relevance_order):
        a_value = a.conditioning.get(attribute, a.attributes.get(attribute))
        b_value = b.conditioning.get(attribute, b.attributes.get(attribute))
        if a_value is None or b_value is None:
            continue
        weight = 1.0 / (rank + 1)
        total += weight
        matched += weight * _attribute_match(attribute, a_value, b_value, ontology)
    return matched / total if total else 0.0


def _attribute_match(attribute: AttributeId, a: AttributeValue, b: AttributeValue, ontology) -> float:
    for scale in ontology.ordinal_scales:
        if scale.attribute != attribute:
            continue
        midpoints = {band.label: band.midpoint for band in scale.bands}
        if a in midpoints and b in midpoints:
            span = max(midpoints.values()) - min(midpoints.values())
            return 1.0 if span == 0 else 1.0 - abs(midpoints[a] - midpoints[b]) / span
        break
    return 1.0 if a == b else 0.0


def _weight(a: Persona, b: Persona, ontology) -> float:
    quantised = round(_similarity(a, b, ontology) * QUANTUM) / QUANTUM
    return min(1.0, max(1.0 / QUANTUM, quantised))


def _restates_the_audiences(graph: SocialGraph, audience_of: Mapping[str, str]) -> bool:
    audiences = set(audience_of.values())
    if len(audiences) < 2:
        return False
    return all(audience_of[edge.u] == audience_of[edge.v] for edge in graph.edges)
