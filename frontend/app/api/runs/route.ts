import { NextResponse } from "next/server";
import { engineApiBase, engineFetch, listRuns } from "@/lib/server";
import type { RunSummary } from "@/lib/engine";

export async function GET() {
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    const data = await engineFetch<{ runs: RunSummary[] }>("/api/runs");
    return NextResponse.json(data.runs);
  }
  return NextResponse.json(await listRuns());
}
