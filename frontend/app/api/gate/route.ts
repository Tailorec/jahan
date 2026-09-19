import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { engineRoot } from "@/lib/server";

const run = promisify(execFile);

/* Run the engine's real population gate on an authored brief — fully offline
   (--fake corpus, fake pins). Mirrors `coreset-gate`: the draw is gated
   before any model is called, a failing draw exits 2 with its gate report. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const briefYaml: string | undefined = body?.brief_yaml;
  const evidenceJson: Record<string, unknown> | undefined = body?.evidence_json;
  const n: number = body?.n ?? 200;
  const seed: number = body?.seed ?? 4021;
  if (!briefYaml || typeof briefYaml !== "string") {
    return NextResponse.json({ error: "brief_yaml (string) required" }, { status: 400 });
  }
  const root = engineRoot();
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "consumersim-brief-"));
  // Gate artefacts persist under runs/ so the new run shows up on the overview.
  const out = path.join(root, "runs");
  try {
    await fs.writeFile(path.join(tmp, "brief.yaml"), briefYaml);
    // Public-source claims cite evidence by URL; intake reads the sidecar
    // beside the brief (brief.yaml.evidence.json), keyed by URL.
    if (evidenceJson && typeof evidenceJson === "object") {
      await fs.writeFile(path.join(tmp, "brief.yaml.evidence.json"), JSON.stringify(evidenceJson));
    }
    const python = path.join(root, ".venv", "bin", "python");
    let stdout = "";
    let stderr = "";
    let code = 0;
    try {
      const res = await run(
        python,
        ["-m", "simcore.cli", "coreset-gate", "--brief", path.join(tmp, "brief.yaml"),
          "--fake", "--n", String(n), "--seed", String(seed),
          "--ontologies", path.join(root, "ontologies"), "--out", out],
        { cwd: root, timeout: 240000, maxBuffer: 16 * 1024 * 1024 },
      );
      stdout = res.stdout;
      stderr = res.stderr;
    } catch (e: unknown) {
      const err = e as { code?: number; stdout?: string; stderr?: string };
      code = err.code ?? 1;
      stdout = err.stdout ?? "";
      stderr = err.stderr ?? "";
    }
    // coreset-gate prints `run_id:` / `artefacts:` — pick up whatever it wrote.
    let gate = null;
    let manifest = null;
    let runId: string | null = null;
    const m = stdout.match(/run_id:\s*(run-\S+)/);
    if (m) {
      runId = m[1];
      try {
        gate = JSON.parse(await fs.readFile(path.join(out, runId, "gate-report.json"), "utf8"));
      } catch { /* failing draw may still write it; tolerate absence */ }
      try {
        manifest = JSON.parse(await fs.readFile(path.join(out, runId, "manifest.json"), "utf8"));
      } catch { /* absent when the gate fails */ }
    }
    return NextResponse.json({ code, run_id: runId, stdout, stderr, gate, manifest });
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
}
