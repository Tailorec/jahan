import { NextResponse } from "next/server";
import { listBriefs } from "@/lib/server";

export async function GET() {
  return NextResponse.json(await listBriefs());
}
