import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Fit drafted audiences to their quotas in the open, flagging every move. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/draft/fit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
