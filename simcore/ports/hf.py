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
from .decoder import Codebook, decode_row

REPO = "MatrAIx2026/MatrAIx_Persona_1M_Public_Release"
DEFAULT_CODEBOOK = "persona_codes.schema.json"
DEFAULT_MANIFEST = "manifest.json"


def default_cache_dir(repo: str = REPO) -> Path:
    """Where a fetched release lives: a user cache directory, never the repository."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "consumersim" / "coreset" / repo.replace("/", "__")

# The tier cannot be read from the source alone (`gss` and `amazon` both report `direct`) or from the
# assignment type alone (`wiki` varies within a source). It is read from the pair: what kind of
# instrument or reader produced the value, together with how that reading was assigned (ADR 0017).
_INSTRUMENT_SOURCES = frozenset({"gss", "stackoverflow", "real_human_survey"})
_TEXT_SOURCES = frozenset({"wiki", "amazon", "prism"})
_MEASURED_ASSIGNMENTS = frozenset({"direct", "structured_claim"})


def tier_for(source: PersonaSource, assignment_type: str | None) -> FieldOrigin:
    """Grade one field's value from the source it came from and the way it was assigned.

    A survey answer grades as measured even when its evidence is empty; a model's reading of text
    grades as extracted, whether it was direct, summarised, or unsupported; a synthetic row's
    skeleton grades as synthesized."""
    if source == "synthetic":
        return FieldOrigin.SYNTHESIZED
    if source in _INSTRUMENT_SOURCES:
        return FieldOrigin.MEASURED
    if source in _TEXT_SOURCES:
        return FieldOrigin.EXTRACTED
    if assignment_type in _MEASURED_ASSIGNMENTS:
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
    full: object  # the pyarrow table, kept for the lazy per-row decode
    overrides: Mapping[int, Mapping[int, str]]  # field_index -> row -> raw override value
    labels: dict = field(default_factory=dict)  # attribute -> decoded-label array, cached


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
        present = tuple(present)
        requested = None if sources is None else tuple(sources)
        selected: list[str] = []
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
            selected.extend(shard.row_ids[index] for index in np.nonzero(mask)[0])
        return tuple(selected)

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
        # Answered from the packed arrays, so it costs a scan of the loaded shards, not a row decode.
        selected = self.matching(predicates, present)
        if not by_source:
            return len(selected)
        counts: dict[PersonaSource, int] = {}
        for row_id in selected:
            shard, _, index = row_id.partition(":")
            source = str(self._arrays(shard).sources[int(index)])
            counts[source] = counts.get(source, 0) + 1
        return counts

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
        columns = [
            "source",
            "attributes",
            "null_bitmap",
            "attribute_overrides",
            "grounding",
            "populated_attribute_count",
        ]
        full = pq.read_table(path, columns=columns)
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
        return _ShardArrays(
            row_ids=row_ids,
            attributes=attributes,
            bitmap=bitmap,
            vocabulary_sizes=self._vocabulary_sizes,
            sources=sources,
            full=full,
            overrides=overrides,
        )

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
        for row, raw in arrays.overrides.get(index, {}).items():
            labels[row] = _resolve_override_label(raw, values)
        arrays.labels[attribute] = labels
        return labels

    def _populated(self, arrays: _ShardArrays, attribute: AttributeId) -> np.ndarray:
        return self.labels(arrays, attribute) != None  # noqa: E711 - numpy object-array presence test

    def _predicate(self, arrays: _ShardArrays, attribute: AttributeId, predicate: AttributeFilter) -> np.ndarray:
        index = self._field_of.get(attribute)
        if index is None:
            return np.zeros(len(arrays.row_ids), dtype=bool)
        labels = self.labels(arrays, attribute)
        allowed = set(_allowed_labels(predicate, [str(value) for value in self._codebook.columns[index]["values"]]))
        mask = np.zeros(len(arrays.row_ids), dtype=bool)
        for position, label in enumerate(labels):
            if label is not None and label in allowed:
                mask[position] = True
        return mask

    def _decode(self, arrays: _ShardArrays, index: int) -> DecodedRow:
        record = arrays.full.slice(index, 1).to_pylist()[0]
        row_id = arrays.row_ids[index]
        source = str(arrays.sources[index])
        overrides = [(int(item["field_index"]), str(item["value"])) for item in (record.get("attribute_overrides") or ())]
        values = decode_row(
            self._codebook,
            record["attributes"],
            record.get("null_bitmap"),
            overrides,
            int(record["populated_attribute_count"]),
            row_id=row_id,
        )
        assignments = {int(item["field_index"]): item.get("assignment_type") for item in (record.get("grounding") or ())}
        tiers = {attribute: tier_for(source, assignments.get(self._field_of[attribute])) for attribute in values}
        return DecodedRow(row_id=row_id, source=source, values=FrozenDict(values), tiers=FrozenDict(tiers))


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


def _resolve_override_label(raw: str, values: list) -> str | None:
    from simcore.ports.decoder import _MISSINGNESS

    token = raw.strip()
    if token.lower() in _MISSINGNESS:
        return None
    if token in values:
        return token
    lowered = {value.lower(): value for value in values}
    return lowered.get(token.lower())


def _stream(path: Path, chunk: int = 1 << 20) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            yield block


def fetch_command(repo: str, relative: str | Path, cache_dir: Path) -> str:
    """The command that fetches one cached file. It is shown, never run: a study downloads nothing on
    its user's behalf."""
    return f'hf download {repo} "{str(relative)}" --repo-type dataset --local-dir "{str(cache_dir)}"'
