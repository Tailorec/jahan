import { NextResponse } from "next/server";
import { readRunDetail } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const detail = await readRunDetail(id);
  if (!detail.summary) return NextResponse.json({ error: "run not found" }, { status: 404 });
  return NextResponse.json(detail);
}
