"""Audience head counts against quotas, from the persona value matrix.

For each audience in a draft: how many people match, against its quota at
the study size; where they come from; and which filter is shrinking it and by
how much. An audience that matches nobody says so in words — the people
holding one of its answers never gave another — rather than showing zero
alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AudienceHeadCount:
    """One audience's count: head count against quota, source mix, and what
    each filter costs. Counts only; wording lives in the interface."""

    name: str
    quota: int
    head_count: int
    by_source: dict[str, int]
    dominant_source: str | None
    filter_costs: dict[str, int]
    empty_note: str | None

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "quota": self.quota,
            "head_count": self.head_count,
            "by_source": dict(self.by_source),
            "dominant_source": self.dominant_source,
            "filter_costs": dict(self.filter_costs),
            "empty_note": self.empty_note,
        }


def _codes_of(matrix, attribute: str, values: tuple[str, ...]) -> set[int]:
    vocabulary = matrix.vocabulary.get(attribute)
    if vocabulary is None:
        raise ValueError(f"the corpus carries no such attribute: {attribute}")
    index_of = {value: code for code, value in enumerate(vocabulary)}
    outside = sorted(set(values) - set(index_of))
    if outside:
        raise ValueError(
            f"{attribute} carries no such value: {outside}; the codebook holds {list(vocabulary)}"
        )
    return {index_of[value] for value in values}


def preview_audiences(matrix, sources, required, audiences, study_size: int) -> list[AudienceHeadCount]:
    """Head counts for `audiences`, each `{name, share, filters}` with filters
    `{attribute: [values]}`. Quota is share of the study size."""
    if study_size < 1:
        raise ValueError(f"a study size counts at least one persona, got {study_size}")
    unknown_sources = sorted(set(sources) - set(matrix.sources))
    if unknown_sources:
        raise ValueError(f"the corpus carries no such source: {', '.join(unknown_sources)}")
    unknown_required = sorted(set(required) - set(matrix.attributes))
    if unknown_required:
        raise ValueError(f"the corpus carries no such attribute: {', '.join(unknown_required)}")
    base = matrix.pool_mask(tuple(sources), tuple(required))
    positions = {attribute: position for position, attribute in enumerate(matrix.attributes)}
    counts = len(audiences) or 1
    out = []
    for audience in audiences:
        name = audience.get("name") or "audience"
        share = audience.get("share")
        quota = math.ceil((share if isinstance(share, (int, float)) and share > 0 else 1 / counts) * study_size)
        filters = audience.get("filters") or {}
        mask = base
        for attribute, values in filters.items():
            codes = _codes_of(matrix, attribute, tuple(values))
            column = matrix.codes[positions[attribute]]
            mask = mask & np.isin(column, list(codes))
        head_count = int(mask.sum())
        by_source = matrix.by_source(mask)
        total = head_count or 1
        dominant = None
        for source, count in by_source.items():
            if count / total >= 0.8:
                dominant = source
        filter_costs = {}
        for attribute in filters:
            others = {other: values for other, values in filters.items() if other != attribute}
            remaining = base
            for other, values in others.items():
                codes = _codes_of(matrix, other, tuple(values))
                remaining = remaining & np.isin(matrix.codes[positions[other]], list(codes))
            filter_costs[attribute] = int(remaining.sum())
        out.append(AudienceHeadCount(
            name=name,
            quota=quota,
            head_count=head_count,
            by_source=by_source,
            dominant_source=dominant,
            filter_costs=filter_costs,
            empty_note=_empty_note(matrix, positions, base, filters) if not head_count and filters else None,
        ))
    return out


def _empty_note(matrix, positions, base, filters) -> str | None:
    """Why an audience matches nobody: the pair of answers nobody holds together."""
    holders: dict[tuple[str, str], np.ndarray] = {}
    for attribute, values in filters.items():
        for value in values:
            code = matrix.vocabulary[attribute].index(value)
            holders[(attribute, value)] = base & (matrix.codes[positions[attribute]] == code)
    empties = [key for key, mask in holders.items() if not int(mask.sum())]
    if empties:
        attribute, value = empties[0]
        return f"nobody in your sources holds {value!r} for {attribute} — the people holding one of its answers never gave another"
    keys = list(holders)
    for first in range(len(keys)):
        for second in range(first + 1, len(keys)):
            if not int((holders[keys[first]] & holders[keys[second]]).sum()):
                (attr_a, val_a), (attr_b, val_b) = keys[first], keys[second]
                return (
                    f"the people holding {val_a!r} for {attr_a} never gave {val_b!r} for {attr_b}"
                )
    return "nobody in your sources holds this combination — the people holding one of its answers never gave another"
