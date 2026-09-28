import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Every persona and every tie of a run's social graph, to draw it whole. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/graph/network`));
  } catch (e) {
    return refused(e);
  }
}
