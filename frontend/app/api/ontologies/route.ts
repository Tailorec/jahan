import { NextResponse } from "next/server";
import { engineApiBase, engineFetch, listOntologies, readOntology } from "@/lib/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const version = searchParams.get("version");
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    if (category && version) {
      try {
        return NextResponse.json(await engineFetch(`/api/ontologies/${category}/${version}`));
      } catch {
        return NextResponse.json({ error: "ontology not found" }, { status: 404 });
      }
    }
    return NextResponse.json(await engineFetch("/api/ontologies"));
  }
  if (category && version) {
    const o = await readOntology(category, version);
    if (!o) return NextResponse.json({ error: "ontology not found" }, { status: 404 });
    return NextResponse.json(o);
  }
  return NextResponse.json(await listOntologies());
}
