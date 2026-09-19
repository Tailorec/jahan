import { NextResponse } from "next/server";
import fs from "node:fs/promises";
import path from "node:path";
import { engineApiBase, engineFetch, engineRoot, listOntologies, readOntology } from "@/lib/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const version = searchParams.get("version");
  // Proxied to the engine API when it serves the record; readers of disk otherwise.
  if (engineApiBase()) {
    if (category && version) {
      try {
        return NextResponse.json(await engineFetch(`/api/ontologies/${category}/${version}`));
      } catch {
        return NextResponse.json({ error: "ontology not found" }, { status: 404 });
      }
    }
    return NextResponse.json(await engineFetch("/api/ontologies"));
  }
  if (category && version) {
    const o = await readOntology(category, version);
    if (!o) return NextResponse.json({ error: "ontology not found" }, { status: 404 });
    return NextResponse.json(o);
  }
  return NextResponse.json(await listOntologies());
}

/* Save a validated draft as a new version. Proxied when the engine API
   serves; otherwise validated by the engine's own check and written here —
   an existing version is never overwritten. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { ontology?: Record<string, unknown> } | null;
  const ontology = body?.ontology;
  if (!ontology || typeof ontology !== "object") {
    return NextResponse.json({ error: "ontology (object) is required" }, { status: 422 });
  }
  if (engineApiBase()) {
    try {
      return NextResponse.json(
        await engineFetch("/api/ontologies", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ ontology }),
        }),
        { status: 201 },
      );
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const category = ontology.category;
  const version = ontology.version;
  if (typeof category !== "string" || typeof version !== "string") {
    return NextResponse.json({ error: "ontology needs a category and a version" }, { status: 422 });
  }
  const dest = path.join(engineRoot(), "ontologies", category, `${version}.json`);
  try {
    await fs.stat(dest);
    return NextResponse.json(
      { error: `${category}@${version} already exists: save as a new version` },
      { status: 409 },
    );
  } catch { /* not there — the only case that proceeds */ }
  const check = await fetch(new URL("/api/ontologies/validate", req.url).toString(), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ontology }),
  });
  if (!check.ok) {
    const detail = await check.json().catch(() => ({}));
    return NextResponse.json(detail, { status: check.status });
  }
  await fs.mkdir(path.dirname(dest), { recursive: true });
  await fs.writeFile(dest, `${JSON.stringify(ontology, null, 2)}\n`);
  return NextResponse.json({ category, version }, { status: 201 });
}
