"""Export a run's trace summary for the Next.js UI layer.

Builds `trace-summary.json` through `simcore.analysis.trace_summary` — the one
implementation that joins the five shapes — over the run's finalized record, then
projects the legacy `ui-trace.json` the interface reads today (counts, sampled
belief histories, top edges, verbatim samples, costs, resolved finding evidence).

Usage:
    .venv/bin/python scripts/export_ui_trace.py runs/<run-id> [--worlds w1,w2]

New runs do not need this: the CLI writes `trace-summary.json` beside
`report.json` at the end of every run. It exists for runs recorded before the
summary was an artefact.
"""

from __future__ import annotations

import argparse
import json
import sys
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

    from simcore.analysis import trace_summary
    from simcore.trace.views import ParquetTraceView

    run_dir: Path = args.run_dir
    run_id = run_dir.name
    result = json.loads((run_dir / "result.json").read_text())
    world_ids = [o["world_id"] for o in result["outcomes"]]
    if args.worlds:
        want = set(args.worlds.split(","))
        world_ids = [w for w in world_ids if w in want]

    trace_root = run_dir / "trace"
    views = {world_id: ParquetTraceView(str(trace_root), run_id, (world_id,)) for world_id in world_ids}

    # The engine's own join — every number below comes from this object.
    summary = trace_summary(views, run_id=run_id)
    summary_dest = run_dir / "trace-summary.json"
    summary_dest.write_text(summary.model_dump_json(indent=2) + "\n")

    dumped = json.loads(summary.model_dump_json())
    by_world = {world["world_id"]: world for world in dumped["per_world"]}
    out: dict = {
        "run_id": run_id,
        "worlds": dumped["worlds"],
        "event_counts": {},
        "max_tick": {},
        "belief_histories": {},
        "belief_personas": {},
        "edges_top": [],
        "verbatim_groups": {},
        "costs": [],
        "recorded_cost": dumped["recorded_cost"],
        "resolved": {},
    }

    for world_id in world_ids:
        world = by_world[world_id]
        out["event_counts"][world_id] = world["event_counts"]
        out["max_tick"][world_id] = world["max_tick"]
        chosen = [history["persona_id"] for history in world["belief_histories"]][: args.belief_personas]
        out["belief_personas"][world_id] = chosen
        out["belief_histories"][world_id] = {
            history["persona_id"]: [
                {"tick": point["tick"], "beliefs": _flatten(point["beliefs"])}
                for point in history["points"]
            ]
            for history in world["belief_histories"]
            if history["persona_id"] in set(chosen)
        }
        top = sorted(world["edges"], key=lambda e: -e["count"])[: args.edge_top]
        out["edges_top"].extend(top)
        for grouping in ("persona", "tick"):
            groups = sorted(
                world["verbatim_groups"].get(grouping, []),
                key=lambda g: -len(g["records"]),
            )[:24]
            out["verbatim_groups"].setdefault(grouping, []).extend([
                {
                    "key": group["key"],
                    "count": len(group["records"]),
                    "samples": [
                        {
                            "event_id": record["event_id"],
                            "persona_id": record["persona_id"],
                            "tick": record["tick"],
                            "text": record["text"][:500],
                            "action": record["action"],
                        }
                        for record in group["records"][:3]
                    ],
                }
                for group in groups
            ])

    out["costs"] = [
        {
            "role": row["role"],
            "calls": row["calls"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cost": row["cost"],
        }
        for row in dumped["costs"]
    ]

    # Resolve every finding's cited evidence through the Trace View.
    report_path = run_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        want_ids: list[str] = []
        for f in report.get("findings", []):
            want_ids.extend(f.get("evidence_trace_ids", [])[:12])
        for c in report.get("objection_clusters", [])[:24]:
            want_ids.extend(c.get("verbatim_trace_ids", [])[:4])
        unique = list(dict.fromkeys(want_ids))
        for world_id in world_ids:
            missing = [i for i in unique if i not in out["resolved"]]
            if not missing:
                break
            try:
                for e in views[world_id].resolve(missing):
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
    print(f"wrote {summary_dest} ({summary_dest.stat().st_size / 1024:.0f} KiB)")
    print(f"wrote {dest} ({dest.stat().st_size / 1024:.0f} KiB)")
    return 0


def _flatten(beliefs: dict) -> dict:
    """A `Beliefs` snapshot as one flat record: dimensions beside claim credences."""
    flat = dict(beliefs.get("dimensions", {}))
    for claim, credence in (beliefs.get("claim_credence") or {}).items():
        flat[claim] = credence
    return flat


if __name__ == "__main__":
    raise SystemExit(main())
