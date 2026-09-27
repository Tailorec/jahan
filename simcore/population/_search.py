"""Codebook search: by words, or by meaning with near-empty attributes sunk.

Meaning decides; an attribute almost nobody carries sinks below comparably
relevant ones people do. Each result shows how well it matches, how many
people answered it and from which sources, and what requiring it would do to
the pool. Until embeddings exist — and without an endpoint — search is by
words, and the answer says so.
"""

from __future__ import annotations

import numpy as np


def _shares(matrix, sources: tuple[str, ...]) -> np.ndarray:
    """Each attribute's share of the chosen sources' people carrying it."""
    index_of = {name: position for position, name in enumerate(matrix.sources)}
    chosen = [index_of[name] for name in sources if name in index_of]
    total = sum(matrix.totals.get(name, 0) for name in sources if name in matrix.totals)
    if not chosen or not total:
        return np.zeros(len(matrix.attributes), dtype=np.float64)
    present = np.zeros(len(matrix.attributes), dtype=np.float64)
    for position in range(len(matrix.attributes)):
        column = matrix.codes[position] != -1
        present[position] = sum(int((column & (matrix.row_source == source)).sum()) for source in chosen)
    return present / total


def search_attributes(codebook, matrix, query: str, sources, required, mode: str, embeddings, offset: int = 0, limit: int | None = None) -> dict:
    """Ranked attribute cards for `query` over the codebook — cards only for the page asked for,
    since each card counts over the whole matrix."""
    from simcore.brief._codebook import kind_of, measures_of, word_search
    from simcore.ports.embeddings import endpoint_base, rank_meaning

    sources = tuple(sources)
    required = tuple(required)
    base = matrix.pool_mask(sources, required)
    base_counts = matrix.by_source(base)
    used = "words"
    relevance_of: dict[str, float | None] = {}
    if query.strip() and mode == "meaning" and embeddings is not None and endpoint_base() is not None:
        try:
            from simcore.ports.embeddings import _embed, embed_model

            vector = _embed([query.strip().lower()], embed_model(), endpoint_base() or "")[0]
            norm = float(np.linalg.norm(vector)) or 1.0
            vector = (np.asarray(vector, dtype=np.float32) / norm).tolist()
            relevance, score = rank_meaning(vector, embeddings, _shares(matrix, sources))
            order = [int(i) for i in np.argsort(-score) if matrix.attributes[int(i)] not in required]
            ordered = [matrix.attributes[position] for position in order]
            for position in order:
                relevance_of[matrix.attributes[position]] = round(float(relevance[position]), 4)
            used = "meaning"
        except Exception:
            used = "words (search by meaning is unavailable — searching by words)"
    if used.startswith("words") and query.strip():
        ordered = [attribute for attribute in word_search(query, codebook, limit=len(codebook.attributes)) if attribute not in required]
        for attribute in ordered:
            relevance_of.setdefault(attribute, None)
    elif used.startswith("words"):
        shares = _shares(matrix, sources)
        ordered = [matrix.attributes[int(i)] for i in np.argsort(-shares) if matrix.attributes[int(i)] not in required]
    page = ordered[offset:] if limit is None else ordered[offset:offset + limit]
    cards = [_card(matrix, codebook, sources, required, base, base_counts, attribute, relevance_of.get(attribute))
             for attribute in page]
    return {"results": cards, "total": len(ordered), "mode": used}


def _card(matrix, codebook, sources, required, base, base_counts, attribute: str, relevance) -> dict:
    from simcore.brief._codebook import domain_of, kind_of, looks_ordered, measures_of

    position = matrix.attributes.index(attribute)
    everyone = matrix.pool_mask(sources, ())
    answered = everyone & (matrix.codes[position] != -1)
    present = int(answered.sum())
    total = int(everyone.sum())
    after = base & (matrix.codes[position] != -1)
    after_counts = matrix.by_source(after)
    lost = {name: count - after_counts.get(name, 0) for name, count in base_counts.items()}
    lost = {name: count for name, count in lost.items() if count > 0}
    wiped = [name for name, count in base_counts.items() if count and not after_counts.get(name)]
    return {
        "id": attribute,
        "label": codebook.label(attribute),
        "category": codebook.category(attribute),
        "domain": domain_of(attribute, codebook.label(attribute), codebook.category(attribute)),
        "measures": measures_of(attribute, codebook.label(attribute), codebook.category(attribute)),
        "kind": kind_of(attribute, codebook.label(attribute), codebook.category(attribute)),
        "values": list(codebook.vocabulary(attribute) or ()),
        "ordered": looks_ordered(codebook.vocabulary(attribute) or ()),
        "relevance": relevance,
        "present": present,
        "total": total,
        "share": round(present / total, 5) if total else 0.0,
        "carry_by_source": matrix.by_source(answered),
        "if_required": {
            "pool": int(after.sum()),
            "by_source": after_counts,
            "lost": lost,
            "wiped_sources": wiped,
        },
    }
