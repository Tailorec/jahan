"""The `CoresetSource` protocol: the seam through which the engine reaches persona rows.

A source yields decoded rows, never packed bytes — the packed format belongs to the dataset adapter
that does not exist yet (§12). Its vocabulary, its value ordering and the values each attribute can
take are the adapter's knowledge, so nothing above it learns the dataset's encoding.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    AttributeValue,
    BandRange,
    Exactly,
    FieldOrigin,
    OneOf,
    PersonaSource,
)

from .catalog import AttributeCoverage

RowId = str


@dataclass(frozen=True)
class DecodedRow:
    """One dataset row as the engine consumes it: the corpus it came from, the attribute values it
    carries, and the tier each value's origin carries. An attribute absent from `values` was never
    populated on this row; one absent from `tiers` was recorded by an instrument (`MEASURED`)."""

    row_id: RowId
    source: PersonaSource
    values: Mapping[AttributeId, AttributeValue]
    tiers: Mapping[AttributeId, FieldOrigin] = field(default_factory=dict)


@runtime_checkable
class CoresetSource(Protocol):
    """Three questions: which rows match, what they contain, and what values an attribute can take.

    `matching` carries both the predicates and the attributes that must be populated, so eligibility
    can never be requested without stating the conditioning set it rests on (ADR 0002). `sources`, when
    given, restricts eligibility to those sources at the same point — a source a study does not admit
    must be excluded before sampling, never discarded after it, or the draw silently comes up short."""

    def matching(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        sources: Iterable[PersonaSource] | None = None,
    ) -> tuple[RowId, ...]: ...

    def rows(self, ids: Iterable[RowId]) -> Iterator[DecodedRow]: ...

    def values(self, attribute: AttributeId) -> tuple[AttributeValue, ...]: ...


def matches(predicate: AttributeFilter, value: AttributeValue, order: Sequence[AttributeValue]) -> bool:
    """Whether one decoded value satisfies a predicate, judged against the source's value order.

    A band range reads its position in the declared order, so the source's vocabulary is the only
    thing that decides what "from weekly to 3_plus_weekly" includes."""
    if isinstance(predicate, Exactly):
        return value == predicate.value
    if isinstance(predicate, OneOf):
        return value in predicate.values
    assert isinstance(predicate, BandRange)
    if value not in order or predicate.first not in order or predicate.last not in order:
        return False
    return order.index(predicate.first) <= order.index(value) <= order.index(predicate.last)


class _DecodedRowSource:
    """The behaviour every in-repository source shares: an ordered vocabulary and an in-memory store.

    The real dataset adapter will answer the same three questions without holding every row, but it
    lives elsewhere (§12); these two sources are what the suite and the quickstart run against."""

    def __init__(
        self,
        rows: Iterable[DecodedRow],
        vocabulary: Mapping[AttributeId, Sequence[AttributeValue]],
    ) -> None:
        self._vocabulary = {attribute: tuple(values) for attribute, values in vocabulary.items()}
        self._rows = tuple(rows)
        self._by_id = {row.row_id: row for row in self._rows}
        if len(self._by_id) != len(self._rows):
            raise ValueError("row ids must be unique within a source")

    def _require_known(self, attributes: Iterable[AttributeId]) -> None:
        unknown = sorted(set(attributes) - set(self._vocabulary))
        if unknown:
            raise KeyError(f"the source does not know these attributes: {unknown}")

    def matching(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        sources: Iterable[PersonaSource] | None = None,
    ) -> tuple[RowId, ...]:
        present = tuple(present)
        self._require_known([*predicates, *present])
        required = set(present)
        admitted = None if sources is None else frozenset(sources)
        selected = []
        for row in self._rows:
            if admitted is not None and row.source not in admitted:
                continue
            if not required <= set(row.values):
                continue
            if all(
                attribute in row.values and matches(predicate, row.values[attribute], self._vocabulary[attribute])
                for attribute, predicate in predicates.items()
            ):
                selected.append(row.row_id)
        return tuple(selected)

    def rows(self, ids: Iterable[RowId]) -> Iterator[DecodedRow]:
        for row_id in ids:
            try:
                yield self._by_id[row_id]
            except KeyError:
                raise KeyError(f"the source has no row {row_id!r}") from None

    def values(self, attribute: AttributeId) -> tuple[AttributeValue, ...]:
        try:
            return self._vocabulary[attribute]
        except KeyError:
            raise KeyError(f"the source does not know attribute {attribute!r}") from None

    # --- the catalog seam: answers an index would give, scanned from memory because this source holds
    # every row. A real adapter implements these from postings; the shape of the answers is the contract.

    def sources(self) -> tuple[PersonaSource, ...]:
        return tuple(sorted({row.source for row in self._rows}))

    def attributes(self) -> tuple[AttributeId, ...]:
        return tuple(sorted(self._vocabulary))

    def coverage(
        self, attributes: Iterable[AttributeId], sources: Iterable[PersonaSource]
    ) -> Mapping[AttributeId, Mapping[PersonaSource, AttributeCoverage]]:
        attributes, sources = tuple(attributes), tuple(sources)
        result: dict[AttributeId, Mapping[PersonaSource, AttributeCoverage]] = {}
        for attribute in attributes:
            per_source: dict[PersonaSource, AttributeCoverage] = {}
            for source in sources:
                rows = [row for row in self._rows if row.source == source]
                carried = [row for row in rows if attribute in row.values]
                per_source[source] = AttributeCoverage(
                    total=len(rows),
                    present=len(carried),
                    measured=sum(row.tiers.get(attribute, FieldOrigin.MEASURED) is FieldOrigin.MEASURED for row in carried),
                    extracted=sum(row.tiers.get(attribute, FieldOrigin.MEASURED) is FieldOrigin.EXTRACTED for row in carried),
                    synthesized=sum(row.tiers.get(attribute, FieldOrigin.MEASURED) is FieldOrigin.SYNTHESIZED for row in carried),
                    calibrated=sum(row.tiers.get(attribute, FieldOrigin.MEASURED) is FieldOrigin.CALIBRATED for row in carried),
                )
            result[attribute] = per_source
        return result

    def count(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        by_source: bool = True,
    ) -> Mapping[PersonaSource, int] | int:
        # The catalog reports zeros, never refusals: a predicate or requirement on an attribute the
        # source does not know matches no row, which is the answer a preview exists to show.
        known = set(self._vocabulary)
        if set(predicates) - known or set(present) - known:
            selected: tuple[str, ...] = ()
        else:
            selected = self.matching(predicates, present)
        if not by_source:
            return len(selected)
        counts: dict[PersonaSource, int] = {}
        for row_id in selected:
            source = self._by_id[row_id].source
            counts[source] = counts.get(source, 0) + 1
        return counts
