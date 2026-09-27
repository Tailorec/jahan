"""The persona value matrix: every persona's value for every attribute, decoded once.

Every count the "Who you study" step shows — candidate pool, requirement and
filter costs, value counts, audience head counts — is vector work over this
matrix, in milliseconds. It is decoded through the adapter (`labels`), so
presence, overrides and missingness follow the draw's rules; synthetic rows
are left out, as a study leaves them out. Built once per machine beside the
coverage cache, keyed by shard digests, and memory-mapped rather than held by
the API process.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

import numpy as np

MATRIX_DIRECTORY = "consumersim-index"
MATRIX_FORMAT = "matrix/2"

# No value: the field is absent (or the row is synthetic and was left out).
MISSING = -1


@dataclass(frozen=True)
class PersonaMatrix:
    """The decoded matrix: `codes[attribute, row]` is the value's index into
    the attribute's vocabulary, or -1 where the field is absent."""

    attributes: tuple[str, ...]
    vocabulary: dict[str, tuple[str, ...]]
    sources: tuple[str, ...]
    totals: dict[str, int]
    codes: np.ndarray  # (attributes, personas) int8, possibly memory-mapped
    row_source: np.ndarray  # (personas,) index into `sources`

    def pool_mask(self, sources: tuple[str, ...], required: tuple[str, ...]) -> np.ndarray:
        """Rows in `sources` carrying every required attribute."""
        index_of = {name: position for position, name in enumerate(self.sources)}
        chosen = np.zeros(len(self.row_source), dtype=bool)
        for name in sources:
            position = index_of.get(name)
            if position is not None:
                chosen |= self.row_source == position
        mask = chosen
        positions = {attribute: position for position, attribute in enumerate(self.attributes)}
        for attribute in required:
            mask = mask & (self.codes[positions[attribute]] != MISSING)
        return mask

    @cached_property
    def answered_by_source(self) -> dict[str, int]:
        """How many attributes each source's people answered at all — one pass, once per opened matrix."""
        answered = np.zeros(len(self.sources), dtype=np.int64)
        for column in self.codes:
            answered += np.bincount(self.row_source[column != MISSING], minlength=len(self.sources)) > 0
        return {name: int(count) for name, count in zip(self.sources, answered)}

    def by_source(self, mask: np.ndarray) -> dict[str, int]:
        counts = np.bincount(self.row_source[mask], minlength=len(self.sources))
        return {name: int(count) for name, count in zip(self.sources, counts) if int(count)}


def _fingerprint(hf_source) -> dict[str, str]:
    return {str(path): str(entry.get("sha256", "")) for path, entry in sorted(hf_source._entries.items())}


def _path(cache_dir: Path, fingerprint: dict[str, str]) -> Path:
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / MATRIX_DIRECTORY / f"matrix-{key}"


def load_matrix(hf_source) -> PersonaMatrix | None:
    """The saved matrix for exactly these shards, memory-mapped — or nothing.

    Opened once per process and shared: the codes stay on disk and in the page
    cache, so a request costs no copy of the 774 MB matrix."""
    base = _path(hf_source.cache_dir, _fingerprint(hf_source))
    sidecar_path = base.with_suffix(".json")
    if not sidecar_path.is_file():
        return None
    return _open(str(base), sidecar_path.stat().st_mtime_ns, json.dumps(_fingerprint(hf_source), sort_keys=True))


@lru_cache(maxsize=2)
def _open(base_name: str, _mtime: int, fingerprint: str) -> PersonaMatrix | None:
    base = Path(base_name)
    try:
        sidecar = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        if sidecar.get("format") != MATRIX_FORMAT or sidecar.get("shards") != json.loads(fingerprint):
            return None
        codes = np.load(f"{base}.codes.npy", mmap_mode="r")
        row_source = np.load(f"{base}.rows.npy", mmap_mode="r")
    except (OSError, ValueError):
        return None
    return PersonaMatrix(
        attributes=tuple(sidecar["attributes"]),
        vocabulary={attribute: tuple(values) for attribute, values in sidecar["vocabulary"].items()},
        sources=tuple(sidecar["sources"]),
        totals=dict(sidecar["totals"]),
        codes=codes,
        row_source=row_source,
    )


def build_matrix(hf_source) -> PersonaMatrix:
    """Decode every non-synthetic row through the adapter and save the matrix."""
    attributes = tuple(hf_source.attributes())
    vocabularies = {attribute: tuple(hf_source.values(attribute)) for attribute in attributes}
    order = {attribute: position for position, attribute in enumerate(attributes)}

    from simcore.ports.coverage import SYNTHETIC

    codes_parts: list[np.ndarray] = []
    source_parts: list[np.ndarray] = []
    names: list[str] = []
    for entry in hf_source._entries.values():
        arrays = hf_source._arrays(Path(str(entry["path"])).stem)
        shard_sources = np.asarray(arrays.sources, dtype=object)
        keep = shard_sources != SYNTHETIC
        kept_sources = [str(name) for name in shard_sources[keep]]
        for name in kept_sources:
            if name not in names:
                names.append(name)
        table = np.full((len(attributes), int(keep.sum())), MISSING, dtype=np.int8)
        for attribute in attributes:
            labels = hf_source.labels(arrays, attribute)[keep]
            index_of = {value: code for code, value in enumerate(vocabularies[attribute])}
            column = np.full(len(labels), MISSING, dtype=np.int8)
            for value, code in index_of.items():
                column[labels == value] = code
            table[order[attribute]] = column
            arrays.labels.pop(attribute, None)  # a shard's labels for every attribute would hold ~1 GB
            arrays.unexpressible.pop(attribute, None)
        codes_parts.append(table)
        source_parts.append(np.asarray([names.index(name) for name in kept_sources], dtype=np.int64))
        hf_source._cache.pop(Path(str(entry["path"])).stem, None)

    codes = np.concatenate(codes_parts, axis=1) if codes_parts else np.zeros((len(attributes), 0), dtype=np.int8)
    row_source = np.concatenate(source_parts) if source_parts else np.zeros(0, dtype=np.int64)
    totals = {name: int((row_source == position).sum()) for position, name in enumerate(names)}
    matrix = PersonaMatrix(
        attributes=attributes,
        vocabulary=vocabularies,
        sources=tuple(names),
        totals=totals,
        codes=codes,
        row_source=row_source,
    )
    _save(hf_source.cache_dir, _fingerprint(hf_source), matrix)
    return matrix


def _save(cache_dir: Path, fingerprint: dict[str, str], matrix: PersonaMatrix) -> None:
    """Uncompressed, so it can be memory-mapped; the sidecar goes last, so a half-written matrix is never read."""
    base = _path(cache_dir, fingerprint)
    base.parent.mkdir(parents=True, exist_ok=True)
    for suffix, array, dtype in (("codes", matrix.codes, np.int8), ("rows", matrix.row_source, np.int64)):
        partial = Path(f"{base}.{suffix}.partial.npy")
        np.save(partial, np.asarray(array, dtype=dtype))
        partial.replace(f"{base}.{suffix}.npy")
    sidecar = {
        "format": MATRIX_FORMAT,
        "shards": fingerprint,
        "attributes": list(matrix.attributes),
        "vocabulary": {attribute: list(values) for attribute, values in matrix.vocabulary.items()},
        "sources": list(matrix.sources),
        "totals": dict(matrix.totals),
    }
    sidecar_partial = base.with_suffix(".partial.json")
    sidecar_partial.write_text(json.dumps(sidecar, sort_keys=True), encoding="utf-8")
    sidecar_partial.replace(base.with_suffix(".json"))
