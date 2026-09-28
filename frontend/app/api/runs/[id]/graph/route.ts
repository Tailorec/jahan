import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* A run's social graph, read by the engine: its shape, the spread of ties, the hubs and one persona's circle. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const q = new URL(req.url).searchParams.toString();
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/graph${q ? `?${q}` : ""}`));
  } catch (e) {
    return refused(e);
  }
}
