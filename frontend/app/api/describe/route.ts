import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* Read the description into groups, shared traits and topics, and match the category. */
export async function POST(req: Request) {
  try {
    return NextResponse.json(await engineFetch("/api/describe", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
    }));
  } catch (e) {
    return refused(e);
  }
}
