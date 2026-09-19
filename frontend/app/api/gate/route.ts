import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Draw and gate a population for an authored brief, before any study is paid for.
   The engine runs its own `coreset-gate`; a failing draw answers with its gate report,
   which is the case the population page most needs to explain. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body.brief_yaml !== "string" || !body.brief_yaml.trim()) {
    return NextResponse.json({ error: "brief_yaml (string) is required" }, { status: 422 });
  }
  try {
    return NextResponse.json(await engineFetch("/api/gate", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    }));
  } catch (e) {
    return refused(e);
  }
}
