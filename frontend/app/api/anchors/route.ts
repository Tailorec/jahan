import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Every frozen anchor version with its check's verdict, and the scale a study defaults to. */
export async function GET() {
  try {
    return NextResponse.json(await engineFetch("/api/anchors"));
  } catch (e) {
    return refused(e);
  }
}
