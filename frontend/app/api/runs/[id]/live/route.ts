import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Each world's digest as of its last closed tick — the numbers a running study can already say. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/live`));
  } catch (e) {
    return refused(e);
  }
}
