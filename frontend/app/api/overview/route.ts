import { NextResponse } from "next/server";
import { engineApiBase, engineFetch, engineRoot, listRuns, listOntologies, listBriefs } from "@/lib/server";

export async function GET() {
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    const [runs, ontologies, briefs] = await Promise.all([
      engineFetch<{ runs: unknown[] }>("/api/runs"),
      engineFetch<{ ontologies: unknown[] }>("/api/ontologies"),
      engineFetch<{ briefs: unknown[] }>("/api/briefs"),
    ]);
    return NextResponse.json({ runs: runs.runs, ontologies: ontologies.ontologies, briefs: briefs.briefs });
  }
  const [runs, ontologies, briefs] = await Promise.all([listRuns(), listOntologies(), listBriefs()]);
  return NextResponse.json({
    engine_root: engineRoot(),
    runs, ontologies,
    briefs: briefs.map((b) => ({
      name: b.name, path: b.path,
      product: b.brief.product.name, category: b.brief.product.category,
      claims: b.brief.claims.length,
      audiences: b.brief.audiences.map((a) => a.name),
    })),
  });
}
