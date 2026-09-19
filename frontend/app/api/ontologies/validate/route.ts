import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Check a draft against the corpus before it can become a version. A refusal keeps the
   engine's reason — what it does not carry, and what the codebook has that resembles it. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { ontology?: unknown } | null;
  const ontology = body?.ontology ?? body;
  if (!ontology || typeof ontology !== "object") {
    return NextResponse.json({ error: "ontology (object) is required" }, { status: 422 });
  }
  try {
    return NextResponse.json(await engineFetch("/api/ontologies/validate", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ontology }),
    }));
  } catch (e) {
    return refused(e);
  }
}
