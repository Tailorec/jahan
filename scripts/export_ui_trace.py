"""Export Trace View answers to `ui-trace.json` for the Next.js UI layer.

Reads a finalized run's parquet partitions through simcore's own
ParquetTraceView (the same Trace View the report cites) and writes a compact,
UI-ready summary: per-world event counts, sampled belief histories, top WOM
edges, verbatim groups, cost ledger by role, and resolved finding evidence.

Usage:
    .venv/bin/python scripts/export_ui_trace.py runs/<run-id> [--worlds w1,w2]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--worlds", default=None)
    ap.add_argument("--belief-personas", type=int, default=12)
    ap.add_argument("--edge-top", type=int, default=60)
    args = ap.parse_args()

    from simcore.schemas.query import EventFilter
    from simcore.trace.views import ParquetTraceView

    run_dir: Path = args.run_dir
    run_id = run_dir.name
    result = json.loads((run_dir / "result.json").read_text())
    world_ids = [o["world_id"] for o in result["outcomes"]]
    if args.worlds:
        want = set(args.worlds.split(","))
        world_ids = [w for w in world_ids if w in want]

    trace_root = run_dir / "trace"
    out: dict = {
        "run_id": run_id,
        "worlds": world_ids,
        "event_counts": {},
        "max_tick": {},
        "belief_histories": {},
        "belief_personas": {},
        "edges_top": [],
        "verbatim_groups": {},
        "costs": [],
        "recorded_cost": result["registry"].get("recorded_cost", 0.0),
        "resolved": {},
    }

    for world_id in world_ids:
        view = ParquetTraceView(str(trace_root), run_id, (world_id,))
        events = view.events(EventFilter())
        counts = Counter(e.payload.kind for e in events)
        out["event_counts"][world_id] = dict(counts)
        out["max_tick"][world_id] = max((e.tick for e in events), default=0)

        # Belief histories: personas with the longest snapshot trails.
        persona_ticks: Counter[str] = Counter(
            e.persona_id for e in events
            if e.payload.kind == "belief_snapshot" and e.persona_id
        )
        chosen = [p for p, _ in persona_ticks.most_common(args.belief_personas)]
        out["belief_personas"][world_id] = chosen
        histories: dict[str, list] = {}
        for pid in chosen:
            try:
                h = view.beliefs(pid)
                histories[pid] = [
                    {"tick": p.tick, "beliefs": json.loads(p.model_dump_json())["beliefs"]}
                    for p in h.points
                ]
            except Exception:
                continue
        out["belief_histories"][world_id] = histories

        # WOM / influence edges.
        try:
            edges = view.edges()
            out["edges_top"] = [
                {"u": e.u, "v": e.v, "channel": e.channel,
                 "count": e.count, "last_tick": e.last_tick}
                for e in sorted(edges, key=lambda e: -e.count)[: args.edge_top]
            ]
        except Exception:
            pass

        # Verbatims grouped by persona and by tick (counts + samples).
        for grouping in ("persona", "tick"):
            try:
                groups = view.verbatims(grouping)  # type: ignore[arg-type]
            except Exception:
                continue
            ranked = sorted(groups, key=lambda g: -len(g.records))
            out["verbatim_groups"][grouping] = [
                {
                    "key": g.key,
                    "count": len(g.records),
                    "samples": [
                        {
                            "event_id": r.event_id,
                            "persona_id": r.persona_id,
                            "tick": r.tick,
                            "text": r.text[:500],
                            "action": r.action,
                        }
                        for r in g.records[:3]
                    ],
                }
                for g in ranked[:24]
            ]

        # Cost ledger by role from cost events.
        roles: dict[str, dict] = {}
        for e in events:
            if e.payload.kind != "cost":
                continue
            p = e.payload
            role = getattr(p, "role", "unknown")
            row = roles.setdefault(role, {"role": role, "calls": 0,
                                          "input_tokens": 0, "output_tokens": 0,
                                          "cost": 0.0})
            row["calls"] += 1
            row["input_tokens"] += getattr(p, "input_tokens", 0) or 0
            row["output_tokens"] += getattr(p, "output_tokens", 0) or 0
            c = getattr(p, "cost", None)
            if c is not None:
                row["cost"] += c
        out["costs"] = list(roles.values())

    # Resolve every finding's cited evidence through the Trace View.
    report_path = run_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        want_ids: list[str] = []
        for f in report.get("findings", []):
            want_ids.extend(f.get("evidence_trace_ids", [])[:12])
        for c in report.get("objection_clusters", [])[:24]:
            want_ids.extend(c.get("verbatim_trace_ids", [])[:4])
        seen: dict[str, bool] = {}
        unique = [i for i in want_ids if not seen.setdefault(i, True) and True]
        # (dedup preserving order)
        unique = list(dict.fromkeys(want_ids))
        for world_id in world_ids:
            view = ParquetTraceView(str(trace_root), run_id, (world_id,))
            missing = [i for i in unique if i not in out["resolved"]]
            if not missing:
                break
            try:
                for e in view.resolve(missing):
                    d = e.model_dump(mode="json")
                    out["resolved"][e.event_id] = {
                        "event_id": e.event_id,
                        "world_id": e.world_id,
                        "tick": e.tick,
                        "seq": e.seq,
                        "persona_id": e.persona_id,
                        "payload": d["payload"],
                    }
            except Exception as exc:
                print(f"resolve skipped for {world_id}: {exc}", file=sys.stderr)

    dest = run_dir / "ui-trace.json"
    dest.write_text(json.dumps(out))
    print(f"wrote {dest} ({dest.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
