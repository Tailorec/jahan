"""Objection clusters: what personas objected to, grouped deterministically.

Verbatims are embedded once through the run's pinned embedding model and grouped by
cosine similarity at a recorded threshold, with ties broken from a derived seed. Each
cluster is labelled by its medoid — the verbatim nearest the centre, quoted as written.
No k-means, no generated summaries. Two runs over one trace produce one answer.
"""

import hashlib
from collections.abc import Sequence

import numpy as np

from simcore.schemas import ObjectionCluster, VerbatimGrouping, VerbatimRecord


def cluster_objections(view, *, embed, threshold: float = 0.75, seed: int = 0,
                       pinned_embed_model: str | None = None) -> tuple[ObjectionCluster, ...]:
    """Group one world's verbatims by embedding cosine similarity.

    The view supplies the verbatims; `embed` is the run's pinned embedding model, called
    exactly once with every verbatim in deterministic order. `threshold` is the recorded
    cosine-similarity parameter and travels on every cluster reported. When the run's pin
    is given, an embedding model other than the pin is refused: a digest cannot be computed
    in a different embedding space from the study it describes.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"clustering threshold lies in [0, 1], got {threshold}")
    if pinned_embed_model is not None and embed.model_id != pinned_embed_model:
        raise ValueError(
            f"the run pins {pinned_embed_model} for every embedding, "
            f"but clustering was asked through {embed.model_id}"
        )
    records = _ordered_verbatims(view)
    if not records:
        return ()
    vectors = _embed_once(embed, [record.text for record in records])
    components = _components(vectors, threshold)
    clusters = []
    for members in _ordered_components(components, records):
        medoid = _medoid(members, vectors, seed)
        member_ids = tuple(sorted(records[index].event_id for index in members))
        clusters.append(ObjectionCluster.model_validate({
            "label": records[medoid].text,
            "verbatim_trace_ids": member_ids,
            "size": len(members),
            "threshold": threshold,
            "embed_model_id": embed.model_id,
        }))
    return tuple(clusters)


def _ordered_verbatims(view) -> list[VerbatimRecord]:
    groups = view.verbatims(VerbatimGrouping.PERSONA)
    records = [record for group in groups for record in group.records]
    return sorted(records, key=lambda record: record.event_id)


def _embed_once(embed, texts: Sequence[str]) -> np.ndarray:
    result = embed.embed(texts)
    vectors = np.asarray(result.vectors, dtype=np.float64)
    if vectors.shape[0] != len(texts):
        raise ValueError(f"embedding returned {vectors.shape[0]} vectors for {len(texts)} verbatims")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


def _components(vectors: np.ndarray, threshold: float) -> list[int]:
    n = vectors.shape[0]
    parent = list(range(n))
    similarity = vectors @ vectors.T

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[max(root_i, root_j)] = min(root_i, root_j)

    for i in range(n):
        for j in range(i + 1, n):
            if float(similarity[i, j]) >= threshold:
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _ordered_components(components: list[list[int]], records: list[VerbatimRecord]) -> list[list[int]]:
    ordered = [sorted(members) for members in components]
    return sorted(ordered, key=lambda members: (-len(members), records[members[0]].event_id))


def _medoid(members: list[int], vectors: np.ndarray, seed: int) -> int:
    if len(members) == 1:
        return members[0]
    similarity = vectors[members] @ vectors[members].T
    distance = 1.0 - similarity
    totals = distance.sum(axis=1)
    best = min(totals)
    tied = [members[k] for k, total in enumerate(totals) if total == best]
    if len(tied) == 1:
        return tied[0]
    return min(tied, key=lambda index: _tie_key(index, seed))


def _tie_key(index: int, seed: int) -> str:
    return hashlib.sha256(f"{int(seed)}:{index}".encode("utf-8")).hexdigest()
