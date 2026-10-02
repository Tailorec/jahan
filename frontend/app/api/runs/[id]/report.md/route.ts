import { engineApiBase } from "@/lib/server";

/* The report as the study wrote it, passed through as markdown to keep or share. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const res = await fetch(`${engineApiBase()}/api/runs/${encodeURIComponent(id)}/report.md`, { cache: "no-store" });
    return new Response(await res.text(), { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "text/plain" } });
  } catch {
    return new Response("the engine could not be reached", { status: 502 });
  }
}
