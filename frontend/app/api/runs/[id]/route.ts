import { NextResponse } from "next/server";
import { engineFetch, readRunDetail, refused } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    return NextResponse.json(await readRunDetail(id));
  } catch (e) {
    return refused(e);
  }
}

/* Cancel a run: the engine stops the process and loses at most the tick in flight,
   so the run reads partial and a resume picks up after the last closed tick. */
export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" }));
  } catch (e) {
    return refused(e);
  }
}

/* Resume a cancelled run: a re-run with the same id, skipping finished worlds. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const { action } = (await req.json().catch(() => ({}))) as { action?: string };
  if (action !== "resume") return NextResponse.json({ error: "unknown action" }, { status: 422 });
  try {
    return NextResponse.json(
      await engineFetch(`/api/runs/${encodeURIComponent(id)}/resume`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}",
      }),
      { status: 202 },
    );
  } catch (e) {
    return refused(e);
  }
}
