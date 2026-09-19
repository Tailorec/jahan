import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The first screen: the engine's workspace summary — derived over registry entries in
   `analysis` — beside the runs, ontologies and briefs it can offer. The interface adds
   nothing up; every number here is a field of a shape the engine produced. */
export async function GET() {
  try {
    const [workspace, runs, ontologies, briefs] = await Promise.all([
      engineFetch<Record<string, unknown>>("/api/workspace"),
      engineFetch<{ runs: unknown[] }>("/api/runs"),
      engineFetch<{ ontologies: unknown[] }>("/api/ontologies"),
      engineFetch<{ briefs: unknown[] }>("/api/briefs"),
    ]);
    return NextResponse.json({
      workspace, runs: runs.runs, ontologies: ontologies.ontologies, briefs: briefs.briefs,
    });
  } catch (e) {
    return refused(e);
  }
}
