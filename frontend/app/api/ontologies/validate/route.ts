import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { engineApiBase, engineFetch, engineRoot } from "@/lib/server";

const run = promisify(execFile);

function python(): string {
  return path.join(engineRoot(), ".venv", "bin", "python");
}

function corpusArgs(): string[] {
  return process.env.SIMCORE_CORPUS_DIR ? ["--corpus", process.env.SIMCORE_CORPUS_DIR] : [];
}

/* Check a draft against the corpus before it can become a version. Proxied
   to the engine API when it serves the record; otherwise the engine's own
   `ontology check` runs the refusal. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { ontology?: unknown } | null;
  const ontology = body?.ontology ?? body;
  if (!ontology || typeof ontology !== "object") {
    return NextResponse.json({ error: "ontology (object) is required" }, { status: 422 });
  }
  if (engineApiBase()) {
    try {
      return NextResponse.json(await engineFetch("/api/ontologies/validate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ontology }),
      }));
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "consumersim-onto-"));
  try {
    await fs.writeFile(path.join(tmp, "draft.json"), JSON.stringify(ontology));
    try {
      const res = await run(
        python(),
        ["-m", "simcore.cli", "ontology", "check", "--ontology", path.join(tmp, "draft.json"), ...corpusArgs()],
        { cwd: engineRoot(), timeout: 120000, maxBuffer: 4 * 1024 * 1024 },
      );
      return NextResponse.json({ valid: true, detail: res.stdout.trim() });
    } catch (e: unknown) {
      const err = e as { code?: number; stdout?: string; stderr?: string };
      const detail = (err.stdout ?? err.stderr ?? "").trim() || String(e);
      // A refusal (exit 2) names what moved; without a corpus (exit 2 with
      // the cache message) the draft stays a draft.
      const noCorpus = detail.includes("no corpus is cached");
      return NextResponse.json({ valid: false, error: detail }, { status: noCorpus ? 409 : 422 });
    }
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
}
