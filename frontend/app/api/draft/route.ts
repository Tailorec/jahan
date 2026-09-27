import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* A confirmed category and a reading become audiences and an ontology draft. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/draft", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
