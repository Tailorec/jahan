import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* How populated each attribute is, per source. The count is made once by the engine and served from then on. */
export async function GET(request: Request) {
  const retry = new URL(request.url).searchParams.get("retry") === "true";
  try {
    return NextResponse.json(await engineFetch(`/api/corpus/coverage${retry ? "?retry=true" : ""}`));
  } catch (e) {
    return refused(e);
  }
}
