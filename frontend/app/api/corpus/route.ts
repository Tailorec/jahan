import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* What the corpus offers a study: which shards are cached and which sources exist — never a path. */
export async function GET() {
  try {
    return NextResponse.json(await engineFetch("/api/corpus"));
  } catch (e) {
    return refused(e);
  }
}
