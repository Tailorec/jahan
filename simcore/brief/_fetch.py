"""Fetching the evidence a brief cites, through the port, into the sidecar beside it.

This is the only part of intake that reaches the network or reads the clock; `load_brief` stays a
pure function of two files (ADR 0013). Hashing, timestamping and writing live here, so the port
is nothing but bytes for a URL."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from simcore.ports import EvidencePort
from simcore.schemas import GateFailure

from ._intake import _read_yaml, _sidecar_path, read_sidecar_entries


@dataclass(frozen=True)
class FetchFailure:
    url: str
    reason: str


@dataclass(frozen=True)
class FetchedEvidence:
    url: str
    content_hash: str


@dataclass(frozen=True)
class FetchReport:
    """What one fetch did: the URLs retrieved, the ones already recorded, and the ones that failed."""

    fetched: tuple[FetchedEvidence, ...]
    skipped: tuple[str, ...]
    failed: tuple[FetchFailure, ...]


def fetch_evidence(path: Path, port: EvidencePort, *, refetch: bool = False) -> FetchReport:
    """Retrieve every URL the brief at `path` cites through `port` and record what came back.

    A URL already recorded is skipped unless `refetch` is set; one that fails is reported and left
    for a re-run. The sidecar is written atomically, so an interrupted run keeps the sidecar it
    started with, and the response body is hashed as received and never stored."""
    payload = _read_yaml(path)
    sidecar_path = _sidecar_path(path)
    entries = _existing_entries(sidecar_path)
    fetched: list[FetchedEvidence] = []
    skipped: list[str] = []
    failed: list[FetchFailure] = []
    for url in _cited_urls(payload):
        if url in entries and not refetch:
            skipped.append(url)
            continue
        try:
            body = port.fetch(url)
        except Exception as error:
            failed.append(FetchFailure(url, str(error) or type(error).__name__))
            continue
        content_hash = hashlib.sha256(body).hexdigest()
        entries[url] = {"content_hash": content_hash, "fetched_at": _utc_now()}
        fetched.append(FetchedEvidence(url, content_hash))
    if fetched:
        _write_sidecar(sidecar_path, entries)
    return FetchReport(tuple(fetched), tuple(skipped), tuple(failed))


def _cited_urls(payload: dict) -> tuple[str, ...]:
    """The URLs the brief cites, in file order and once each."""
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return ()
    urls: list[str] = []
    for claim in claims:
        url = claim.get("evidence_url") if isinstance(claim, dict) else None
        if isinstance(url, str) and url and url not in urls:
            urls.append(url)
    return tuple(urls)


def _existing_entries(sidecar_path: Path) -> dict:
    if not sidecar_path.is_file():
        return {}
    return read_sidecar_entries(sidecar_path)


def _write_sidecar(sidecar_path: Path, entries: dict) -> None:
    """Write the sidecar through a temporary file and a rename, so a partial file is never seen."""
    payload = json.dumps(entries, indent=2, sort_keys=True) + "\n"
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=sidecar_path.parent, prefix=sidecar_path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, sidecar_path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    except OSError as error:
        raise GateFailure(f"{sidecar_path}: could not be written ({error.strerror or error})") from error


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
