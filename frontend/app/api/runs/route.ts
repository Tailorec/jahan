import { NextResponse } from "next/server";
import { listRuns } from "@/lib/server";

export async function GET() {
  return NextResponse.json(await listRuns());
}
