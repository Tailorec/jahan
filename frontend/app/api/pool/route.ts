import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The candidate pool and what each requirement costs — counted by the engine
   over the persona value matrix, serialised here. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/pool", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
