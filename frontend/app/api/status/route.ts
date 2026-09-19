import { NextResponse } from "next/server";
import { engineApiBase, engineFetch } from "@/lib/server";

/* How a study may run: whether an endpoint is configured — never its key.
   Proxied to the engine API when it serves; otherwise read from this
   server's own environment, booleans only. */
export async function GET() {
  if (engineApiBase()) {
    try {
      return NextResponse.json(await engineFetch("/api/status"));
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const configured = Boolean(process.env.SIMCORE_INFERENCE_BASE_URL ?? process.env.OPENAI_BASE_URL);
  return NextResponse.json({
    engine_version: "checkout",
    endpoint_configured: configured,
    fake_available: true,
  });
}
