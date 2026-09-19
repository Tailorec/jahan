import { NextResponse } from "next/server";
import { listOntologies, readOntology } from "@/lib/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const version = searchParams.get("version");
  if (category && version) {
    const o = await readOntology(category, version);
    if (!o) return NextResponse.json({ error: "ontology not found" }, { status: 404 });
    return NextResponse.json(o);
  }
  return NextResponse.json(await listOntologies());
}
