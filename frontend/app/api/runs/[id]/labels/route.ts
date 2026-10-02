import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Name or rename one version of a run — recorded beside the run, outside its identity (ADR 0052). */
export async function PUT(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    return NextResponse.json(await engineFetch(`/api/runs/${encodeURIComponent(id)}/labels`, {
      method: "PUT", headers: { "content-type": "application/json" }, body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
