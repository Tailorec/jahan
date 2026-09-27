"""Audience sets: what Who you study finishes with, saved as one unit.

The audiences with their filters and shares, the assumptions they carry, the
sources and study size they were counted at, and the one ontology version they
were drafted against. Everything is checked by the engine's own types before it
is written, and a saved set is never changed: editing one saves another, so a
study that started from a set can always find what it started from.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_SET_ID = re.compile(r"^\d{8}-\d{6}-[a-z0-9_]{1,48}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def save_audience_set(root, ontology_root, body: dict, now: datetime | None = None) -> dict:
    """Check an audience set against the ontology version it names, then write it once."""
    from simcore.schemas import Assumption, Audience, CategoryOntology

    category = str(body.get("category") or "")
    version = str(body.get("ontology_version") or "")
    if not _NAME.fullmatch(category):
        raise ValueError("an audience set names the category it was drafted in")
    ontology_file = Path(ontology_root, category, f"{version}.json") if ontology_root is not None else None
    if not _VERSION.fullmatch(version) or ontology_file is None or not ontology_file.is_file():
        raise ValueError(f"no saved ontology {category} {version}: save the ontology before the audiences drafted against it")
    ontology = CategoryOntology.model_validate_json(ontology_file.read_text(encoding="utf-8"))

    raw = body.get("audiences") or []
    if not isinstance(raw, list) or not raw:
        raise ValueError("an audience set holds at least one audience")
    audiences = [
        {"name": item.get("name"), "share": item.get("share"), "attribute_filters": item.get("attribute_filters") or {}}
        for item in raw if isinstance(item, dict)
    ]
    parsed = [Audience.model_validate(audience) for audience in audiences]
    shares = [audience.share for audience in parsed]
    if any(share is None for share in shares) or abs(sum(shares) - 1.0) > 0.001:
        raise ValueError("every audience in a set has a share, and the shares add to 100%")
    undeclared = sorted({key for audience in parsed for key in audience.attribute_filters} - set(ontology.attribute_domains))
    if undeclared:
        raise ValueError(f"audiences filter on attributes {category} {version} does not declare: {undeclared}")
    assumptions = [
        {"text": item.get("text"), "source": item.get("source") or "assumed"}
        for item in body.get("assumptions") or [] if isinstance(item, dict)
    ]
    for assumption in assumptions:
        Assumption.model_validate(assumption)
    sources = body.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(source, str) and source for source in sources):
        raise ValueError("sources names persona sources, like [\"gss\"]")
    study_size = body.get("study_size")
    if not isinstance(study_size, int) or isinstance(study_size, bool) or study_size < 1:
        raise ValueError("study_size counts personas, like 200")

    now = now or datetime.now(timezone.utc)
    name = " ".join(str(body.get("name") or " · ".join(audience.name for audience in parsed)).split())[:120]
    set_id = f"{now:%Y%m%d-%H%M%S}-{_slug(name)}"
    record = {
        "id": set_id,
        "name": name,
        "category": category,
        "ontology_version": version,
        "created_at": now.isoformat(timespec="seconds"),
        "description": str(body.get("description") or ""),
        "audiences": audiences,
        "assumptions": assumptions,
        "sources": sources,
        "study_size": study_size,
    }
    dest = Path(root, category, f"{set_id}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("x", encoding="utf-8") as handle:  # never overwrite a saved set
            handle.write(json.dumps(record, indent=2) + "\n")
    except FileExistsError:
        raise ValueError(f"an audience set {category}/{set_id} already exists: save again in a moment")
    return record


def list_audience_sets(root) -> list[dict]:
    """Every saved audience set, newest first."""
    found = []
    base = Path(root) if root is not None else None
    if base is not None and base.is_dir():
        for path in base.glob("*/*.json"):
            try:
                found.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return sorted(found, key=lambda record: str(record.get("created_at") or ""), reverse=True)


def load_audience_set(root, category: str, set_id: str) -> dict | None:
    """One saved audience set, or nothing when there is no such set."""
    if root is None or not _NAME.fullmatch(category) or not _SET_ID.fullmatch(set_id):
        return None
    path = Path(root, category, f"{set_id}.json")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "audiences"
