"""Attribute embeddings: one per attribute, for search by meaning.

Each attribute becomes one short document — its label, its category and its
value list — embedded with the pinned embedding model through the one
OpenAI-compatible endpoint. Cached by codebook digest and model beside the
coverage cache, built in the background; a different model builds a new cache
rather than mixing vectors. Without them, or without an endpoint, search is
by words and drafting is unavailable, and the interface says so.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
import time
import urllib.request
from pathlib import Path

import numpy as np

EMBEDDINGS_DIRECTORY = "consumersim-index"
EMBEDDINGS_FORMAT = "attribute-embeddings/1"

# The run's pinned embedding model: the identifier sent to the endpoint.
DEFAULT_EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def embed_model() -> str:
    """The pinned embedding model — configuration, never a study input."""
    return os.environ.get("SIMCORE_EMBED_MODEL") or DEFAULT_EMBED_MODEL


def endpoint_base() -> str | None:
    """The one OpenAI-compatible endpoint (ADR 0021), or nothing when the server's environment names none."""
    base = os.environ.get("SIMCORE_INFERENCE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    return base.rstrip("/") if base else None


def post_json(path: str, body: dict, timeout: float = 120) -> dict:
    """POST to the configured endpoint, with its key when it has one."""
    base = endpoint_base()
    if base is None:
        raise RuntimeError("no inference endpoint is configured in the server's environment")
    headers = {"content-type": "application/json"}
    key = os.environ.get("SIMCORE_INFERENCE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def document(column: dict) -> str:
    """One attribute as one short document: label, category, values."""
    return f"{column.get('label') or column['id']}. {column.get('category', '')}. Values: {', '.join(map(str, column['values']))}."


def codebook_digest(cache_dir: Path) -> str:
    """What the embeddings are cached under, with the model: the codebook file itself."""
    return hashlib.sha256(Path(cache_dir, "persona_codes.schema.json").read_bytes()).hexdigest()


def _slug(model: str) -> str:
    return hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]


def cache_path(cache_dir: Path, digest: str, model: str) -> Path:
    return Path(cache_dir) / EMBEDDINGS_DIRECTORY / f"embeddings-{digest[:8]}-{_slug(model)}"


def load_embeddings(cache_dir: Path, digest: str, model: str):
    """The saved vectors for this codebook and model, normalised — or nothing. Read once per file."""
    base = cache_path(cache_dir, digest, model)
    archive = base.with_suffix(".npz")
    if not (base.with_suffix(".json").is_file() and archive.is_file()):
        return None
    return _read(str(base), archive.stat().st_mtime_ns, digest, model)


@lru_cache(maxsize=2)
def _read(base_name: str, _mtime: int, digest: str, model: str):
    base = Path(base_name)
    sidecar_path = base.with_suffix(".json")
    archive = base.with_suffix(".npz")
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if sidecar.get("format") != EMBEDDINGS_FORMAT or sidecar.get("digest") != digest or sidecar.get("model") != model:
        return None
    with np.load(archive) as stored:
        vectors = np.array(stored["vectors"], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)
    return {"ids": list(sidecar["ids"]), "vectors": vectors}


def _embed(texts: list[str], model: str, base: str | None = None) -> list[list[float]]:
    return [row["embedding"] for row in post_json("/embeddings", {"model": model, "input": texts})["data"]]


def build_embeddings(cache_dir: Path, digest: str, model: str, progress=None) -> dict:
    """Embed every codebook attribute once, resumably, and save the cache."""
    cache_dir = Path(cache_dir)
    columns = json.loads(Path(cache_dir, "persona_codes.schema.json").read_text())["columns"]
    base = cache_path(cache_dir, digest, model)
    done: dict[str, list[float]] = {}
    partial = base.with_suffix(".partial.jsonl")
    if partial.is_file():
        for line in partial.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["id"]] = row["embedding"]
    todo = [column for column in columns if column["id"] not in done]
    if endpoint_base() is None:
        raise RuntimeError("no inference endpoint is configured in the server's environment")
    with partial.open("a", encoding="utf-8") as sink:
        for position, column in enumerate(todo):
            vector = _embed([document(column)], model)[0]
            done[column["id"]] = vector
            sink.write(json.dumps({"id": column["id"], "embedding": vector}) + "\n")
            sink.flush()
            if progress is not None:
                progress(column["id"], len(done), len(columns))
            time.sleep(1.0)  # Titan v2's default quota is 60 requests a minute
    ids = [column["id"] for column in columns]
    vectors = np.asarray([done[column["id"]] for column in columns], dtype=np.float32)
    base.parent.mkdir(parents=True, exist_ok=True)
    archive = base.with_suffix(".npz")
    archive_partial = base.with_suffix(".partial.npz")
    np.savez_compressed(archive_partial, vectors=vectors)
    archive_partial.replace(archive)
    sidecar_path = base.with_suffix(".json")
    sidecar_partial = base.with_suffix(".partial.json")
    sidecar_partial.write_text(
        json.dumps({"format": EMBEDDINGS_FORMAT, "digest": digest, "model": model, "ids": ids}, sort_keys=True),
        encoding="utf-8",
    )
    sidecar_partial.replace(sidecar_path)
    partial.unlink(missing_ok=True)
    loaded = load_embeddings(cache_dir, digest, model)
    assert loaded is not None
    return loaded


def rank_meaning(query_vector, embeddings: dict, shares) -> tuple[np.ndarray, np.ndarray]:
    """Relevance minus what almost nobody answered: below 10% coverage sinks
    0.04, below 1% sinks 0.08, and nobody-carries-it ranks last."""
    relevance = embeddings["vectors"] @ np.asarray(query_vector, dtype=np.float32)
    shares = np.asarray(shares, dtype=np.float64)
    score = relevance - 0.04 * (shares < 0.10) - 0.08 * (shares < 0.01)
    score = np.where(shares == 0, -10.0, score)
    return relevance, score
