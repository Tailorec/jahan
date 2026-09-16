"""The index-backed catalog: coverage and counts answered from a compact postings index, never a shard.

`preview()` is typed to `CoresetCatalog`, so the whole value of M3.5's pre-flight — that audience
exploration costs megabytes, not gigabytes — depends on there being a catalog that answers from an index
rather than by holding rows. This is that catalog: it materialises, once, the per-value posting sets and
coverage counts for a chosen attribute set, and thereafter reads nothing but its own structures. The
release ships this as `postings.sqlite`; it is rebuilt from a source here so the shape and the guarantee
are proven in this repository, and a shard-backed index can be dropped in beside it unchanged."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from simcore.schemas import AttributeFilter, AttributeId, AttributeValue, BandRange, Exactly, FieldOrigin, OneOf, PersonaSource

from .catalog import AttributeCoverage
from .coreset import CoresetSource, DecodedRow


@dataclass
class IndexCoresetCatalog:
    """Coverage and counts for a fixed attribute set, answered from postings the constructor built once.

    After `from_source` or `from_hf_source` returns, the catalog holds no reference to any source or
    shard: it is a self-contained index, and `count`/`coverage` touch only its own tables."""

    admitted_sources: tuple[PersonaSource, ...]
    totals: Mapping[PersonaSource, int]
    vocabulary: Mapping[AttributeId, tuple[AttributeValue, ...]]
    _coverage: Mapping[AttributeId, Mapping[PersonaSource, AttributeCoverage]] = field(repr=False)
    _present: Mapping[tuple[PersonaSource, AttributeId], frozenset[int]] = field(repr=False)
    _value: Mapping[tuple[PersonaSource, AttributeId], Mapping[AttributeValue, frozenset[int]]] = field(repr=False)

    def sources(self) -> tuple[PersonaSource, ...]:
        return self.admitted_sources

    def attributes(self) -> tuple[AttributeId, ...]:
        return tuple(sorted(self.vocabulary))

    def values(self, attribute: AttributeId) -> tuple[AttributeValue, ...]:
        try:
            return self.vocabulary[attribute]
        except KeyError:
            raise KeyError(f"the index does not know attribute {attribute!r}") from None

    def coverage(self, attributes: Iterable[AttributeId], sources: Iterable[PersonaSource]):
        attributes, sources = tuple(attributes), tuple(sources)
        result = {}
        for attribute in attributes:
            per = {source: self._coverage.get(attribute, {}).get(source, AttributeCoverage(total=self.totals.get(source, 0), present=0)) for source in sources}
            result[attribute] = per
        return result

    def count(self, predicates, present, *, by_source: bool = True):
        present = tuple(present)
        per_source: dict[PersonaSource, int] = {}
        for source in self.sources():
            selected = self._matching_source(source, predicates, present)
            per_source[source] = selected
        if not by_source:
            return sum(per_source.values())
        return {source: count for source, count in per_source.items() if count}

    def _matching_source(self, source: PersonaSource, predicates: Mapping[AttributeId, AttributeFilter], present: Sequence[AttributeId]) -> int:
        universe = frozenset(range(self.totals.get(source, 0)))
        sets = [self._present.get((source, attribute), universe) for attribute in present]
        for attribute, predicate in predicates.items():
            values = self.vocabulary.get(attribute)
            if values is None:
                return 0
            allowed = _allowed_values(predicate, tuple(values))
            postings = self._value.get((source, attribute), {})
            hits: frozenset[int] = frozenset()
            for value in allowed:
                hits |= postings.get(value, frozenset())
            sets.append(hits)
        if not sets:
            return len(universe)
        result = sets[0]
        for other in sets[1:]:
            result &= other
            if not result:
                break
        return len(result)


def _allowed_values(predicate: AttributeFilter, values: tuple[AttributeValue, ...]) -> list[AttributeValue]:
    if isinstance(predicate, Exactly):
        return [predicate.value] if predicate.value in values else []
    if isinstance(predicate, OneOf):
        return [value for value in predicate.values if value in values]
    if isinstance(predicate, BandRange):
        if predicate.first not in values or predicate.last not in values:
            return []
        low, high = sorted((values.index(predicate.first), values.index(predicate.last)))
        return list(values[low : high + 1])
    return []


def from_source(source: CoresetSource, attributes: Iterable[AttributeId] | None = None) -> IndexCoresetCatalog:
    """Build the index by scanning a source's rows once — the synthetic source, a fixture, or anything
    already in memory. The result decouples every later coverage/counts question from that scan."""
    wanted = tuple(attributes) if attributes is not None else source.attributes()
    index = _IndexBuilder(wanted, source.values)
    for row in source.rows(source.matching({}, present=[])):
        index.add(row)
    return index.build()


def from_hf_source(hf_source, attributes: Iterable[AttributeId], sources: Sequence[PersonaSource] | None = None) -> IndexCoresetCatalog:
    """Build the index from the packed arrays of a real shard source, without decoding a persona.

    Presence, codes and each field's tier are read as numpy vectors — the tier from the source and the
    field's own assignment type, as a decoded row would carry it — so a hundred-thousand-row
    shard indexes in the time it takes to read its bytes rather than the time it would take to build a
    hundred thousand personas."""
    wanted = tuple(attributes)
    totals: dict[PersonaSource, int] = {}
    base: dict[PersonaSource, int] = {}
    coverage: dict[AttributeId, dict[PersonaSource, dict[str, int]]] = {a: {} for a in wanted}
    present: dict[tuple[PersonaSource, AttributeId], list[int]] = {}
    value: dict[tuple[PersonaSource, AttributeId], dict[AttributeValue, list[int]]] = {}
    vocabulary = {attribute: hf_source.values(attribute) for attribute in wanted}

    for entry in hf_source._entries.values():
        arrays = hf_source._arrays(_stem(entry["path"]))
        shard_sources = np.asarray(arrays.sources, dtype=object)
        admitted = np.ones(len(arrays.row_ids), dtype=bool) if sources is None else np.isin(shard_sources, np.asarray(tuple(sources), dtype=object))
        for source in sorted({str(s) for s in shard_sources[admitted]}):
            source_mask = admitted & (shard_sources == source)
            ordinals = np.cumsum(source_mask) - 1
            positions = ordinals[source_mask] + base.get(source, 0)
            totals[source] = totals.get(source, 0) + int(source_mask.sum())
            base[source] = totals[source]
            for attribute in wanted:
                labels = hf_source.labels(arrays, attribute)[source_mask]
                cell = coverage[attribute].setdefault(source, {"total": 0, "present": 0, "measured": 0, "extracted": 0, "synthesized": 0, "calibrated": 0, "unexpressible": 0})
                cell["total"] += int(source_mask.sum())
                cell["unexpressible"] += int(hf_source.unexpressible(arrays, attribute)[source_mask].sum())
                carried = labels != None  # noqa: E711 - numpy object-array presence test
                present_positions = positions[carried]
                cell["present"] += int(len(present_positions))
                # Graded per field, not per source: a survey source's inferred values are extracted.
                for tier, count in zip(*np.unique(hf_source.tiers(arrays, attribute)[source_mask][carried], return_counts=True)):
                    cell[tier.value] += int(count)
                present.setdefault((source, attribute), []).extend(present_positions.tolist())
                for label in np.unique(labels[carried]):
                    hits = positions[(labels == label) & carried]
                    value.setdefault((source, attribute), {}).setdefault(str(label), []).extend(hits.tolist())

    present_built = {key: frozenset(rows) for key, rows in present.items()}
    value_built = {key: {v: frozenset(rows) for v, rows in inner.items()} for key, inner in value.items()}
    coverage_built = {
        attribute: {source: _coverage_of(cell) for source, cell in by_source.items()}
        for attribute, by_source in coverage.items()
    }
    return IndexCoresetCatalog(
        admitted_sources=tuple(sorted(totals)),
        totals=totals,
        vocabulary=vocabulary,
        _coverage=coverage_built,
        _present=present_built,
        _value=value_built,
    )


def _coverage_of(cell: Mapping[str, int]) -> AttributeCoverage:
    return AttributeCoverage(
        total=cell["total"],
        present=cell["present"],
        measured=cell["measured"],
        extracted=cell["extracted"],
        synthesized=cell["synthesized"],
        calibrated=cell["calibrated"],
        unexpressible=cell.get("unexpressible", 0),
    )


def _stem(path: str) -> str:
    from pathlib import Path

    return Path(str(path)).stem


class _IndexBuilder:
    """Accumulates postings and coverage from decoded rows, then freezes them into a catalog. A row's
    position is its ordinal within its own source, so an unlisted requirement is read as a source's
    whole row set."""

    def __init__(self, attributes: Sequence[AttributeId], values_of) -> None:
        self._attributes = tuple(attributes)
        self._values_of = values_of
        self.totals: dict[PersonaSource, int] = {}
        self.coverage: dict[AttributeId, dict[PersonaSource, dict[str, int]]] = {a: {} for a in attributes}
        self.present: dict[tuple[PersonaSource, AttributeId], set[int]] = {}
        self.value: dict[tuple[PersonaSource, AttributeId], dict[AttributeValue, set[int]]] = {}
        self.seen: set[PersonaSource] = set()

    def add(self, row: DecodedRow) -> None:
        self.seen.add(row.source)
        position = self.totals.get(row.source, 0)
        self.totals[row.source] = position + 1
        for attribute in self._attributes:
            cell = self.coverage[attribute].setdefault(row.source, {"total": 0, "present": 0, "measured": 0, "extracted": 0, "synthesized": 0, "calibrated": 0})
            cell["total"] += 1
            if attribute in row.values:
                tier = row.tiers.get(attribute, FieldOrigin.MEASURED)
                self.present.setdefault((row.source, attribute), set()).add(position)
                cell["present"] += 1
                cell[tier.value] += 1
                self.value.setdefault((row.source, attribute), {}).setdefault(row.values[attribute], set()).add(position)

    def build(self) -> IndexCoresetCatalog:
        vocabulary = {attribute: tuple(self._values_of(attribute)) for attribute in self._attributes}
        coverage = {attribute: {source: _coverage_of(cell) for source, cell in by_source.items()} for attribute, by_source in self.coverage.items()}
        present = {key: frozenset(rows) for key, rows in self.present.items()}
        value = {key: {v: frozenset(rows) for v, rows in inner.items()} for key, inner in self.value.items()}
        return IndexCoresetCatalog(
            admitted_sources=tuple(sorted(self.seen)),
            totals=self.totals,
            vocabulary=vocabulary,
            _coverage=coverage,
            _present=present,
            _value=value,
        )
