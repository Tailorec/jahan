"""How populated each attribute is, per source, across the shards a machine holds.

A study can pass every check and still be undrawable when its audience is defined by an attribute that almost
nobody has (`habit_budget_tracking` is populated for 0.04% of measured personas). Only 20 of the corpus's 1,290
attributes are populated for more than half of them, so which attribute to choose is the decision that matters
most and the one the codebook does not inform. This counts presence, per attribute and per source, from the
packed arrays — no persona is decoded — and keeps the result beside the release's own cache, keyed by the
digests of the shards it read, so a changed release recounts rather than answering from a stale count.

Unlike the value index in `index_catalog`, this holds one integer per attribute per source: it is small enough
to count over every attribute in the codebook, which is the point.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

COVERAGE_DIRECTORY = "consumersim-index"
COVERAGE_FORMAT = "coverage/1"

# Sources whose values were recorded rather than synthesized. A synthetic row carries every field by
# construction, so counting it would make every attribute look populated.
SYNTHETIC = "synthetic"


def _fingerprint(hf_source) -> dict[str, str]:
    return {str(path): str(entry.get("sha256", "")) for path, entry in sorted(hf_source._entries.items())}


def _path(cache_dir: Path, fingerprint: dict[str, str]) -> Path:
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / COVERAGE_DIRECTORY / f"coverage-{key}.json"


def load_coverage(hf_source) -> dict | None:
    """The saved count for exactly these shards, or nothing when none was made."""
    fingerprint = _fingerprint(hf_source)
    try:
        saved = json.loads(_path(hf_source.cache_dir, fingerprint).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if saved.get("format") != COVERAGE_FORMAT or saved.get("shards") != fingerprint:
        return None
    return saved


def count_coverage(hf_source, progress: Callable[[str, int, int], None] | None = None) -> dict:
    """Count, per source and per attribute, how many rows carry the attribute; save and return it.

    Shards are read one at a time and each attribute's decoded labels are dropped as soon as they are
    counted: keeping them, as a persona draw does, holds about a gigabyte per shard at this width.
    """
    import numpy as np

    attributes = tuple(hf_source.attributes())
    totals: dict[str, int] = {}
    present: dict[str, dict[str, int]] = {attribute: {} for attribute in attributes}
    entries = list(hf_source._entries.values())
    for position, entry in enumerate(entries):
        shard = Path(str(entry["path"])).stem
        arrays = hf_source._arrays(shard)
        sources = np.asarray(arrays.sources, dtype=object)
        names = sorted({str(name) for name in sources})
        masks = {name: sources == name for name in names}
        for name in names:
            totals[name] = totals.get(name, 0) + int(masks[name].sum())
        for done, attribute in enumerate(attributes):
            carried = hf_source.labels(arrays, attribute) != None  # noqa: E711 - numpy object-array presence test
            for name in names:
                count = int((carried & masks[name]).sum())
                if count:
                    present[attribute][name] = present[attribute].get(name, 0) + count
            arrays.labels.pop(attribute, None)
            arrays.unexpressible.pop(attribute, None)
            if progress is not None and done % 100 == 0:
                progress(shard, position * len(attributes) + done, len(entries) * len(attributes))
        del arrays
        hf_source._cache.pop(shard, None)
    fingerprint = _fingerprint(hf_source)
    result = {
        "format": COVERAGE_FORMAT,
        "shards": fingerprint,
        "totals": totals,
        "present": {attribute: counts for attribute, counts in present.items()},
    }
    target = _path(hf_source.cache_dir, fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    partial.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    partial.replace(target)
    return result


def coverage_table(saved: dict) -> dict[str, dict]:
    """Each attribute's coverage as the reader wants it: counted over the recorded sources together and
    source by source, with the share alongside so nothing downstream divides."""
    totals = {name: total for name, total in saved["totals"].items()}
    recorded = {name: total for name, total in totals.items() if name != SYNTHETIC}
    recorded_total = sum(recorded.values())
    table: dict[str, dict] = {}
    for attribute, counts in saved["present"].items():
        recorded_present = sum(count for name, count in counts.items() if name in recorded)
        table[attribute] = {
            "recorded": {
                "present": recorded_present,
                "total": recorded_total,
                "share": round(recorded_present / recorded_total, 6) if recorded_total else None,
            },
            "by_source": {
                name: {
                    "present": counts.get(name, 0),
                    "total": total,
                    "share": round(counts.get(name, 0) / total, 6) if total else None,
                }
                for name, total in sorted(recorded.items())
            },
        }
    return table
