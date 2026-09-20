"""Communities: discovered from the graph, seeded, substantial, and absent rather than fabricated."""

import pytest

from simcore.population import _communities
from simcore.schemas import (
    Beliefs,
    CommunityThresholds,
    FrozenDict,
    OutcomeDigest,
    Persona,
    SocialEdge,
    SocialGraph,
)
from tests.study_builders import digest_payload


def persona(index: int) -> Persona:
    return Persona(
        persona_id=f"p-{index + 1:06d}",
        source="synthetic",
        conditioning=FrozenDict({"age": "25_34", "sex": "female", "exercise_frequency": "weekly"}),
        attributes=FrozenDict({}),
        origins=FrozenDict({"age": "measured", "sex": "measured", "exercise_frequency": "measured"}),
        baseline_beliefs=Beliefs(
            dimensions=FrozenDict({"value": 0.5, "fit": 0.5, "trust": 0.5}),
            claim_credence=FrozenDict({"C1": 0.5}),
        ),
    )


def personas(count: int = 120) -> list[Persona]:
    return [persona(index) for index in range(count)]


def clustered_graph(people: list[Persona], groups: int = 6) -> SocialGraph:
    ids = [person.persona_id for person in people]
    size = len(ids) // groups
    edges = []
    for group in range(groups):
        members = ids[group * size : (group + 1) * size]
        edges.extend(SocialEdge(u=members[i], v=members[j], weight=0.9) for i in range(len(members)) for j in range(i + 1, len(members)))
    edges.extend(SocialEdge(u=ids[group * size], v=ids[((group + 1) % groups) * size], weight=0.1) for group in range(groups))
    return SocialGraph(edges=tuple(edges))


def ring_graph(people: list[Persona]) -> SocialGraph:
    ids = [person.persona_id for person in people]
    return SocialGraph(edges=tuple(SocialEdge(u=ids[i], v=ids[(i + 1) % len(ids)], weight=0.5) for i in range(len(ids))))


def test_communities_are_discovered_from_the_graph_and_partition_the_population():
    people = personas()
    communities = _communities.detect(people, clustered_graph(people), population_seed=4021)
    assert len(communities) == 6
    members = [member for community in communities for member in community.member_ids]
    assert sorted(members) == sorted(person.persona_id for person in people)
    assert len(set(members)) == len(members)


def test_detection_is_seeded_and_the_same_graph_yields_the_same_communities_twice():
    people = personas()
    graph = clustered_graph(people)
    assert _communities.detect(people, graph, population_seed=4021) == _communities.detect(people, graph, population_seed=4021)


def test_the_resolution_search_selects_the_qualifying_partition_with_the_highest_modularity(monkeypatch):
    people = personas()
    graph = clustered_graph(people)
    modularities = {0.5: 0.5, 0.75: 0.6, 1.0: 0.7, 1.25: 0.3, 1.5: 0.65}
    sizes = {
        0.5: [20, 20, 20, 20, 20, 20],
        0.75: [30, 25, 20, 20, 15, 10],
        1.0: [40, 20, 15, 15, 15, 15],
        1.25: [20, 20, 20, 20, 20, 20],
        1.5: [20, 20, 20, 20, 20, 20],
    }

    def fake_partition(network, gamma, seed):
        membership = []
        for community, size in enumerate(sizes[gamma]):
            membership.extend([community] * size)
        return modularities[gamma], membership

    monkeypatch.setattr(_communities, "_partition", fake_partition)
    communities = _communities.detect(people, graph, population_seed=4021)
    assert sorted(len(community.member_ids) for community in communities) == [15, 15, 15, 15, 20, 40]  # the 0.7 partition


@pytest.mark.parametrize(
    ("modularity", "sizes", "qualifies"),
    [
        (0.8, [20, 20, 20, 20, 20, 20], True),
        (0.2, [20, 20, 20, 20, 20, 20], False),
        (0.8, [40, 40, 40], False),
        (0.8, [20, 20, 20, 20, 20, 15, 5], False),
    ],
    ids=["substantial", "below-modularity-floor", "too-few-communities", "a-community-below-the-share-floor"],
)
def test_a_partition_qualifies_only_when_it_is_substantial(modularity, sizes, qualifies):
    membership = [community for community, size in enumerate(sizes) for _ in range(size)]
    assert _communities._qualifies(modularity, membership, sum(sizes)) is qualifies


def test_community_selection_follows_its_tuned_thresholds():
    people = personas()
    graph = clustered_graph(people)
    default = _communities.detect(people, graph, population_seed=4021)
    tuned = CommunityThresholds(min_communities=2, share_floor=0.2)
    found = _communities.detect(people, graph, population_seed=4021, thresholds=tuned)
    assert found != default
    assert all(len(community.member_ids) >= 0.2 * len(people) for community in found)


def test_the_resolution_search_covers_exactly_the_tuned_resolutions(monkeypatch):
    people = personas()
    searched: list[float] = []

    def recording(network, gamma, seed):
        searched.append(gamma)
        return 0.0, [0] * len(people)

    monkeypatch.setattr(_communities, "_partition", recording)
    _communities.detect(people, clustered_graph(people), population_seed=4021, thresholds=CommunityThresholds(resolutions=(0.3, 0.9)))
    assert searched == [0.3, 0.9]


def test_a_graph_with_no_qualifying_partition_produces_no_communities():
    people = personas()
    assert _communities.detect(people, ring_graph(people), population_seed=4021) == ()


def test_a_population_with_no_communities_reports_polarization_as_not_measurable():
    people = personas()
    assert _communities.detect(people, ring_graph(people), population_seed=4021) == ()
    digest = OutcomeDigest.model_validate(digest_payload(community_pmfs={}, community_sizes={}))
    assert digest.polarization is None


def test_communities_appear_only_in_outputs_and_are_never_read_from_an_input():
    import simcore.schemas as schemas

    for model in (schemas.ProductBrief, schemas.BriefPack, schemas.CategoryOntology, schemas.Variant,
                  schemas.Scenario, schemas.SweepGrid, schemas.SweepPlan, schemas.RunConfig):
        assert "Community" not in repr(model.model_fields), f"{model.__name__} references a community"


def _small_network():
    import igraph as ig

    network = ig.Graph(n=8, edges=[(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (2, 3), (6, 7)], directed=False)
    network.es["weight"] = [1.0] * network.ecount()
    return network


def test_every_population_seed_can_drive_community_detection():
    """`spawn` derives each stream's seed as an unsigned 64-bit integer, and `leidenalg` takes a signed
    C `ssize_t`. A seed at or above 2**63 crashed with `OverflowError: Python int too large to convert to
    C ssize_t` — after the draw had already passed its gates. Of forty consecutive population seeds,
    twenty-three did; 4021, the only one ever used, happened to derive a small value."""
    from simcore.population._streams import spawn

    network = _small_network()
    for population_seed in range(4000, 4040):
        _, membership = _communities._partition(network, 1.0, spawn(population_seed)[2])
        assert len(membership) == 8


def test_a_seed_that_already_fits_keeps_exactly_the_partition_it_had():
    """The fix must not move any existing population: a seed below 2**63 is passed through unchanged, so
    every recorded population's identity stands."""
    network = _small_network()
    fits = 4021
    assert fits < 2**63
    assert _communities._partition(network, 1.0, fits) == _communities._partition(network, 1.0, fits)
    assert _communities._leiden_seed(fits) == fits
    assert _communities._leiden_seed(2**63 + 5) == 5
    assert 0 <= _communities._leiden_seed(2**64 - 1) < 2**63
