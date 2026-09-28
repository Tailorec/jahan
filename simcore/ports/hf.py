"""The corpus, readable: rows from real shards, fetched explicitly and verified on every use.

The adapter owns dataset knowledge (ADR 0016): the packed decoding, the mapping from source and
assignment type to a tier, and the layout of the release. A row's source is the release's own `source`
column — read, never inferred from the shape of its identifiers. Nothing here downloads a shard: an absent file raises with the exact command that fetches it.
Every cached file is verified against `manifest.json` when it is opened, not only at fetch, because a
partial write, a corrupted read, or a substituted file must never reach a study.

Eligibility is answered from the packed arrays with numpy — presence and codes, never a row decode —
so a study against a 100,000-row shard scans bytes rather than materialising a hundred thousand
personas; only the rows a draw actually selects are decoded."""

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    AttributeValue,
    BandRange,
    Exactly,
    FieldOrigin,
    FrozenDict,
    OneOf,
    PersonaSource,
)

from .coreset import DecodedRow
from .decoder import Codebook, _resolve_override, decode_row, is_unexpressible

REPO = "MatrAIx2026/MatrAIx_Persona_1M_Public_Release"
DEFAULT_CODEBOOK = "persona_codes.schema.json"
DEFAULT_MANIFEST = "manifest.json"


def default_cache_dir(repo: str = REPO) -> Path:
    """Where a fetched release lives: a user cache directory, never the repository."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "consumersim" / "coreset" / repo.replace("/", "__")

# The tier cannot be read from the source alone (`gss` and `amazon` both report `direct`) or from the
# assignment type alone (`wiki` varies within a source). It is read from the pair (ADR 0017): a survey
# source's value is measured when the instrument recorded it — `direct`, a `structured_claim` mapped from
# answers, or no grounding entry at all, which is how `real_human_survey` records every field — and
# extracted when a model inferred it (`summary_inference`, `unsupported`): 15% of Stack Overflow's
# `att_ai` is inferred. A text source is read by a model whatever the assignment says. A source the
# adapter does not know is never granted a measured claim by default.
_SURVEY_SOURCES = frozenset({"gss", "stackoverflow", "prism", "real_human_survey"})
_TEXT_SOURCES = frozenset({"wiki", "amazon"})
_RECORDED_ASSIGNMENTS = frozenset({"direct", "structured_claim"})


def tier_for(source: PersonaSource, assignment_type: str | None) -> FieldOrigin:
    """Grade one field's value from the source it came from and the way it was assigned."""
    if source == "synthetic":
        return FieldOrigin.SYNTHESIZED
    if source in _SURVEY_SOURCES and (assignment_type is None or assignment_type in _RECORDED_ASSIGNMENTS):
        return FieldOrigin.MEASURED
    return FieldOrigin.EXTRACTED


class MissingShard(FileNotFoundError):
    """A shard the study needs is not cached; the refusal names the command that fetches it, so no
    download is ever implicit and the reader can act without looking the command up."""


class ShardMismatch(ValueError):
    """A cached shard does not match the manifest's digest: the file was truncated, substituted, or
    corrupted since it was fetched. Refused rather than quietly read."""


@dataclass
class _ShardArrays:
    """One loaded shard held as packed bytes, so eligibility is answered without decoding a row."""

    row_ids: tuple[str, ...]
    attributes: np.ndarray  # uint8 [rows, row_bytes]
    bitmap: np.ndarray | None  # uint8 [rows, bitmap_bytes] or None when every field is present
    vocabulary_sizes: np.ndarray  # int16 [fields]: how many values each code may take
    sources: np.ndarray  # object [rows]: each row's source, from the release's `source` column
    counts: np.ndarray  # int32 [rows]: the release's own populated-attribute count per row
    overrides: Mapping[int, Mapping[int, str]]  # field_index -> row -> raw override value
    inferred: Mapping[int, np.ndarray]  # field_index -> rows whose grounding says a model inferred it
    labels: dict = field(default_factory=dict)  # attribute -> decoded-label array, cached
    unexpressible: dict = field(default_factory=dict)  # attribute -> rows whose override the vocabulary cannot express

    def inferred_at(self, field_index: int, row: int) -> bool:
        """Whether this row's grounding named an assignment other than a recorded one.

        Searched, never indexed: a field can be inferred on most of a shard's hundred thousand
        rows and a shard carries 1,290 fields, so a set of row numbers per field is memory the
        machine does not have. `inferred` holds each field's rows ascending, so a binary search
        answers in logarithmic time and allocates nothing."""
        rows = self.inferred.get(field_index)
        if rows is None or not len(rows):
            return False
        position = int(np.searchsorted(rows, row))
        return position < len(rows) and int(rows[position]) == row


class HfCoresetSource:
    """Rows from the real shards, cached outside the repository and verified on every open.

    `cache_dir` is the release's root, holding `manifest.json`, the codebook and `data/*.parquet`.
    When `shards` is given the source reads only those, which is how a study naming one source reaches
    one shard; a named-but-absent shard raises `MissingShard` with the fetch command.

    Eligibility treats presence and predicates from the packed codes; a field an override folds to
    missing is vanishingly rare on a conditioning attribute and is caught by projection's invariant."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        shards: Sequence[str] | None = None,
        codebook: Path | None = None,
        manifest: Path | None = None,
        sources: Sequence[PersonaSource] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.repo = REPO
        self.admissible = tuple(sources) if sources is not None else None
        manifest_path = manifest or self.cache_dir / DEFAULT_MANIFEST
        if not manifest_path.is_file():
            raise MissingShard(
                f"the coreset manifest {str(manifest_path)!r} is not cached; fetch it with: "
                f"{fetch_command(self.repo, manifest_path.name, self.cache_dir)}"
            )
        self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._codebook = Codebook.from_json(codebook or self.cache_dir / DEFAULT_CODEBOOK)
        self._field_of = {str(column["id"]): index for index, column in enumerate(self._codebook.columns)}
        self._vocabulary_sizes = np.asarray([len(column["values"]) for column in self._codebook.columns], dtype=np.int16)
        declared = [str(column["path"]) for column in self._manifest["files"]]
        wanted = list(shards) if shards is not None else declared
        unknown = sorted(set(wanted) - set(declared))
        if unknown:
            raise MissingShard(
                f"the release's manifest names no such shards: {unknown}; fetch them with: "
                + " && ".join(fetch_command(self.repo, name, self.cache_dir) for name in unknown)
            )
        self._entries = {str(entry["path"]): entry for entry in self._manifest["files"] if str(entry["path"]) in set(wanted)}
        self._cache: dict[str, _ShardArrays] = {}

    @property
    def codebook(self) -> Codebook:
        return self._codebook

    def sources(self) -> tuple[PersonaSource, ...]:
        present = set()
        for shard in self._loaded():
            for source in shard.sources:
                if self.admissible is None or source in self.admissible:
                    present.add(str(source))
        return tuple(sorted(present))

    def attributes(self) -> tuple[AttributeId, ...]:
        return self._codebook.attributes

    def values(self, attribute: AttributeId) -> tuple[AttributeValue, ...]:
        vocabulary = self._codebook.vocabulary(attribute)
        if vocabulary is None:
            raise KeyError(f"the codebook does not know attribute {attribute!r}")
        return vocabulary

    def matching(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        sources: Iterable[PersonaSource] | None = None,
    ) -> tuple[str, ...]:
        self._require_known([*predicates, *present])
        selected: list[str] = []
        for shard, mask in self._masks(predicates, present, sources):
            selected.extend(shard.row_ids[index] for index in np.nonzero(mask)[0])
        return tuple(selected)

    def _require_known(self, attributes: Iterable[AttributeId]) -> None:
        """Refuse a study naming attributes this corpus does not carry, before a shard is read.

        A study states the attributes it conditions and filters on, and nothing compared them with
        the codebook: a name the release spells differently surfaced as a `KeyError` from inside a
        numpy mask, after four shards had been read. A doomed study should cost nothing, so the
        refusal names what is missing and what the codebook does have that looks like it."""
        from simcore.schemas import GateFailure

        missing = sorted({str(attribute) for attribute in attributes} - set(self._field_of))
        if not missing:
            return
        known = sorted(self._field_of)
        suggestions = {}
        for name in missing:
            stem = str(name).lower()
            near = [candidate for candidate in known if stem in candidate.lower() or candidate.lower() in stem]
            if near:
                suggestions[name] = near[:4]
        detail = "; ".join(f"{name} (the codebook has {', '.join(near)})" for name, near in suggestions.items())
        raise GateFailure(
            f"the corpus carries no attribute named {', '.join(missing)}"
            + (f": {detail}" if detail else f"; it carries {len(known)} attributes, none of them these")
        )

    def _masks(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        sources: Iterable[PersonaSource] | None = None,
    ) -> Iterator[tuple[_ShardArrays, np.ndarray]]:
        """Each loaded shard with the boolean mask of its rows that are eligible — the one computation
        `matching` and `count` share, so counting never has to revisit a matched row."""
        present = tuple(present)
        requested = None if sources is None else tuple(sources)
        for shard in self._loaded():
            mask = np.ones(len(shard.row_ids), dtype=bool)
            for attribute in present:
                mask &= self._populated(shard, attribute)
            for attribute, predicate in predicates.items():
                mask &= self._predicate(shard, attribute, predicate)
            if self.admissible is not None:
                mask &= np.isin(shard.sources, np.asarray(self.admissible, dtype=object))
            if requested is not None:
                mask &= np.isin(shard.sources, np.asarray(requested, dtype=object))
            yield shard, mask

    def reference_values(self, ids: Sequence[str], attributes: Sequence[AttributeId]) -> list | None:
        """The values of `attributes` for rows `ids`, read from the persona value matrix — the same decoding
        as `rows`, looked up instead of decoded one row at a time — or nothing when the matrix is not built
        or does not hold one of the rows. A gate's reference distribution needs only these values."""
        from types import SimpleNamespace

        from .matrix import MISSING, load_matrix

        paths = tuple(str(entry["path"]) for entry in self._manifest["files"])
        try:
            whole = self if len(self._entries) == len(paths) else HfCoresetSource(cache_dir=self.cache_dir)
            matrix = load_matrix(whole)
            where = _matrix_positions(str(self.cache_dir), paths) if matrix is not None else None
        except (OSError, ValueError, MissingShard):
            return None
        if matrix is None or where is None:
            return None
        columns = []
        for row_id in ids:
            shard, _, index = row_id.partition(":")
            if shard not in where or not index.isdigit():
                return None
            offset, kept = where[shard]
            at = int(np.searchsorted(kept, int(index)))
            if at >= len(kept) or int(kept[at]) != int(index):
                return None  # a synthetic row, which the matrix leaves out
            columns.append(offset + at)
        picked = np.asarray(columns, dtype=np.int64)
        position = {attribute: row for row, attribute in enumerate(matrix.attributes)}
        values: list[dict] = [{} for _ in columns]
        for attribute in attributes:
            if attribute not in position:
                continue
            vocabulary = matrix.vocabulary[attribute]
            for k, code in enumerate(matrix.codes[position[attribute]][picked].tolist()):
                if code != MISSING:
                    values[k][attribute] = vocabulary[code]
        return [SimpleNamespace(values=held) for held in values]

    def rows(self, ids: Iterable[str]) -> Iterator[DecodedRow]:
        by_shard: dict[str, list[int]] = {}
        for row_id in ids:
            shard, _, index = row_id.partition(":")
            by_shard.setdefault(shard, []).append(int(index))
        for shard, indices in by_shard.items():
            arrays = self._arrays(shard)
            for index in indices:
                yield self._decode(arrays, index)

    def count(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        by_source: bool = True,
    ) -> Mapping[PersonaSource, int] | int:
        # Answered from the packed arrays as vectors: a scan of the loaded shards, never a row decode and
        # never a pass over the matched rows one at a time.
        counts: dict[PersonaSource, int] = {}
        for shard, mask in self._masks(predicates, present):
            for source, count in zip(*np.unique(shard.sources[mask].astype(str), return_counts=True)):
                counts[str(source)] = counts.get(str(source), 0) + int(count)
        return counts if by_source else sum(counts.values())

    # --- reading machinery ---------------------------------------------------------------------

    def _loaded(self) -> list[_ShardArrays]:
        return [self._arrays(Path(str(entry["path"])).stem) for entry in self._entries.values()]

    def _arrays(self, shard: str) -> _ShardArrays:
        cached = self._cache.get(shard)
        if cached is not None:
            return cached
        entry = self._find_entry(shard)
        self._verify(shard, str(entry.get("sha256", "")))
        arrays = self._load(shard)
        self._cache[shard] = arrays
        return arrays

    def _find_entry(self, shard: str) -> Mapping[str, object]:
        for path, entry in self._entries.items():
            if Path(path).stem == shard:
                return entry
        raise KeyError(f"no shard {shard!r} is loaded in this source")

    def _verify(self, shard: str, digest: str) -> None:
        path = self._find_entry(shard)
        file_path = self.cache_dir / str(path["path"])
        if not file_path.is_file():
            raise MissingShard(
                f"the shard {str(file_path)!r} is needed but not cached; fetch it with: "
                f"{fetch_command(self.repo, str(path['path']), self.cache_dir)}"
            )
        if digest:
            hasher = hashlib.sha256()
            for block in _stream(file_path):
                hasher.update(block)
            if hasher.hexdigest() != digest:
                raise ShardMismatch(f"{str(file_path)} digest {hasher.hexdigest()} does not match the manifest's {digest}")

    def _load(self, shard: str) -> _ShardArrays:
        import pyarrow.parquet as pq

        entry = self._find_entry(shard)
        path = self.cache_dir / str(entry["path"])
        # `grounding` carries an `evidence` text the adapter never reads — 3.08 GB uncompressed on the
        # release's largest shard, against 0.08 GB for the two leaves that decide a field's tier. The
        # dataset reader takes whole columns only; the file reader takes leaf paths, so only the leaves
        # are read. (`descriptions`, larger still at 4.48 GB, is not asked for at all.)
        columns = [
            "source",
            "attributes",
            "null_bitmap",
            "attribute_overrides",
            "populated_attribute_count",
        ]
        reader = pq.ParquetFile(path)
        full = reader.read(columns=columns)
        rows = full.num_rows
        attributes = np.frombuffer(b"".join(full["attributes"].to_numpy(zero_copy_only=False)), dtype=np.uint8).reshape(rows, -1)
        bitmaps = full["null_bitmap"].to_numpy(zero_copy_only=False)
        bitmap = (
            None
            if all(item is None for item in bitmaps)
            else np.frombuffer(
                b"".join(item if item is not None else b"\x00" * _bitmap_bytes(attributes.shape[1]) for item in bitmaps),
                dtype=np.uint8,
            ).reshape(rows, -1)
        )
        sources = np.asarray(full["source"].to_pylist(), dtype=object)
        row_ids = tuple(f"{shard}:{index}" for index in range(rows))
        overrides: dict[int, dict[int, str]] = {}
        for index, entry_overrides in enumerate(full["attribute_overrides"].to_pylist()):
            for item in entry_overrides or ():
                overrides.setdefault(int(item["field_index"]), {})[index] = str(item["value"])
        inferred = _stream_inferred(reader)
        counts = np.asarray(full["populated_attribute_count"].to_numpy(zero_copy_only=False), dtype=np.int32)
        # Everything the shard is read for is now packed, so the table goes. Held, it kept the whole
        # `grounding` column alive for the sake of slicing single rows out of it later — gigabytes per
        # shard, times every shard a draw matches against.
        del full
        return _ShardArrays(
            row_ids=row_ids,
            attributes=attributes,
            bitmap=bitmap,
            vocabulary_sizes=self._vocabulary_sizes,
            sources=sources,
            counts=counts,
            overrides=overrides,
            inferred=inferred,
        )

    def tiers(self, arrays: _ShardArrays, attribute: AttributeId) -> np.ndarray:
        """The tier of one attribute for every row in a shard, as ``tier_for`` grades a decoded row —
        computed as vectors, so an index can grade millions of fields without building a persona."""
        index = self._field_of[attribute]
        tiers = np.empty(len(arrays.row_ids), dtype=object)
        tiers[:] = FieldOrigin.EXTRACTED
        tiers[np.isin(arrays.sources, np.asarray(tuple(_SURVEY_SOURCES), dtype=object))] = FieldOrigin.MEASURED
        tiers[arrays.sources == "synthetic"] = FieldOrigin.SYNTHESIZED
        rows = arrays.inferred.get(index)
        if rows is not None and len(rows):
            downgraded = rows[tiers[rows] == FieldOrigin.MEASURED]
            tiers[downgraded] = FieldOrigin.EXTRACTED
        return tiers

    def labels(self, arrays: _ShardArrays, attribute: AttributeId) -> np.ndarray:
        """The decoded label of one attribute for every row in a shard, `None` where the field is absent —
        the same value ``decode_row`` would produce, including its overrides, computed as vectors."""
        cached = arrays.labels.get(attribute)
        if cached is not None:
            return cached
        index = self._field_of[attribute]
        values = [str(value) for value in self._codebook.columns[index]["values"]]
        codes = _field_codes(arrays.attributes, index)
        labels = np.empty(len(arrays.row_ids), dtype=object)
        labels[:] = None
        for code, label in enumerate(values):
            labels[codes == code] = label
        if arrays.bitmap is not None:
            labels[~_field_present(arrays.bitmap, index)] = None
        unexpressible = np.zeros(len(arrays.row_ids), dtype=bool)
        for row, raw in arrays.overrides.get(index, {}).items():
            labels[row] = _resolve_override(raw, values)
            unexpressible[row] = is_unexpressible(raw, values)
        arrays.labels[attribute] = labels
        arrays.unexpressible[attribute] = unexpressible
        return labels

    def unexpressible(self, arrays: _ShardArrays, attribute: AttributeId) -> np.ndarray:
        """Rows that recorded a value for `attribute` the vocabulary cannot express, and so decode it as
        absent; see ``is_unexpressible``."""
        self.labels(arrays, attribute)
        return arrays.unexpressible[attribute]

    def _populated(self, arrays: _ShardArrays, attribute: AttributeId) -> np.ndarray:
        return self.labels(arrays, attribute) != None  # noqa: E711 - numpy object-array presence test

    def _predicate(self, arrays: _ShardArrays, attribute: AttributeId, predicate: AttributeFilter) -> np.ndarray:
        index = self._field_of.get(attribute)
        if index is None:
            return np.zeros(len(arrays.row_ids), dtype=bool)
        labels = self.labels(arrays, attribute)
        allowed = _allowed_labels(predicate, [str(value) for value in self._codebook.columns[index]["values"]])
        return np.isin(labels, np.asarray(allowed, dtype=object)) if allowed else np.zeros(len(arrays.row_ids), dtype=bool)

    def _decode(self, arrays: _ShardArrays, index: int) -> DecodedRow:
        """One row, from the packed arrays alone — the shard's table is not kept to be sliced."""
        row_id = arrays.row_ids[index]
        source = str(arrays.sources[index])
        overrides = sorted(
            (field_index, values[index]) for field_index, values in arrays.overrides.items() if index in values
        )
        values = decode_row(
            self._codebook,
            arrays.attributes[index].tobytes(),
            arrays.bitmap[index].tobytes() if arrays.bitmap is not None else None,
            overrides,
            int(arrays.counts[index]),
            row_id=row_id,
        )
        # A recorded assignment and an absent one grade alike, and `inferred` holds exactly the rows
        # whose assignment was neither — the same distinction `tier_for` draws, from what is kept.
        tiers = {
            attribute: tier_for(source, "inferred" if arrays.inferred_at(self._field_of[attribute], index) else None)
            for attribute in values
        }
        return DecodedRow(row_id=row_id, source=source, values=FrozenDict(values), tiers=FrozenDict(tiers))


# Rows per batch when the grounding leaves are streamed. One shard of the release carries fifty
# million grounding entries, and taking their parent indices in one go is a 390 MB array before
# anything is filtered; batching bounds that whatever the shard's size.
_GROUNDING_BATCH_ROWS = 20_000


def _stream_inferred(reader) -> dict[int, np.ndarray]:
    """`_inferred_rows` over one shard, read a batch at a time.

    Only the two leaves a tier depends on are read: `grounding` also carries an `evidence` text
    three gigabytes wide on the release's largest shard, and the adapter never looks at it. Each
    batch numbers its rows from zero, so its rows are shifted by the rows before it.
    """
    parts: dict[int, list[np.ndarray]] = {}
    rows_before = 0
    for batch in reader.iter_batches(
        batch_size=_GROUNDING_BATCH_ROWS,
        columns=["grounding.list.element.field_index", "grounding.list.element.assignment_type"],
    ):
        for field_index, rows in _inferred_rows(batch.column("grounding")).items():
            parts.setdefault(field_index, []).append(rows + rows_before)
        rows_before += batch.num_rows
    merged = {}
    for field_index, chunks in parts.items():
        rows = np.concatenate(chunks)
        rows.sort()  # ascending, in place, so membership can be searched rather than indexed
        merged[field_index] = rows
    return merged


def _inferred_rows(grounding) -> dict[int, np.ndarray]:
    """For each field, the rows whose grounding entry names an assignment other than a recorded one.

    Read with vector compute: a wiki shard carries tens of millions of grounding entries, far too many to
    walk as Python objects. A null assignment type is not an inference, so nullness is tested explicitly —
    `is_in` reports a null as a non-member rather than as null.

    Read chunk by chunk, never combined: the release's largest shard holds more than two gigabytes of
    grounding child data, and concatenating its chunks into one array overflows Arrow's 32-bit offsets.
    Each chunk numbers its rows from zero, so the rows it reports are shifted by the rows before it."""
    import pyarrow as pa
    import pyarrow.compute as pc

    chunks = list(grounding.chunks) if hasattr(grounding, "chunks") else [grounding]
    value_set = pa.array(sorted(_RECORDED_ASSIGNMENTS))
    field_parts: list[np.ndarray] = []
    parent_parts: list[np.ndarray] = []
    rows_before = 0
    for chunk in chunks:
        entries = chunk.flatten()
        if len(entries):
            chunk_parents = pc.list_parent_indices(chunk).to_numpy() + rows_before
            chunk_fields = entries.field("field_index").to_numpy(zero_copy_only=False)
            types = entries.field("assignment_type")
            recorded = pc.or_(pc.is_in(types, value_set=value_set), pc.is_null(types))
            inferred = ~recorded.to_numpy(zero_copy_only=False)
            field_parts.append(chunk_fields[inferred])
            parent_parts.append(chunk_parents[inferred])
        rows_before += len(chunk)
    if not field_parts:
        return {}
    fields = np.concatenate(field_parts)
    parents = np.concatenate(parent_parts)
    if len(fields) == 0:
        return {}
    order = np.argsort(fields, kind="stable")
    fields, parents = fields[order], parents[order]
    boundaries = np.flatnonzero(np.diff(fields)) + 1
    return {int(group[0]): rows for group, rows in zip(np.split(fields, boundaries), np.split(parents, boundaries)) if len(group)}


def _field_codes(attributes: np.ndarray, index: int) -> np.ndarray:
    byte = attributes[:, index // 2]
    return (byte & 0x0F) if index % 2 == 0 else ((byte >> 4) & 0x0F)


def _field_present(bitmap: np.ndarray, index: int) -> np.ndarray:
    byte = bitmap[:, index // 8]
    return ((byte >> (index % 8)) & 1) == 0


def _bitmap_bytes(row_bytes: int) -> int:
    fields = row_bytes * 2
    return (fields + 7) // 8


def _allowed_labels(predicate: AttributeFilter, values: list) -> list:
    if isinstance(predicate, Exactly):
        return [predicate.value] if predicate.value in values else []
    if isinstance(predicate, OneOf):
        return [value for value in predicate.values if value in values]
    if isinstance(predicate, BandRange):
        if predicate.first not in values or predicate.last not in values:
            return []
        low, high = sorted((values.index(predicate.first), values.index(predicate.last)))
        return values[low : high + 1]
    return []


def _stream(path: Path, chunk: int = 1 << 20) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            yield block


@lru_cache(maxsize=4)
def _matrix_positions(cache_dir: str, paths: tuple[str, ...]) -> dict[str, tuple[int, np.ndarray]]:
    """Where each shard's rows sit in the persona matrix: its offset, and the positions of its
    non-synthetic rows, in the order the matrix was built — the manifest's."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from .coverage import SYNTHETIC

    where: dict[str, tuple[int, np.ndarray]] = {}
    offset = 0
    for path in paths:
        # Compared in Arrow and read back as booleans: a Python string per row is memory a large draw lacks.
        column = pq.ParquetFile(Path(cache_dir, path)).read(columns=["source"])["source"]
        kept = np.flatnonzero(~pc.equal(column, SYNTHETIC).to_numpy(zero_copy_only=False))
        where[Path(path).stem] = (offset, kept)
        offset += len(kept)
    return where


def shard_sources(path: str | Path) -> dict[str, int]:
    """How many rows of each source one shard holds, largest first: a shard is a slice of rows, not of sources."""
    shard = Path(path)
    return dict(_source_counts(str(shard), shard.stat().st_mtime_ns))


@lru_cache(maxsize=64)
def _source_counts(path: str, _mtime_ns: int) -> tuple[tuple[str, int], ...]:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    counts = pc.value_counts(pq.ParquetFile(path).read(columns=["source"])["source"]).to_pylist()
    return tuple(sorted(((str(item["values"]), int(item["counts"])) for item in counts), key=lambda pair: -pair[1]))


def fetch_command(repo: str, relative: str | Path, cache_dir: Path) -> str:
    """The command that fetches one cached file. It is shown, never run: a study downloads nothing on
    its user's behalf."""
    return f'hf download {repo} "{str(relative)}" --repo-type dataset --local-dir "{str(cache_dir)}"'
