import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Decisions heard in a world's open tick, before it closes — provisional, replaced by the recorded tick. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const q = new URL(req.url).searchParams.toString();
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/live/decisions${q ? `?${q}` : ""}`));
  } catch (e) {
    return refused(e);
  }
}
