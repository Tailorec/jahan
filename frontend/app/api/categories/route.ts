import { NextResponse } from "next/server";
import { engineFetch, refused } from "@/lib/server";

/* The existing categories a description may reuse. */
export async function GET() {
  try {
    return NextResponse.json(await engineFetch("/api/categories"));
  } catch (e) {
    return refused(e);
  }
}
