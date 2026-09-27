import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Exactly what still stands in the way of Continue. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/who/blockers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
