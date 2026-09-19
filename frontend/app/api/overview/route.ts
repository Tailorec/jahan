import { NextResponse } from "next/server";
import { engineRoot, listRuns, listOntologies, listBriefs } from "@/lib/server";

export async function GET() {
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
