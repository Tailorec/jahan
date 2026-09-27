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
    text_would_add: dict[str, int]

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "quota": self.quota,
            "head_count": self.head_count,
            "by_source": dict(self.by_source),
            "dominant_source": self.dominant_source,
            "filter_costs": dict(self.filter_costs),
            "empty_note": self.empty_note,
            "text_would_add": dict(self.text_would_add),
        }


# Sources whose rows were read from text rather than answered, so every field
# they carry is extracted. Off by default, labelled wherever they are counted.
TEXT_SOURCES = ("amazon", "wiki")
TEXT_LABEL = "read by a model from text, not surveyed"


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
        would_add = {}
        for text_source in TEXT_SOURCES:
            if text_source in matrix.sources and text_source not in sources:
                wider = _apply_filters(matrix, positions, matrix.pool_mask(tuple([*sources, text_source]), tuple(required)), filters)
                would_add[text_source] = int(wider.sum()) - head_count
        out.append(AudienceHeadCount(
            name=name,
            quota=quota,
            head_count=head_count,
            by_source=by_source,
            dominant_source=dominant,
            filter_costs=filter_costs,
            empty_note=_empty_note(matrix, positions, base, filters) if not head_count and filters else None,
            text_would_add=would_add,
        ))
    return out


def _apply_filters(matrix, positions, base, filters):
    mask = base
    for attribute, values in filters.items():
        codes = _codes_of(matrix, attribute, tuple(values))
        mask = mask & np.isin(matrix.codes[positions[attribute]], list(codes))
    return mask


def assumption_entries(matrix, sources, required, audiences, previews) -> list[dict]:
    """The brief's assumption-ledger entries this draft writes: admitting a
    text source, and audiences drawn mostly from different surveys. Each
    validates as the engine's `Assumption` with source `assumed`."""
    from simcore.population._pool import describe_pool

    entries = []
    widened = describe_pool(matrix, tuple(sources), tuple(required))
    for text_source in TEXT_SOURCES:
        if text_source in sources and text_source in matrix.sources:
            contributed = widened.pool_by_source.get(text_source, 0)
            entries.append({
                "text": (
                    f"{text_source} is admitted: {contributed} of "
                    f"{widened.pool} candidate-pool personas come from {text_source}, "
                    f"whose answers were {TEXT_LABEL}"
                ),
                "source": "assumed",
            })
    dominant = [(audience.get("name") or "audience", preview.dominant_source) for audience, preview in zip(audiences, previews)]
    dominant = [(name, source) for name, source in dominant if source is not None]
    for first in range(len(dominant)):
        for second in range(first + 1, len(dominant)):
            (name_a, source_a), (name_b, source_b) = dominant[first], dominant[second]
            if source_a != source_b:
                entries.append({
                    "text": (
                        f"differences between {name_a} and {name_b} are treated as differences "
                        f"between people, not between the {source_a} and {source_b} surveys"
                    ),
                    "source": "assumed",
                })
    return entries


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
