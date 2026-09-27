import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

export async function GET(_req: Request, { params }: { params: Promise<{ category: string; id: string }> }) {
  try {
    const { category, id } = await params;
    return NextResponse.json(await engineFetch(`/api/audience-sets/${encodeURIComponent(category)}/${encodeURIComponent(id)}`));
  } catch (e) {
    return refused(e);
  }
}
