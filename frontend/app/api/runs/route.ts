import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";
import type { RunSummary } from "@/lib/engine";

export async function GET() {
  try {
    const data = await engineFetch<{ runs: RunSummary[] }>("/api/runs");
    return NextResponse.json(data.runs);
  } catch (e) {
    return refused(e);
  }
}

/* Start a study. The engine runs it as a subprocess under its own id, and refuses what
   would die in its first second: a brief its contracts turn away, a number that is not one,
   a key or an endpoint — those are the server's environment, never a study input. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.brief_yaml !== "string" || !body.brief_yaml.trim()) {
    return NextResponse.json({ error: "brief_yaml (string) is required" }, { status: 422 });
  }
  try {
    const data = await engineFetch<{ run_id: string }>("/api/runs", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    return NextResponse.json(data, { status: 202 });
  } catch (e) {
    return refused(e);
  }
}
