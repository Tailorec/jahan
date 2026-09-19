import { NextResponse } from "next/server";
import { readBriefFile } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  try {
    return NextResponse.json(await readBriefFile(name));
  } catch {
    return NextResponse.json({ error: "brief not found" }, { status: 404 });
  }
}
