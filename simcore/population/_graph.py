"""The social graph: clustering from a ring lattice, a hub tail from preferential attachment, and a
homophily pass that rewires toward attribute-similar partners over sampled candidates.

Tie strength is attribute similarity weighted by the ontology's relevance order, quantised before it
becomes an edge so a graph's identity is its structure rather than the numeric path that produced it.
Similarity is read over a bounded sample per rewiring rather than every pair, because all-pairs is
billions of comparisons at the sizes this engine targets. The graph is judged on degree shape,
clustering and connectivity; a failure rejects the population."""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import networkx as nx
import numpy as np

from simcore.schemas import (
    AttributeId,
    AttributeValue,
    BriefPack,
    GateFailure,
    GraphCheck,
    GraphGateResult,
    GraphParameters,
    GraphThresholds,
    Persona,
    SocialEdge,
    SocialGraph,
)

# Tie strengths are quantised to this grid, and never zero, so two numeric builds of the same
# structure hash identically and no edge is recorded as weightless.
QUANTUM = 1000
# How many partners a rewiring considers. Operational: it bounds cost and never changes what is measured.
CANDIDATE_SAMPLE = 16


@dataclass(frozen=True)
class GraphBuild:
    graph: SocialGraph
    results: tuple[GraphGateResult, ...]
    # Newman's attribute assortativity per declared attribute the personas carry: how strongly ties join
    # personas who share it, from -1 through 0 (no preference) to 1 (only like joins like).
    assortativity: Mapping[AttributeId, float]


def build_graph(
    pack: BriefPack,
    personas: Sequence[Persona],
    *,
    population_seed: int,
    parameters: GraphParameters = GraphParameters(),
    thresholds: GraphThresholds = GraphThresholds(),
    audience_of: Mapping[str, str] | None = None,
    candidate_sample_size: int = CANDIDATE_SAMPLE,
) -> GraphBuild:
    """The social structure over `personas`, built from its tuned parameters and judged against its
    tuned thresholds; a failing gate rejects it. The defaults are the values the engine used before."""
    n = len(personas)
    if n < 3:
        raise GateFailure("a social graph needs at least three personas")
    if parameters.hub_attachment >= n:
        raise GateFailure(
            f"a hub attachment of {parameters.hub_attachment} ties each newcomer to more personas than the "
            f"{n} in this population; tune it below the population size rather than have it silently clamped"
        )
    ontology, brief = pack.ontology, pack.brief
    generator = random.Random(f"population-graph:{population_seed}")
    arranged = _arrange(personas, population_seed)

    ring = parameters.ring_degree if n > parameters.ring_degree + 1 else 2
    edges = _ring_lattice(n, ring)
    edges |= {frozenset(edge) for edge in nx.barabasi_albert_graph(n, parameters.hub_attachment, seed=population_seed).edges()}
    edges = _rewire(edges, arranged, ontology, parameters.homophily_strength, candidate_sample_size, generator)

    graph = SocialGraph(
        edges=tuple(
            SocialEdge(u=arranged[u].persona_id, v=arranged[v].persona_id, weight=_weight(arranged[u], arranged[v], ontology))
            for u, v in sorted(tuple(sorted(edge)) for edge in edges)
        )
    )
    if audience_of is not None:
        restating = _audience_assortativity(graph, audience_of)
        if restating is not None and restating >= thresholds.assortativity_ceiling:
            raise GateFailure(
                f"ties follow the declared audiences with assortativity {restating:.2f}, at or above the ceiling of "
                f"{thresholds.assortativity_ceiling}: the graph merely restates the declared audiences"
            )
    results = judge(graph, n, thresholds)
    if not all(result.passed for result in results):
        failed = [result.check.value for result in results if not result.passed]
        raise GateFailure(f"the generated graph fails its structural gates: {failed}")
    return GraphBuild(graph, results, _assortativity(graph, arranged, ontology))


def judge(graph: SocialGraph, n: int, thresholds: GraphThresholds = GraphThresholds()) -> tuple[GraphGateResult, ...]:
    """Degree shape, clustering and connectivity, each with its measured value and its tuned floor."""
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
        GraphGateResult(kind="graph", check=GraphCheck.CONNECTIVITY, measured=connectivity, threshold=thresholds.connectivity_floor),
        GraphGateResult(kind="graph", check=GraphCheck.CLUSTERING, measured=clustering, threshold=thresholds.clustering_floor),
        GraphGateResult(kind="graph", check=GraphCheck.DEGREE_SHAPE, measured=hub_tail, threshold=thresholds.hub_tail_floor),
    )


def _assortativity(graph: SocialGraph, personas: Sequence[Persona], ontology) -> dict[AttributeId, float]:
    """Attribute assortativity for each declared attribute, over the personas that carry it.

    This is what "how much attributes shaped the structure" means. The mean tie strength once reported
    here rose with homophily too, but it is high for any homogeneous population whether or not ties
    follow attributes — it read 0.39 on a graph whose real assortativity was below zero. An attribute
    carried by too few tied personas, or by only one value, has no assortativity to measure and is left out."""
    network = nx.Graph()
    network.add_edges_from((edge.u, edge.v) for edge in graph.edges)
    by_id = {persona.persona_id: persona for persona in personas}
    measured: dict[AttributeId, float] = {}
    for attribute in ontology.relevance_order:
        values = {node: _value(by_id[node], attribute) for node in network.nodes if node in by_id}
        carriers = {node: value for node, value in values.items() if value is not None}
        value = _coefficient(network.subgraph(carriers).copy(), carriers, attribute)
        if value is not None:
            measured[attribute] = value
    return measured


def _audience_assortativity(graph: SocialGraph, audience_of: Mapping[str, str]) -> float | None:
    """How strongly ties stay within the declared audiences, or nothing when there is only one."""
    if len(set(audience_of.values())) < 2:
        return None
    network = nx.Graph()
    network.add_edges_from((edge.u, edge.v) for edge in graph.edges if edge.u in audience_of and edge.v in audience_of)
    return _coefficient(network, {node: audience_of[node] for node in network.nodes}, "audience")


def _coefficient(network: nx.Graph, labels: Mapping[str, AttributeValue], name: str) -> float | None:
    if network.number_of_edges() < 2 or len(set(labels.values())) < 2:
        return None
    nx.set_node_attributes(network, dict(labels), name)
    with np.errstate(divide="ignore", invalid="ignore"):
        value = nx.attribute_assortativity_coefficient(network, name)
    return round(float(value), 6) if math.isfinite(value) else None


def _value(persona: Persona, attribute: AttributeId) -> AttributeValue | None:
    return persona.conditioning.get(attribute, persona.attributes.get(attribute))


def _arrange(personas: Sequence[Persona], population_seed: int) -> list[Persona]:
    """The positions the structural layers tie by: a canonical order, then a seeded permutation.

    The ring lattice ties each position to its neighbours, so if positions followed the order personas
    were handed over — audience by audience, as a draw produces them — the clustering layer would tie
    each audience to itself before homophily did anything, and communities would rediscover the audiences
    by construction. Sorting first makes the graph a function of which personas and which seed, never of
    the order they arrived in; the permutation makes a neighbour in the lattice mean nothing about audience."""
    arranged = sorted(personas, key=lambda persona: persona.persona_id)
    random.Random(f"population-graph-order:{population_seed}").shuffle(arranged)
    return arranged


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
