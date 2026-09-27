import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* A follow-up: naming a group adds it, naming none refines every audience. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/draft/followup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
