import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Continue to study: validate and say what saving will do. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/who/launch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
