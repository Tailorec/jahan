import { NextResponse } from "next/server";
import { engineApiBase, engineFetch, readBriefFile, toBrief } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    try {
      const d = await engineFetch<{ name: string; brief: Record<string, unknown>; evidence: Record<string, unknown> | null }>(
        `/api/briefs/${name}`,
      );
      return NextResponse.json({ name: d.name, brief: toBrief(d.brief, d.name), evidence: d.evidence });
    } catch {
      return NextResponse.json({ error: "brief not found" }, { status: 404 });
    }
  }
  try {
    return NextResponse.json(await readBriefFile(name));
  } catch {
    return NextResponse.json({ error: "brief not found" }, { status: 404 });
  }
}
