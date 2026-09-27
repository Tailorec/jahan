import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* One attribute's values with counts per source among the candidate pool,
   plus the other ways the corpus asks the same question. */
export async function GET(req: Request, { params }: { params: Promise<{ attribute: string }> }) {
  try {
    const { attribute } = await params;
    return NextResponse.json(await engineFetch(`/api/codebook/${attribute}/values${new URL(req.url).search}`));
  } catch (e) {
    return refused(e);
  }
}
