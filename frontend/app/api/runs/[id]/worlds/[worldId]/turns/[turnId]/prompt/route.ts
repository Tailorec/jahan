import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Reconstruct one turn's prompt from recorded parts, verified against the turn's prompt
   hash. Served transiently — nothing here stores or persists a prompt. A prompt that
   cannot be rebuilt arrives as a refusal with the reason, never as an approximation. */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string; worldId: string; turnId: string }> },
) {
  const { id, worldId, turnId } = await ctx.params;
  try {
    return NextResponse.json(
      await engineFetch(
        `/api/runs/${encodeURIComponent(id)}/worlds/${encodeURIComponent(worldId)}/turns/${encodeURIComponent(turnId)}/prompt`,
      ),
    );
  } catch (e) {
    return refused(e);
  }
}
