import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Author and validate a brief against the engine's own contracts before a run can
   start. A refusal keeps the engine's reason; a valid brief comes back with the
   assumption ledger it assembles — stated, assumed and unstated. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { brief_yaml?: unknown } | null;
  if (!body || typeof body.brief_yaml !== "string" || !body.brief_yaml.trim()) {
    return NextResponse.json({ error: "brief_yaml (string) is required" }, { status: 422 });
  }
  try {
    return NextResponse.json(await engineFetch("/api/briefs/validate", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    }));
  } catch (e) {
    return refused(e);
  }
}
