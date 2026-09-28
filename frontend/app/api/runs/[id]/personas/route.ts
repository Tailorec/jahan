import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* A run's persona records, a page at a time, with the total — every persona the study drew. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const q = new URL(req.url).searchParams.toString();
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/personas${q ? `?${q}` : ""}`));
  } catch (e) {
    return refused(e);
  }
}
