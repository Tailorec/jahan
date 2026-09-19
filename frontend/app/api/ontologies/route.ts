import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const version = searchParams.get("version");
  try {
    if (category && version) {
      return NextResponse.json(
        await engineFetch(`/api/ontologies/${encodeURIComponent(category)}/${encodeURIComponent(version)}`),
      );
    }
    // The list, as the pages read it: an array of the versions the engine holds.
    const data = await engineFetch<{ ontologies: unknown[] }>("/api/ontologies");
    return NextResponse.json(data.ontologies);
  } catch (e) {
    return refused(e);
  }
}

/* Save a validated draft as a new version. The engine checks it against the corpus
   and never overwrites an existing version. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { ontology?: Record<string, unknown> } | null;
  const ontology = body?.ontology;
  if (!ontology || typeof ontology !== "object") {
    return NextResponse.json({ error: "ontology (object) is required" }, { status: 422 });
  }
  try {
    return NextResponse.json(
      await engineFetch("/api/ontologies", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ontology }),
      }),
      { status: 201 },
    );
  } catch (e) {
    return refused(e);
  }
}
