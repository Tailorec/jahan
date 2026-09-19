import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { engineApiBase, engineFetch, engineRoot } from "@/lib/server";

const run = promisify(execFile);

/* Phase 8: read events for a run scoped to persona, world, kind or ticks.
   Proxied to the engine API when configured; otherwise reads trace store. */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const { searchParams } = new URL(req.url);
  if (engineApiBase()) {
    try {
      const q = searchParams.toString();
      return NextResponse.json(
        await engineFetch(`/api/runs/${id}/events${q ? `?${q}` : ""}`),
      );
    } catch (e: unknown) {
      const err = e as { message?: string; status?: number };
      const status = typeof err.status === "number" ? err.status : 502;
      return NextResponse.json({ error: err.message || String(e) }, { status });
    }
  }

  const root = engineRoot();
  const python = path.join(root, ".venv", "bin", "python");
  const pyCode = `
import json
import sys
from pathlib import Path
from simcore.schemas import EventFilter
from simcore.trace import TraceStore

run_dir = Path(sys.argv[1], "runs", sys.argv[2])
params = json.loads(sys.argv[3])

try:
    store = TraceStore(run_dir / "trace")
    view = store.view(sys.argv[2])
    persona_ids = tuple(params.get("persona_id", []))
    world_ids = tuple(params.get("world_id", []))
    kinds = tuple(params.get("kind", []))
    ticks = None
    if "tick_from" in params or "tick_to" in params:
        ticks = (int(params.get("tick_from", 0)), int(params.get("tick_to", 999999)))
    
    flt = EventFilter.model_validate({
        "persona_ids": persona_ids,
        "world_ids": world_ids,
        "kinds": kinds,
        "ticks": ticks,
    })
    events = view.events(flt)
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 200))
    dumped = [json.loads(e.model_dump_json()) for e in events]
    print(json.dumps({"events": dumped[offset:][:limit], "total": len(dumped)}))
except Exception as exc:
    print(json.dumps({"error": str(exc), "status": 500}))
`;

  const queryObj: Record<string, unknown> = {};
  for (const [k, v] of searchParams.entries()) {
    if (k === "persona_id" || k === "world_id" || k === "kind") {
      const arr = (queryObj[k] as string[]) || [];
      arr.push(v);
      queryObj[k] = arr;
    } else {
      queryObj[k] = v;
    }
  }

  try {
    const res = await run(python, ["-c", pyCode, root, id, JSON.stringify(queryObj)], {
      cwd: root,
      timeout: 30000,
    });
    const parsed = JSON.parse(res.stdout);
    if (parsed.status && parsed.status !== 200) {
      return NextResponse.json({ error: parsed.error }, { status: parsed.status });
    }
    return NextResponse.json(parsed);
  } catch (e: unknown) {
    const err = e as { stderr?: string };
    return NextResponse.json({ error: err.stderr || String(e) }, { status: 500 });
  }
}
