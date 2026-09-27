import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Each audience's head count against its quota, its source mix, and what each
   filter costs — counted by the engine, serialised here. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/audiences/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
