"""The index-backed catalog: coverage and counts answered from a compact postings index, never a shard.

`preview()` is typed to `CoresetCatalog`, so the whole value of M3.5's pre-flight — that audience
exploration costs megabytes, not gigabytes — depends on there being a catalog that answers from an index
rather than by holding rows. This is that catalog: it materialises, once, the per-value posting sets and
coverage counts for a chosen attribute set, and thereafter reads nothing but its own structures. The
release ships this as `postings.sqlite`; it is rebuilt from a source here so the shape and the guarantee
are proven in this repository, and a shard-backed index can be dropped in beside it unchanged."""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

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


# --- persistence: build once from the shards, answer from the cache thereafter ----------------------

INDEX_FORMAT = 1
INDEX_DIRECTORY = "consumersim-index"


def cached_hf_index(hf_source, attributes: Iterable[AttributeId], sources: Sequence[PersonaSource] | None = None) -> IndexCoresetCatalog:
    """The index for these attributes and sources, loaded from the cache when a valid one exists and built
    from the shards — then saved — only when none does.

    This is what makes a preview cheap after the first: loading reads the manifest and the saved index,
    never a shard. The saved index is keyed by the manifest's shard digests, so a changed release builds a
    new one rather than answering from a stale one, and its own digest is verified on every load."""
    fingerprint = _fingerprint(hf_source, attributes, sources)
    path = _index_path(hf_source.cache_dir, fingerprint)
    loaded = load_index(path, fingerprint)
    if loaded is not None:
        return loaded
    built = from_hf_source(hf_source, attributes, sources=sources)
    save_index(built, path, fingerprint)
    return built


def save_index(catalog: IndexCoresetCatalog, path: Path, fingerprint: Mapping[str, object]) -> None:
    """Write an index as a postings archive and a JSON sidecar recording what it indexes and its digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    present_keys, value_keys = [], []
    for position, ((source, attribute), rows) in enumerate(sorted(catalog._present.items())):
        arrays[f"p{position}"] = np.asarray(sorted(rows), dtype=np.int64)
        present_keys.append([source, attribute])
    position = 0
    for (source, attribute), by_value in sorted(catalog._value.items()):
        for value, rows in sorted(by_value.items()):
            arrays[f"v{position}"] = np.asarray(sorted(rows), dtype=np.int64)
            value_keys.append([source, attribute, value])
            position += 1
    archive = path.with_suffix(".npz")
    partial = archive.with_suffix(".partial.npz")
    np.savez_compressed(partial, **arrays)
    partial.replace(archive)
    sidecar = {
        "format": INDEX_FORMAT,
        "fingerprint": fingerprint,
        "sha256": _digest(archive),
        "admitted_sources": list(catalog.admitted_sources),
        "totals": dict(catalog.totals),
        "vocabulary": {attribute: list(values) for attribute, values in catalog.vocabulary.items()},
        "coverage": {attribute: {source: asdict(cell) for source, cell in by_source.items()} for attribute, by_source in catalog._coverage.items()},
        "present": present_keys,
        "values": value_keys,
    }
    path.with_suffix(".json").write_text(json.dumps(sidecar, sort_keys=True), encoding="utf-8")


def load_index(path: Path, fingerprint: Mapping[str, object]) -> IndexCoresetCatalog | None:
    """A saved index, or nothing when there is none or it was built for different inputs. An archive whose
    digest no longer matches its sidecar is refused, as a cached shard would be."""
    sidecar_path, archive = path.with_suffix(".json"), path.with_suffix(".npz")
    if not (sidecar_path.is_file() and archive.is_file()):
        return None
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if sidecar.get("format") != INDEX_FORMAT or sidecar.get("fingerprint") != json.loads(json.dumps(fingerprint)):
        return None
    if _digest(archive) != sidecar["sha256"]:
        from .hf import ShardMismatch

        raise ShardMismatch(f"the saved index {str(archive)!r} does not match its recorded digest; delete it to rebuild")
    with np.load(archive) as arrays:
        present = {(source, attribute): frozenset(arrays[f"p{i}"].tolist()) for i, (source, attribute) in enumerate(sidecar["present"])}
        value: dict[tuple[PersonaSource, AttributeId], dict[AttributeValue, frozenset[int]]] = {}
        for i, (source, attribute, label) in enumerate(sidecar["values"]):
            value.setdefault((source, attribute), {})[label] = frozenset(arrays[f"v{i}"].tolist())
    return IndexCoresetCatalog(
        admitted_sources=tuple(sidecar["admitted_sources"]),
        totals=dict(sidecar["totals"]),
        vocabulary={attribute: tuple(values) for attribute, values in sidecar["vocabulary"].items()},
        _coverage={
            attribute: {source: AttributeCoverage(**cell) for source, cell in by_source.items()}
            for attribute, by_source in sidecar["coverage"].items()
        },
        _present=present,
        _value=value,
    )


def _fingerprint(hf_source, attributes: Iterable[AttributeId], sources: Sequence[PersonaSource] | None) -> dict[str, object]:
    return {
        "attributes": sorted(attributes),
        "sources": sorted(sources) if sources is not None else None,
        "shards": {str(path): str(entry.get("sha256", "")) for path, entry in sorted(hf_source._entries.items())},
    }


def _index_path(cache_dir: Path, fingerprint: Mapping[str, object]) -> Path:
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / INDEX_DIRECTORY / f"catalog-{key}"


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()
