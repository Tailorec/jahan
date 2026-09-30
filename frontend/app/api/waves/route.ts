import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The survey waves a study will run and the answers they take — derived by the engine, serialised here. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/waves", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
