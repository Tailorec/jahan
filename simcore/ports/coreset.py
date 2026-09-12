"""The `CoresetSource` protocol: the seam through which the engine reaches persona rows.

A source yields decoded rows, never packed bytes — the packed format belongs to the dataset adapter
that does not exist yet (§12). Its vocabulary, its value ordering and the values each attribute can
take are the adapter's knowledge, so nothing above it learns the dataset's encoding.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    AttributeValue,
    BandRange,
    Exactly,
    OneOf,
    PersonaSource,
)

RowId = str


@dataclass(frozen=True)
class DecodedRow:
    """One dataset row as the engine consumes it: the corpus it came from, and the attribute values
    it carries. An attribute absent from `values` was never populated on this row."""

    row_id: RowId
    source: PersonaSource
    values: Mapping[AttributeId, AttributeValue]


@runtime_checkable
class CoresetSource(Protocol):
    """Three questions: which rows match, what they contain, and what values an attribute can take.

    `matching` carries both the predicates and the attributes that must be populated, so eligibility
    can never be requested without stating the conditioning set it rests on (ADR 0002)."""

    def matching(
        self, predicates: Mapping[AttributeId, AttributeFilter], present: Iterable[AttributeId]
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
        self, predicates: Mapping[AttributeId, AttributeFilter], present: Iterable[AttributeId]
    ) -> tuple[RowId, ...]:
        present = tuple(present)
        self._require_known([*predicates, *present])
        required = set(present)
        selected = []
        for row in self._rows:
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
