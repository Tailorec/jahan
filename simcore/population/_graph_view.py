"""A saved social graph as a person can read it: its size and shape, how ties are spread, who the hubs are,
and one persona's circle. Computed here so the interface only draws it (ADR 0045)."""

from __future__ import annotations

from collections import Counter


def graph_view(stored: dict, center: str | None = None, limit: int = 120) -> dict:
    """The view of `stored` (a run's graph.json) around `center`, or around a persona with a typical number of
    ties. The circle is every friend, strongest tie first, then friends of friends until `limit` people."""
    nodes = stored["nodes"]
    edges = stored["edges"]
    count = len(nodes)
    neighbours: list[list[tuple[int, float]]] = [[] for _ in range(count)]
    for u, v, weight in edges:
        neighbours[u].append((v, weight))
        neighbours[v].append((u, weight))
    ties = [len(around) for around in neighbours]
    index = {node[0]: position for position, node in enumerate(nodes)}
    if center is not None and center not in index:
        raise ValueError(f"no persona {center} in this population")
    typical = sorted(ties)[count // 2] if count else 0
    middle = index[center] if center is not None else next((i for i in range(count) if ties[i] == typical), 0)

    depth = {middle: 0}
    for friend, _ in sorted(neighbours[middle], key=lambda tie: (-tie[1], tie[0]))[: max(0, limit - 1)]:
        depth[friend] = 1
    reach: dict[int, float] = {}
    for friend in [person for person, level in depth.items() if level == 1]:
        for other, weight in neighbours[friend]:
            if other not in depth:
                reach[other] = max(reach.get(other, 0.0), weight)
    for other, _ in sorted(reach.items(), key=lambda item: (-item[1], item[0]))[: max(0, limit - len(depth))]:
        depth[other] = 2

    shown = sorted(depth, key=lambda person: (depth[person], person))
    position = {person: k for k, person in enumerate(shown)}
    node = lambda i: {"id": nodes[i][0], "audience": nodes[i][1], "community": nodes[i][2], "ties": ties[i]}
    return {
        "graph_hash": stored.get("graph_hash"),
        "summary": {
            "personas": count,
            "ties": len(edges),
            "mean_ties": round(2 * len(edges) / count, 2) if count else 0.0,
            "most_ties": max(ties, default=0),
            "fewest_ties": min(ties, default=0),
            "audience_assortativity": stored.get("audience_assortativity"),
        },
        "checks": stored.get("checks", []),
        "degree_histogram": sorted(Counter(ties).items()),
        "hubs": [node(i) for i in sorted(range(count), key=lambda i: (-ties[i], nodes[i][0]))[:10]],
        "circle": {
            "center": nodes[middle][0] if count else None,
            "friends": len(neighbours[middle]) if count else 0,
            "friends_of_friends": len(reach),
            "nodes": [node(i) | {"depth": depth[i]} for i in shown],
            "edges": [[position[u], position[v], weight] for u, v, weight in edges if u in depth and v in depth],
        },
    }
