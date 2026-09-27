import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Audience sets: what Who you study finishes with, saved by the engine and chosen by a study. */
export async function GET() {
  try {
    return NextResponse.json(await engineFetch("/api/audience-sets"));
  } catch (e) {
    return refused(e);
  }
}

export async function POST(req: Request) {
  try {
    return NextResponse.json(
      await engineFetch("/api/audience-sets", { method: "POST", headers: { "content-type": "application/json" }, body: await req.text() }),
      { status: 201 },
    );
  } catch (e) {
    return refused(e);
  }
}
