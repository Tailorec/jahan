import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { engineApiBase, engineFetch, engineRoot, listRuns, listOntologies, listBriefs } from "@/lib/server";

const run = promisify(execFile);

/* The engine derives its own workspace summary; the interface computes nothing. */
async function workspaceOnDisk(): Promise<Record<string, unknown> | null> {
  try {
    const res = await run(
      path.join(engineRoot(), ".venv", "bin", "python"),
      [path.join("scripts", "workspace_summary.py")],
      { cwd: engineRoot(), timeout: 120000, maxBuffer: 8 * 1024 * 1024 },
    );
    return JSON.parse(res.stdout);
  } catch {
    return null;
  }
}

export async function GET() {
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    const [workspace, runs, ontologies, briefs] = await Promise.all([
      engineFetch<Record<string, unknown>>("/api/workspace"),
      engineFetch<{ runs: unknown[] }>("/api/runs"),
      engineFetch<{ ontologies: unknown[] }>("/api/ontologies"),
      engineFetch<{ briefs: unknown[] }>("/api/briefs"),
    ]);
    return NextResponse.json({
      workspace: workspace, runs: runs.runs, ontologies: ontologies.ontologies, briefs: briefs.briefs,
    });
  }
  const [workspace, runs, ontologies, briefs] = await Promise.all([
    workspaceOnDisk(), listRuns(), listOntologies(), listBriefs(),
  ]);
  return NextResponse.json({
    engine_root: engineRoot(),
    workspace, runs, ontologies,
    briefs: briefs.map((b) => ({
      name: b.name, path: b.path,
      product: b.brief.product.name, category: b.brief.product.category,
      claims: b.brief.claims.length,
      audiences: b.brief.audiences.map((a) => a.name),
    })),
  });
}
