import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* How a study may run: whether an endpoint is configured — never its key. */
export async function GET() {
  try {
    return NextResponse.json(await engineFetch("/api/status"));
  } catch (e) {
    return refused(e);
  }
}
