import { NextResponse } from "next/server";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { engineApiBase, engineFetch } from "@/lib/server";

function corpusSchema(): string {
  if (process.env.SIMCORE_CORPUS_DIR) {
    return path.join(process.env.SIMCORE_CORPUS_DIR, "persona_codes.schema.json");
  }
  return path.join(
    os.homedir(), ".cache", "consumersim", "coreset",
    "MatrAIx2026__MatrAIx_Persona_1M_Public_Release", "persona_codes.schema.json",
  );
}

/* The corpus's own attributes with their declared value sets — read from the
   cached corpus, never from a copy. Proxied to the engine API when it serves
   the record. */
export async function GET(req: Request) {
  if (engineApiBase()) return NextResponse.json(await engineFetch(`/api/codebook${new URL(req.url).search}`));
  const { searchParams } = new URL(req.url);
  const query = (searchParams.get("query") ?? "").toLowerCase();
  const offset = Number(searchParams.get("offset") ?? 0);
  const limit = Math.min(Number(searchParams.get("limit") ?? 50), 200);
  let schema: { columns: { id: string; values: string[] }[] };
  try {
    schema = JSON.parse(await fs.readFile(corpusSchema(), "utf8"));
  } catch {
    return NextResponse.json(
      { error: "no corpus is cached here: author freely, then validate where the corpus is present" },
      { status: 409 },
    );
  }
  const matched = schema.columns
    .filter((c) => c.id.toLowerCase().includes(query))
    .map((c) => ({ id: c.id, values: c.values }));
  return NextResponse.json({ attributes: matched.slice(offset, offset + limit), total: matched.length });
}
