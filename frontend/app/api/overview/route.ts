import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The first screen: the engine's workspace summary — derived over registry entries in
   `analysis` — beside the runs and ontologies it can offer. The interface adds
   nothing up; every number here is a field of a shape the engine produced. */
export async function GET() {
  try {
    const [workspace, runs, ontologies] = await Promise.all([
      engineFetch<Record<string, unknown>>("/api/workspace"),
      engineFetch<{ runs: unknown[] }>("/api/runs"),
      engineFetch<{ ontologies: unknown[] }>("/api/ontologies"),
    ]);
    return NextResponse.json({
      workspace, runs: runs.runs, ontologies: ontologies.ontologies,
    });
  } catch (e) {
    return refused(e);
  }
}
