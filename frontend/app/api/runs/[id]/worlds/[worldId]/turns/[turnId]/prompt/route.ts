import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { engineApiBase, engineFetch, engineRoot } from "@/lib/server";

const run = promisify(execFile);

/* Phase 8: reconstruct one turn's prompt from recorded parts, verified against
   the turn's prompt hash. Serves transiently — nothing here stores or persists
   a prompt. */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string; worldId: string; turnId: string }> },
) {
  const { id, worldId, turnId } = await ctx.params;
  if (engineApiBase()) {
    try {
      return NextResponse.json(
        await engineFetch(`/api/runs/${id}/worlds/${worldId}/turns/${turnId}/prompt`),
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
from simcore.agent import Unreconstructible, reconstruct_turn
from simcore.schemas import CategoryOntology, EventFilter, Persona
from simcore.trace import TraceStore

run_dir = Path(sys.argv[1], "runs", sys.argv[2])
world_id = sys.argv[3]
event_id = sys.argv[4]

try:
    store = TraceStore(run_dir / "trace")
    view = store.view(sys.argv[2], world_id)
    resolved = view.resolve([event_id])
except KeyError as exc:
    print(json.dumps({"error": str(exc), "status": 404}))
    sys.exit(0)
except Exception as exc:
    print(json.dumps({"error": str(exc), "status": 500}))
    sys.exit(0)

event = resolved[0]
if event.payload.kind != "turn" or event.persona_id is None:
    print(json.dumps({"error": f"{event_id} is not a turn", "status": 422}))
    sys.exit(0)

personas_path = run_dir / "personas.json"
personas = []
if personas_path.exists():
    try:
        personas = (json.loads(personas_path.read_text()) or {}).get("personas", [])
    except Exception:
        pass

target_persona = None
for p in personas:
    if isinstance(p, dict) and p.get("persona_id") == event.persona_id:
        try:
            target_persona = Persona.model_validate(p)
            break
        except Exception:
            pass

if target_persona is None:
    print(json.dumps({"error": "the turn's persona has no record in personas.json", "status": 422}))
    sys.exit(0)

ontology_path = run_dir / "ontology.json"
ontology = None
if ontology_path.exists():
    try:
        ontology = CategoryOntology.model_validate(json.loads(ontology_path.read_text()))
    except Exception:
        pass

persona_events = view.events(EventFilter.model_validate({"persona_ids": (event.persona_id,)}))
texts = {}
for e in view.events(EventFilter.model_validate({"kinds": ("stimulus_published",)})):
    texts[e.payload.stimulus.stimulus_id] = e.payload.stimulus.text

rebuilt = reconstruct_turn(
    event.payload, event, persona=target_persona, ontology=ontology,
    persona_events=persona_events, stimulus_texts=texts,
)
if isinstance(rebuilt, Unreconstructible):
    print(json.dumps({"error": rebuilt.reason, "status": 422}))
    sys.exit(0)

print(json.dumps({
    "event_id": event_id,
    "shape": rebuilt.shape,
    "messages": [dict(m) for m in rebuilt.messages],
    "rejected_verified": rebuilt.rejected_verified,
    "status": 200,
}))
`;

  try {
    const res = await run(python, ["-c", pyCode, root, id, worldId, turnId], {
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
