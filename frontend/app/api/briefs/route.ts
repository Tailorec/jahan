import { NextResponse } from "next/server";
import { engineApiBase, engineFetch, listBriefs, toBrief } from "@/lib/server";

export async function GET() {
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    const data = await engineFetch<{ briefs: { name: string }[] }>("/api/briefs");
    const full = await Promise.all(
      data.briefs.map((b) =>
        engineFetch<{ name: string; brief: Record<string, unknown>; evidence: Record<string, unknown> | null }>(
          `/api/briefs/${b.name}`,
        ),
      ),
    );
    return NextResponse.json(
      full.map((d) => ({ name: d.name, path: `examples/${d.name}.yaml`, brief: toBrief(d.brief, d.name) })),
    );
  }
  return NextResponse.json(await listBriefs());
}
