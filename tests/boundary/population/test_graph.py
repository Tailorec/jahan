"""The graph: clustering, a hub tail, homophily rewirings, quantised ties, and structural gates."""

import statistics

import networkx as nx
import pytest

from simcore.population import _graph
from simcore.population._project import project
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import (
    Beliefs,
    BriefPack,
    Exactly,
    FrozenDict,
    GateFailure,
    GraphCheck,
    GraphGateResult,
    GraphParameters,
    GraphThresholds,
    Persona,
    SocialEdge,
    SocialGraph,
    canonical_hash,
)
from tests.study_builders import pack_payload

MODEL = "openrouter/camel-ai/persona-8b"


def synthetic(rows: int = 800, seed: int = 7) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
                "spend_band": AttributeShape(("5_10", "10_20")),
            },
            rows=rows,
        ),
        seed=seed,
    )


def projected(count: int = 250):
    pack = BriefPack.model_validate(pack_payload())
    source = synthetic()
    conditioning = tuple(sorted(pack.ontology.conditioning_set))
    rows = list(source.rows(source.matching({}, present=conditioning)[:count]))
    return pack, project(pack, rows, source, inference=FakeChat(model_id=MODEL)).personas


def audience_grouped(gym_count: int = 150, diet_count: int = 100):
    """Personas handed over audience by audience — the order a draw produces them in."""
    pack = BriefPack.model_validate(pack_payload())
    source = synthetic(rows=2000)
    conditioning = tuple(sorted(pack.ontology.conditioning_set))
    gym = list(source.matching({"exercise_frequency": Exactly(value="3_plus_weekly")}, present=conditioning)[:gym_count])
    taken = set(gym)
    diet = [row_id for row_id in source.matching({"diet_protein_focus": Exactly(value="high")}, present=conditioning) if row_id not in taken][:diet_count]
    rows = list(source.rows(gym + diet))
    people = project(pack, rows, source, inference=FakeChat(model_id=MODEL)).personas
    audience_of = {person.persona_id: ("gym" if index < len(gym) else "diet") for index, person in enumerate(people)}
    return pack, people, audience_of


def network_of(graph: SocialGraph) -> nx.Graph:
    network = nx.Graph()
    network.add_edges_from((edge.u, edge.v) for edge in graph.edges)
    return network


def test_a_generated_graph_carries_clustering_and_a_hub_tail():
    pack, personas = projected()
    build = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.5))
    degrees = [degree for _, degree in network_of(build.graph).degree()]
    assert min(degrees) >= 1 and max(degrees) > statistics.mean(degrees)
    checks = {result.check.value: result for result in build.results}
    assert checks["clustering"].measured > 0.05
    assert checks["degree_shape"].measured > 1.8
    assert all(result.passed for result in build.results)


def test_two_personas_sharing_their_most_relevant_attributes_are_likelier_tied():
    pack, personas = projected()
    anchor = personas[0]
    top = pack.ontology.relevance_order[0]
    anchor_value = anchor.conditioning.get(top, anchor.attributes.get(top))
    sharing = [p for p in personas[1:] if p.conditioning.get(top, p.attributes.get(top)) == anchor_value]
    differing = [p for p in personas[1:] if p.conditioning.get(top, p.attributes.get(top)) != anchor_value]
    assert sharing and differing
    assert statistics.mean(_graph._similarity(anchor, p, pack.ontology) for p in sharing) > statistics.mean(
        _graph._similarity(anchor, p, pack.ontology) for p in differing
    )


def test_a_ties_strength_can_be_explained_from_the_attributes_that_produced_it():
    pack = BriefPack.model_validate(pack_payload())
    beliefs = Beliefs(
        dimensions=FrozenDict({"value": 0.5, "fit": 0.5, "trust": 0.5}),
        claim_credence=FrozenDict({claim.id: 0.5 for claim in pack.brief.claims}),
    )

    def persona(persona_id: str, exercise: str, age: str) -> Persona:
        return Persona(
            persona_id=persona_id,
            source="synthetic",
            conditioning=FrozenDict({"age": age, "sex": "female", "exercise_frequency": exercise}),
            attributes=FrozenDict({}),
            origins=FrozenDict(
                {"age": "grounded", "sex": "grounded", "exercise_frequency": "grounded"}
            ),
            baseline_beliefs=beliefs,
        )

    same = persona("p-000001", "3_plus_weekly", "25_34")
    twin = persona("p-000002", "3_plus_weekly", "25_34")
    different = persona("p-000003", "rarely", "45_54")
    assert _graph._similarity(same, twin, pack.ontology) == 1.0
    assert _graph._similarity(same, different, pack.ontology) < 1.0
    assert _graph._weight(same, twin, pack.ontology) == 1.0


def test_tie_strengths_are_quantised_and_the_same_graph_hashes_identically():
    pack, personas = projected()
    first = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.5))
    second = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.5))
    assert canonical_hash(first.graph) == canonical_hash(second.graph)
    assert all(abs(edge.weight * _graph.QUANTUM - round(edge.weight * _graph.QUANTUM)) < 1e-9 for edge in first.graph.edges)


def test_every_persona_has_at_least_one_tie():
    pack, personas = projected()
    build = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=1.0))
    tied = {endpoint for edge in build.graph.edges for endpoint in (edge.u, edge.v)}
    assert all(persona.persona_id in tied for persona in personas)


def test_degree_shape_clustering_and_connectivity_are_judged_and_a_failure_rejects(monkeypatch):
    disconnected = SocialGraph(
        edges=(
            SocialEdge(u="p-1", v="p-2", weight=0.5),
            SocialEdge(u="p-3", v="p-4", weight=0.5),
        )
    )
    results = {result.check.value: result for result in _graph.judge(disconnected, 4)}
    assert results["connectivity"].passed is False
    assert {"connectivity", "clustering", "degree_shape"} == set(results)

    pack, personas = projected(count=40)
    failing = (GraphGateResult(kind="graph", check=GraphCheck.CONNECTIVITY, measured=0.5, threshold=0.98),)
    monkeypatch.setattr(_graph, "judge", lambda graph, n, thresholds: failing)
    with pytest.raises(GateFailure, match="structural gates"):
        _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.5))


def test_homophily_strength_is_recorded_and_two_strengths_produce_different_graphs():
    pack, personas = projected()
    weak = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.0))
    strong = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=1.0))
    assert canonical_hash(weak.graph) != canonical_hash(strong.graph)


def test_similarity_is_computed_over_sampled_candidates_not_all_pairs(monkeypatch):
    pack, personas = projected(count=250)
    calls: list[int] = []
    original = _graph._similarity

    def counting(a, b, ontology):
        calls.append(1)
        return original(a, b, ontology)

    monkeypatch.setattr(_graph, "_similarity", counting)
    build = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=1.0))
    n = len(personas)
    assert len(calls) < n * (n - 1) / 2
    assert len(calls) <= int(1.0 * len(build.graph.edges)) * (_graph.CANDIDATE_SAMPLE + 2) + len(build.graph.edges)


def test_graph_structure_follows_its_tuned_parameters():
    pack, personas = projected()
    permissive = GraphThresholds(clustering_floor=0.0, connectivity_floor=0.0, hub_tail_floor=1.01)
    sparse = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(ring_degree=4, hub_attachment=1), thresholds=permissive)
    dense = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(ring_degree=8, hub_attachment=4), thresholds=permissive)
    assert len(dense.graph.edges) > len(sparse.graph.edges)


def test_graph_gate_floors_are_tunable_carried_on_each_result_and_a_raised_floor_rejects():
    pack, personas = projected()
    build = _graph.build_graph(pack, personas, population_seed=4021)
    assert {result.check.value: result.threshold for result in build.results} == {"connectivity": 0.98, "clustering": 0.05, "degree_shape": 1.8}
    with pytest.raises(GateFailure, match="clustering"):
        _graph.build_graph(pack, personas, population_seed=4021, thresholds=GraphThresholds(clustering_floor=0.99))


def test_a_hub_attachment_the_population_cannot_support_is_refused_not_clamped():
    pack, personas = projected(count=40)
    with pytest.raises(GateFailure, match="hub attachment of 40"):
        _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(hub_attachment=40))



def test_the_order_personas_arrive_in_does_not_segregate_the_graph():
    """Handed over audience by audience, the clustering layer once tied each audience to itself (82% of ties
    against 52% under random mixing) before homophily did anything."""
    pack, people, audience_of = audience_grouped()
    build = _graph.build_graph(pack, people, population_seed=4021, parameters=GraphParameters(homophily_strength=0.0))
    within = sum(audience_of[edge.u] == audience_of[edge.v] for edge in build.graph.edges) / len(build.graph.edges)
    gym_share = 150 / 250
    random_mixing = gym_share**2 + (1 - gym_share) ** 2
    assert within < random_mixing + 0.08


def test_the_same_personas_in_any_order_build_the_same_graph():
    pack, people, _ = audience_grouped()
    forward = _graph.build_graph(pack, people, population_seed=4021)
    backward = _graph.build_graph(pack, list(reversed(people)), population_seed=4021)
    assert canonical_hash(forward.graph) == canonical_hash(backward.graph)


def test_the_measured_attribute_assortativity_is_reported_per_attribute():
    """Real assortativity: near zero when ties ignore attributes, rising as homophily makes like join like."""
    pack, personas = projected()
    weak = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=0.0))
    strong = _graph.build_graph(pack, personas, population_seed=4021, parameters=GraphParameters(homophily_strength=1.0))
    assert set(weak.assortativity) <= set(pack.ontology.attribute_domains)
    assert abs(weak.assortativity["exercise_frequency"]) < 0.15
    assert strong.assortativity["exercise_frequency"] > weak.assortativity["exercise_frequency"] + 0.05


def test_a_graph_whose_ties_restate_the_audiences_is_refused_at_the_assortativity_ceiling():
    pack, people, audience_of = audience_grouped()
    accepted = _graph.build_graph(pack, people, population_seed=4021, audience_of=audience_of)
    assert accepted.graph.edges
    with pytest.raises(GateFailure, match="restates the declared audiences"):
        _graph.build_graph(
            pack,
            people,
            population_seed=4021,
            audience_of=audience_of,
            parameters=GraphParameters(homophily_strength=1.0),
            thresholds=GraphThresholds(assortativity_ceiling=0.01),
        )
