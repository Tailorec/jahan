"""Turning a finished world's live record into its lasting one.

The payload union fans out into typed Parquet columns — one struct column per payload kind,
so no JSON blob carries a whole event — and the derived shapes are written by the same code
that computes them live (`derive`). The contract version goes into the Parquet metadata and
the registry. Finalization is idempotent, and a finalized world is read-only.

The phase's real deliverable is the property: every read shape answers identically before
and after finalization, on the same world.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from simcore.schemas import TraceEvent

from . import derive as _derive

KIND_COLUMNS = (
    "stimulus_published",
    "exposure_dropped",
    "turn",
    "guardrail_violation",
    "reflection",
    "memory",
    "belief_snapshot",
    "probe",
    "cost",
    "intervention",
    "degraded",
    "tick_closed",
    "lifecycle",
)


def _row(event: TraceEvent) -> dict:
    """One event fanned out: common columns plus exactly one typed struct column."""
    dumped = _normalize(event.payload.model_dump(mode="json"))
    kind = event.payload.kind
    row: dict = {
        "event_id": event.event_id,
        "world_id": event.world_id,
        "tick": event.tick,
        "seq": event.seq,
        "persona_id": event.persona_id,
        "kind": kind,
    }
    for column in KIND_COLUMNS:
        row[column] = dumped if column == kind else None
    return row


def _normalize(value):
    """Empty structs become null: Parquet cannot write a struct with no child field, and an
    empty belief change carries no information a default does not already state."""
    if isinstance(value, dict):
        if not value:
            return None
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


# Struct fields that are never legitimately null: a null on read is a normalized `{}`.
_EMPTY_STRUCT_KEYS = frozenset({"dimensions", "claim_credence", "belief_change", "change"})
# Map fields keyed by stimulus, dimension or claim: unification null-fills keys a row never
# had, so a null entry on read is an absent key rather than a stored nothing.
_MAP_KEYS = frozenset({"contexts", "dimensions", "claim_credence"})


def _restore(value, *, _in_map: bool = False):
    if isinstance(value, dict):
        restored = {}
        for key, item in value.items():
            if item is None:
                if _in_map:
                    continue
                if key in _EMPTY_STRUCT_KEYS:
                    restored[key] = {}
                else:
                    restored[key] = None
            else:
                restored[key] = _restore(item, _in_map=(key in _MAP_KEYS))
        return restored
    if isinstance(value, list):
        return [_restore(item) for item in value]
    return value


def _events_table(events: tuple[TraceEvent, ...]) -> pa.Table:
    rows = [dict(_row(event)) for event in sorted(events, key=lambda e: (e.persona_id or "", e.tick, e.seq))]
    if not rows:
        schema = pa.schema(
            [("event_id", pa.string()), ("world_id", pa.string()), ("tick", pa.int64()), ("seq", pa.int64()),
             ("persona_id", pa.string()), ("kind", pa.string())]
            + [(column, pa.struct([])) for column in KIND_COLUMNS]
        )
        return pa.Table.from_pylist(rows, schema=schema)
    return pa.Table.from_pylist(rows)


def read_finalized_events(root: Path, run_id: str, world_id: str) -> tuple[TraceEvent, ...]:
    """Every event of one finalized world, strictly validated, in sequence order."""
    from .migrations import load_partition_data

    path = Path(root) / "runs" / run_id / world_id / "events.parquet"
    table = pq.read_table(str(path))
    version = (table.schema.metadata or {}).get(b"contract_version", b"1.0.0").decode("utf-8")
    events: list[TraceEvent] = []
    for row in table.to_pylist():
        kind = row["kind"]
        payload = _restore(dict(row[kind]))
        payload.setdefault("kind", kind)
        events.append(
            TraceEvent.model_validate(
                {
                    "event_id": row["event_id"],
                    "world_id": row["world_id"],
                    "tick": row["tick"],
                    "seq": row["seq"],
                    "persona_id": row["persona_id"],
                    "payload": payload,
                }
            )
        )
    events.sort(key=lambda e: e.seq)
    # Version-aware: an older partition migrates forward through every registered migration,
    # then validates strictly; a newer one is refused naming both versions.
    raw = {"header": json.loads((Path(root) / "runs" / run_id / world_id / "partition.json").read_text())["header"],
           "events": [json.loads(e.model_dump_json()) for e in events]}
    partition = load_partition_data(raw, written_version=version)
    return tuple(partition.events)


def finalize_world(store, run_id: str, world_id: str, world_dir: Path) -> Path:
    """Write one world's lasting record. Idempotent: the second call changes nothing."""
    from simcore.schemas import RunStatus

    live_path = world_dir / "live.sqlite"
    events_path = world_dir / "events.parquet"
    with sqlite3.connect(str(live_path)) as connection:
        finalized = connection.execute("SELECT value FROM meta WHERE key = 'finalized'").fetchone()
        if finalized is not None and finalized[0] == "1" and events_path.exists():
            return world_dir
        header_json = connection.execute("SELECT value FROM meta WHERE key = 'header'").fetchone()
        stored_version = connection.execute("SELECT value FROM meta WHERE key = 'contract_version'").fetchone()
        rows = connection.execute("SELECT event_json FROM events WHERE world_id = ? ORDER BY seq", (world_id,)).fetchall()
    if header_json is None:
        raise ValueError(f"world {world_id} carries no header; create it before finalizing")
    events = tuple(TraceEvent.model_validate(json.loads(payload)) for (payload,) in rows)
    contract_version: str = json.loads(header_json[0])["contract_version"] if header_json else (
        stored_version[0] if stored_version else "1.0.0"
    )
    digest = hashlib.sha256(b"".join(e.model_dump_json().encode() for e in sorted(events, key=lambda e: e.seq))).hexdigest()

    _write_events_parquet(events_path, events, contract_version, run_id, world_id, digest)
    _write_beliefs_parquet(world_dir / "beliefs.parquet", events, contract_version)
    _write_edges_parquet(world_dir / "edges.parquet", events, contract_version)
    (world_dir / "partition.json").write_text(
        json.dumps({"header": json.loads(header_json[0]), "contract_version": contract_version,
                    "events_hash": digest, "event_count": len(events)}, indent=2)
    )
    with sqlite3.connect(str(live_path)) as connection:
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('finalized', '1')")
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('events_hash', ?)", (digest,))
        connection.commit()
    entry = store.registry.entry(run_id)
    if entry is not None and entry.status is not RunStatus.COMPLETED:
        store.registry.update(entry.model_copy(update={"status": RunStatus.COMPLETED, "contract_version": contract_version}))
    return world_dir


def _with_metadata(table: pa.Table, contract_version: str, run_id: str, world_id: str, digest: str) -> pa.Table:
    metadata = dict(table.schema.metadata or {})
    metadata.update({b"contract_version": contract_version.encode(),
                     b"run_id": run_id.encode(), b"world_id": world_id.encode(), b"events_hash": digest.encode()})
    return table.replace_schema_metadata(metadata)


def _write_events_parquet(path: Path, events: tuple[TraceEvent, ...], contract_version: str,
                           run_id: str, world_id: str, digest: str) -> None:
    table = _with_metadata(_events_table(events), contract_version, run_id, world_id, digest)
    pq.write_table(table, str(path))


def _write_beliefs_parquet(path: Path, events: tuple[TraceEvent, ...], contract_version: str) -> None:
    """Beliefs written by the same code that computes them live: one row per persona and tick."""
    personas = sorted({e.persona_id for e in events if e.persona_id is not None})
    rows: list[dict] = []
    for persona_id in personas:
        history = _derive.derive_beliefs(events, persona_id)
        for point in history.points:
            rows.append({
                "persona_id": persona_id,
                "tick": point.tick,
                "value": point.beliefs.dimensions["value"],
                "fit": point.beliefs.dimensions["fit"],
                "trust": point.beliefs.dimensions["trust"],
                "claim_ids": sorted(point.beliefs.claim_credence),
                "credences": [point.beliefs.claim_credence[c] for c in sorted(point.beliefs.claim_credence)],
            })
    schema = pa.schema([("persona_id", pa.string()), ("tick", pa.int64()), ("value", pa.float64()),
                        ("fit", pa.float64()), ("trust", pa.float64()),
                        ("claim_ids", pa.list_(pa.string())), ("credences", pa.list_(pa.float64()))])
    table = pa.Table.from_pylist(rows, schema=schema) if not rows else pa.Table.from_pylist(rows)
    metadata = dict(table.schema.metadata or {})
    metadata[b"contract_version"] = contract_version.encode()
    pq.write_table(table.replace_schema_metadata(metadata), str(path))


def _write_edges_parquet(path: Path, events: tuple[TraceEvent, ...], contract_version: str) -> None:
    """Edges written by the same code that computes them live."""
    edges = _derive.derive_edges(events)
    rows = [{"u": e.u, "v": e.v, "channel": e.channel.value, "count": e.count, "last_tick": e.last_tick} for e in edges]
    schema = pa.schema([("u", pa.string()), ("v", pa.string()), ("channel", pa.string()),
                        ("count", pa.int64()), ("last_tick", pa.int64())])
    table = pa.Table.from_pylist(rows, schema=schema) if not rows else pa.Table.from_pylist(rows)
    metadata = dict(table.schema.metadata or {})
    metadata[b"contract_version"] = contract_version.encode()
    pq.write_table(table.replace_schema_metadata(metadata), str(path))
