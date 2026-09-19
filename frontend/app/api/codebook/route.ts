import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The corpus's own attributes with their declared value sets — read by the engine from
   the cached corpus, never from a copy. */
export async function GET(req: Request) {
  try {
    return NextResponse.json(await engineFetch(`/api/codebook${new URL(req.url).search}`));
  } catch (e) {
    return refused(e);
  }
}
