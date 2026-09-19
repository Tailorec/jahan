import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { engineApiBase, engineFetch, engineRoot } from "@/lib/server";

const run = promisify(execFile);

/* Author and validate a brief against the engine's own contracts, with the
   assumption ledger it assembles — before a run can start. Proxied to the
   engine API when it serves; otherwise the engine's own `brief check` runs. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as {
    brief_yaml?: unknown; evidence_json?: unknown;
  } | null;
  if (!body || typeof body.brief_yaml !== "string" || !body.brief_yaml.trim()) {
    return NextResponse.json({ error: "brief_yaml (string) is required" }, { status: 422 });
  }
  if (engineApiBase()) {
    try {
      return NextResponse.json(await engineFetch("/api/briefs/validate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }));
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const root = engineRoot();
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "consumersim-brief-"));
  try {
    await fs.writeFile(path.join(tmp, "brief.yaml"), body.brief_yaml);
    if (body.evidence_json && typeof body.evidence_json === "object") {
      await fs.writeFile(path.join(tmp, "brief.yaml.evidence.json"), JSON.stringify(body.evidence_json));
    }
    try {
      const res = await run(
        path.join(root, ".venv", "bin", "python"),
        ["-m", "simcore.cli", "brief", "check", "--brief", path.join(tmp, "brief.yaml"),
          "--ontologies", path.join(root, "ontologies"), "--format", "json"],
        { cwd: root, timeout: 120000, maxBuffer: 4 * 1024 * 1024 },
      );
      return NextResponse.json(JSON.parse(res.stdout));
    } catch (e: unknown) {
      const err = e as { stdout?: string; stderr?: string };
      const detail = (err.stdout ?? err.stderr ?? "").trim() || String(e);
      return NextResponse.json({ valid: false, error: detail }, { status: 422 });
    }
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
}
