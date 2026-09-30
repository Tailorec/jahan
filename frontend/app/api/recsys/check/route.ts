import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Whether the feed's ranking model answers at the engine's endpoint. The engine holds the key; this never sees it. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/recsys/check", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
