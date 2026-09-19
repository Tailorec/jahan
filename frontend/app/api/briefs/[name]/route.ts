import { NextResponse } from "next/server";
import { engineFetch, refused, toBrief } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  try {
    const d = await engineFetch<{ name: string; brief: Record<string, unknown>; evidence: Record<string, unknown> | null }>(
      `/api/briefs/${encodeURIComponent(name)}`,
    );
    return NextResponse.json({ name: d.name, brief: toBrief(d.brief, d.name), evidence: d.evidence });
  } catch (e) {
    return refused(e);
  }
}
