"""The saved social graph, read: shape, spread of ties, hubs and one persona's circle."""

import pytest

from simcore.population._graph_view import graph_view

# A hub (0) tied to four people; 1–2 and 3–4 know each other; 5 is a friend of 1 only.
STORED = {
    "graph_hash": "abc",
    "nodes": [["hub", "parents", "c1"], ["a", "parents", "c1"], ["b", "retirees", "c1"],
              ["c", "retirees", "c2"], ["d", "parents", "c2"], ["e", "retirees", None]],
    "edges": [[0, 1, 0.9], [0, 2, 0.5], [0, 3, 0.7], [0, 4, 0.2], [1, 2, 0.6], [3, 4, 0.4], [1, 5, 0.8]],
    "checks": [{"kind": "graph", "check": "connectivity", "measured": 1.0, "threshold": 0.98}],
}


def test_the_summary_and_the_spread_of_ties():
    view = graph_view(STORED, "hub")
    assert view["summary"] == {"personas": 6, "ties": 7, "mean_ties": 2.33, "most_ties": 4, "fewest_ties": 1, "audience_assortativity": None}
    assert view["degree_histogram"] == [(1, 1), (2, 3), (3, 1), (4, 1)]
    assert view["hubs"][0] == {"id": "hub", "audience": "parents", "community": "c1", "ties": 4}


def test_a_circle_is_friends_then_friends_of_friends_up_to_its_limit():
    circle = graph_view(STORED, "a")["circle"]
    assert circle["center"] == "a" and circle["friends"] == 3
    assert [(node["id"], node["depth"]) for node in circle["nodes"]] == [("a", 0), ("hub", 1), ("b", 1), ("e", 1), ("c", 2), ("d", 2)]
    small = graph_view(STORED, "hub", limit=3)["circle"]
    assert [node["id"] for node in small["nodes"]] == ["hub", "a", "c"], "strongest ties first"
    ids = [node["id"] for node in small["nodes"]]
    assert all(ids[u] in {"hub", "a", "c"} and ids[v] in {"hub", "a", "c"} for u, v, _ in small["edges"])


def test_without_a_persona_the_circle_starts_from_someone_typical_and_an_unknown_one_is_refused():
    assert graph_view(STORED)["circle"]["center"] in {"a", "c", "d", "b"}  # two or three ties, not the hub
    with pytest.raises(ValueError, match="no persona"):
        graph_view(STORED, "nobody")
