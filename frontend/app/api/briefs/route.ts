import { NextResponse } from "next/server";
import { engineFetch, refused, toBrief } from "@/lib/server";

export async function GET() {
  try {
    const data = await engineFetch<{ briefs: { name: string }[] }>("/api/briefs");
    const full = await Promise.all(
      data.briefs.map((b) =>
        engineFetch<{ name: string; brief: Record<string, unknown>; evidence: Record<string, unknown> | null }>(
          `/api/briefs/${encodeURIComponent(b.name)}`,
        ),
      ),
    );
    return NextResponse.json(
      full.map((d) => ({ name: d.name, path: `examples/${d.name}.yaml`, brief: toBrief(d.brief, d.name) })),
    );
  } catch (e) {
    return refused(e);
  }
}
