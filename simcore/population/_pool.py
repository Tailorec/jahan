"""The candidate pool: who can be drawn at all, and what each requirement costs.

The personas a study can be drawn from are rows from its admitted sources
that carry every attribute of the category's conditioning set, before any
audience filter is applied. Every count here is vector work over the persona
value matrix; `web` serialises the result and the interface renders it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RequirementCost:
    """What one requirement removes: the pool without it, what it takes away
    per source, and the surveys it empties entirely, named."""

    attribute: str
    pool_without: int
    removes: int
    removes_by_source: dict[str, int]
    emptied_sources: tuple[str, ...]


@dataclass(frozen=True)
class CandidatePool:
    """Everyone who carries every required attribute, per source — and what
    each requirement costs, including when it removes a whole survey."""

    sources_total: int
    sources_by_source: dict[str, int]
    pool: int
    pool_by_source: dict[str, int]
    costs: tuple[RequirementCost, ...]

    def to_json(self) -> dict:
        return {
            "sources_total": self.sources_total,
            "sources_by_source": dict(self.sources_by_source),
            "pool": self.pool,
            "pool_by_source": dict(self.pool_by_source),
            "costs": [
                {
                    "attribute": cost.attribute,
                    "pool_without": cost.pool_without,
                    "removes": cost.removes,
                    "removes_by_source": dict(cost.removes_by_source),
                    "emptied_sources": list(cost.emptied_sources),
                }
                for cost in self.costs
            ],
        }


def describe_pool(matrix, sources: tuple[str, ...], required: tuple[str, ...]) -> CandidatePool:
    """The candidate pool for `sources` and `required`, with each cost."""
    unknown = sorted(set(required) - set(matrix.attributes))
    if unknown:
        raise ValueError(f"the corpus carries no such attribute: {', '.join(unknown)}")
    unknown_sources = sorted(set(sources) - set(matrix.sources))
    if unknown_sources:
        raise ValueError(f"the corpus carries no such source: {', '.join(unknown_sources)}")
    base = matrix.pool_mask(tuple(sources), tuple(required))
    pool_by_source = matrix.by_source(base)
    costs = []
    for attribute in required:
        rest = tuple(other for other in required if other != attribute)
        without = matrix.pool_mask(tuple(sources), rest)
        without_by_source = matrix.by_source(without)
        removes = {name: count - pool_by_source.get(name, 0) for name, count in without_by_source.items()}
        removes = {name: count for name, count in removes.items() if count > 0}
        emptied = tuple(
            name for name, count in without_by_source.items()
            if count and not pool_by_source.get(name)
        )
        costs.append(RequirementCost(
            attribute=attribute,
            pool_without=int(without.sum()),
            removes=int(without.sum() - int(base.sum())),
            removes_by_source=removes,
            emptied_sources=emptied,
        ))
    everyone = matrix.pool_mask(tuple(sources), ())
    return CandidatePool(
        sources_total=int(everyone.sum()),
        sources_by_source=matrix.by_source(everyone),
        pool=int(base.sum()),
        pool_by_source=pool_by_source,
        costs=tuple(costs),
    )


def value_counts(matrix, sources: tuple[str, ...], required: tuple[str, ...], attribute: str) -> list[dict]:
    """Every value of `attribute` with its count per source among the candidate
    pool — what the value picker ticks, never typed."""
    if attribute not in matrix.attributes:
        raise ValueError(f"the corpus carries no such attribute: {attribute}")
    unknown_sources = sorted(set(sources) - set(matrix.sources))
    if unknown_sources:
        raise ValueError(f"the corpus carries no such source: {', '.join(unknown_sources)}")
    unknown_required = sorted(set(required) - set(matrix.attributes))
    if unknown_required:
        raise ValueError(f"the corpus carries no such attribute: {', '.join(unknown_required)}")
    import numpy as np

    base = matrix.pool_mask(tuple(sources), tuple(required))
    position = matrix.attributes.index(attribute)
    column = matrix.codes[position]
    vocabulary = matrix.vocabulary[attribute]
    out = []
    for code, value in enumerate(vocabulary):
        hit = base & (column == code)
        out.append({"value": value, "n": int(hit.sum()), "by_source": matrix.by_source(hit)})
    return out


_GENERIC = frozenset({"status", "level", "type", "frequency", "attitude", "interest", "skill", "familiarity", "value", "habit", "the", "and", "for"})


def alternatives(matrix, codebook, sources: tuple[str, ...], attribute: str, limit: int = 3, embeddings=None) -> list[dict]:
    """The other ways the corpus asks the same question, with how many people in `sources` answered each.

    Neighbours by meaning when attribute embeddings exist, else by words shared in the labels. Two
    attributes with the same value list are skipped: that is a shared wording template (Prudence and
    Curiosity both run Signature … Absent), not the same question.
    """
    import re

    import numpy as np

    from simcore.brief._codebook import kind_of, measures_of

    if attribute not in matrix.attributes:
        raise ValueError(f"the corpus carries no such attribute: {attribute}")
    if embeddings is not None and attribute in embeddings["ids"]:
        ids = embeddings["ids"]
        similarity = embeddings["vectors"] @ embeddings["vectors"][ids.index(attribute)]
        ranked = [ids[int(j)] for j in np.argsort(-similarity)]
    else:
        # ponytail: shared label words only; embeddings are the real answer and are built in the background
        def words_of(name: str) -> set[str]:
            return {word for word in re.split(r"[^a-z0-9]+", codebook.label(name).lower()) if len(word) > 2} - _GENERIC

        wanted = words_of(attribute)
        scored = [(-len(wanted & words_of(other)), other) for other in matrix.attributes if wanted & words_of(other)]
        ranked = [other for _, other in sorted(scored)]
    own_values = tuple(codebook.vocabulary(attribute) or ())
    present_rows = matrix.pool_mask(tuple(sources), ())
    out = []
    for other in ranked:
        if other == attribute or other not in matrix.attributes or tuple(codebook.vocabulary(other) or ()) == own_values:
            continue
        hit = present_rows & (matrix.codes[matrix.attributes.index(other)] != -1)
        if not hit.any():
            continue
        out.append({
            "id": other,
            "label": codebook.label(other),
            "category": codebook.category(other),
            "measures": measures_of(other, codebook.label(other), codebook.category(other)),
            "kind": kind_of(other, codebook.label(other), codebook.category(other)),
            "n": int(hit.sum()),
            "by_source": matrix.by_source(hit),
        })
        if len(out) == limit:
            break
    return out
