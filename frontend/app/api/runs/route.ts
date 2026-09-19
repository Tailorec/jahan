import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { engineApiBase, engineFetch, engineRoot, listRuns } from "@/lib/server";
import type { RunSummary } from "@/lib/engine";

export async function GET() {
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    const data = await engineFetch<{ runs: RunSummary[] }>("/api/runs");
    return NextResponse.json(data.runs);
  }
  return NextResponse.json(await listRuns());
}

const CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz";

function mintRunId(): string {
  let ms = Date.now();
  let time = "";
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD[ms % 32] + time;
    ms = Math.floor(ms / 32);
  }
  const rand = Array.from(randomBytes(10)).map((b) => CROCKFORD[b % 32]).join("");
  return `run-${time}${rand.slice(0, 6)}`;
}

function studyArgv(root: string, runDir: string, runId: string, body: Record<string, unknown>): string[] {
  const argv = [
    path.join(root, ".venv", "bin", "python"), "-m", "simcore.cli", "concepts", "run",
    path.join(runDir, "brief.yaml"),
    "--ontologies", path.join(root, "ontologies"),
    "--anchors", path.join(root, "anchors"),
    "--out", path.join(root, "runs"),
    "--run-id", runId,
    "--n", String(body.n ?? 24),
    "--horizon", String(body.horizon ?? 2),
    "--tick-unit", String(body.tick_unit ?? "day"),
    "--budget", String(body.budget ?? 20.0),
    "--channel", String(body.channel ?? "survey_room"),
    "--seeds", String(body.seeds ?? "4021"),
  ];
  if (body.fake ?? true) {
    argv.push("--fake");
  } else {
    if (!body.model || !body.embed_model) throw new Error("a real study pins model and embed_model");
    argv.push("--model", String(body.model), "--embed-model", String(body.embed_model));
  }
  const versions = (body.anchor_versions as string[] | undefined) ?? ["purchase_intent=v1"];
  for (const v of versions) argv.push("--anchor-version", v);
  return argv;
}

/* Start a study from the interface. Proxied to the engine API when it serves
   the record; otherwise the study runs as a local subprocess — the registry
   is authoritative for what happened, the pid in launch.json only for whether
   it is still running. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.brief_yaml !== "string" || !body.brief_yaml.trim()) {
    return NextResponse.json({ error: "brief_yaml (string) is required" }, { status: 422 });
  }
  if (engineApiBase()) {
    try {
      const data = await engineFetch<{ run_id: string }>("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      return NextResponse.json(data, { status: 202 });
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const root = engineRoot();
  const runId: string = typeof body.run_id === "string" ? body.run_id : mintRunId();
  const runDir = path.join(root, "runs", runId);
  await fs.mkdir(runDir, { recursive: true });
  await fs.writeFile(path.join(runDir, "brief.yaml"), body.brief_yaml);
  if (body.evidence_json && typeof body.evidence_json === "object") {
    await fs.writeFile(path.join(runDir, "brief.yaml.evidence.json"), JSON.stringify(body.evidence_json));
  }
  let argv: string[];
  try {
    argv = studyArgv(root, runDir, runId, body);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 422 });
  }
  const child = spawn(argv[0], argv.slice(1), { cwd: root, detached: true, stdio: "ignore" });
  child.unref();
  await fs.writeFile(
    path.join(runDir, "launch.json"),
    JSON.stringify({ argv, cwd: root, pid: child.pid ?? null }, null, 2),
  );
  return NextResponse.json({ run_id: runId }, { status: 202 });
}
