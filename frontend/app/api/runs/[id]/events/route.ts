import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Events for a run scoped by persona, world, kind or ticks — the `events` shape, paged. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const q = new URL(req.url).searchParams.toString();
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/events${q ? `?${q}` : ""}`));
  } catch (e) {
    return refused(e);
  }
}
