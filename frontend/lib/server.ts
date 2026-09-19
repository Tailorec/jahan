/* Server-side access to the engine's own artefacts.
   The UI layer reads runs/, ontologies/, examples/ and anchors/ straight from
   the sim_engine checkout (SIM_ENGINE_ROOT, default: repo parent of frontend/).
   Nothing is copied or mocked: these are the files the CLI writes. */

import fs from "node:fs/promises";
import path from "node:path";
import yaml from "js-yaml";
import type {
  Brief, CategoryOntology, GateReport, OutcomeDigest, PopulationManifest,
  RunSummary, StudyReport, UITrace, ScenarioSummary,
} from "./engine";

export function engineRoot(): string {
  return process.env.SIM_ENGINE_ROOT ?? path.join(process.cwd(), "..");
}

async function readJson<T>(p: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(p, "utf8")) as T;
  } catch {
    return null;
  }
}

async function exists(p: string): Promise<boolean> {
  try {
    await fs.stat(p);
    return true;
  } catch {
    return false;
  }
}

function toBrief(raw: Record<string, unknown>, name: string): Brief {
  const claims = ((raw.claims ?? []) as Record<string, unknown>[]).map((c, i) => ({
    id: `C${i + 1}`,
    text: String(c.text ?? ""),
    source: (c.source ?? "assumed") as Brief["claims"][number]["source"],
    evidence_url: (c.evidence_url as string | undefined) ?? null,
  }));
  const price = raw.price as { amount: number; currency: string };
  return {
    product: raw.product as Brief["product"],
    price: { amount: price.amount, currency: price.currency },
    claims,
    competitors: ((raw.competitors ?? []) as Record<string, unknown>[]).map((c) => ({
      name: String(c.name),
      price: (c.price ?? null) as Brief["competitors"][number]["price"],
      claims: ((c.claims ?? []) as unknown[]).map(String),
    })),
    target_market: String(raw.target_market ?? ""),
    audiences: ((raw.audiences ?? []) as Record<string, unknown>[]).map((a) => ({
      name: String(a.name),
      share: (a.share as number | undefined) ?? null,
      attribute_filters: ((a.attribute_filters ?? {}) as Record<string, unknown>) as Record<string, string>,
    })),
    assumptions: ((raw.assumptions ?? []) as Record<string, unknown>[]).map((a) => ({
      text: String(a.text ?? ""),
      source: (a.source ?? "assumed") as Brief["assumptions"][number]["source"],
    })),
    ontology_version: String(raw.ontology_version ?? ""),
  };
}

/* ---------- ontologies ---------- */
export async function listOntologies() {
  const root = path.join(engineRoot(), "ontologies");
  const out: { category: string; version: string; path: string; attributes: string[]; conditioning_set: string[] }[] = [];
  for (const category of await fs.readdir(root).catch(() => [])) {
    const dir = path.join(root, category);
    if (!(await exists(dir))) continue;
    for (const f of await fs.readdir(dir).catch(() => [])) {
      if (!f.endsWith(".json")) continue;
      const o = await readJson<CategoryOntology>(path.join(dir, f));
      if (!o) continue;
      out.push({
        category: o.category, version: o.version, path: `ontologies/${category}/${f}`,
        attributes: Object.keys(o.attribute_domains), conditioning_set: o.conditioning_set,
      });
    }
  }
  return out;
}

export async function readOntology(category: string, version: string) {
  return readJson<CategoryOntology>(
    path.join(engineRoot(), "ontologies", category, `${version}.json`),
  );
}

/* ---------- briefs (examples) ---------- */
export async function listBriefs() {
  const dir = path.join(engineRoot(), "examples");
  const out: { name: string; path: string; brief: Brief }[] = [];
  for (const f of await fs.readdir(dir).catch(() => [])) {
    if (!f.endsWith(".yaml") || f.endsWith(".evidence.json")) continue;
    try {
      const raw = yaml.load(await fs.readFile(path.join(dir, f), "utf8")) as Record<string, unknown>;
      if (!raw || typeof raw !== "object" || !("product" in raw)) continue;
      out.push({ name: f.replace(/\.yaml$/, ""), path: `examples/${f}`, brief: toBrief(raw, f) });
    } catch { /* skip non-brief yaml */ }
  }
  return out;
}

export async function readBriefFile(name: string) {
  const dir = path.join(engineRoot(), "examples");
  const raw = yaml.load(await fs.readFile(path.join(dir, `${name}.yaml`), "utf8")) as Record<string, unknown>;
  const evidence = await readJson<Record<string, unknown>>(path.join(dir, `${name}.yaml.evidence.json`));
  return { name, brief: toBrief(raw, name), evidence };
}

/* ---------- runs ---------- */
export async function listRunIds(): Promise<string[]> {
  const dir = path.join(engineRoot(), "runs");
  const entries = await fs.readdir(dir).catch(() => []);
  const ids: string[] = [];
  for (const e of entries) {
    if ((await fs.stat(path.join(dir, e)).catch(() => null))?.isDirectory()) ids.push(e);
  }
  return ids.sort();
}

export async function readRunSummary(runId: string): Promise<RunSummary | null> {
  const dir = path.join(engineRoot(), "runs", runId);
  const result = await readJson<{
    registry: {
      config: {
        run_id: string; seeds: number[]; budget: { max_cost: number; currency: string };
        scenarios: RunSummary["scenarios"]; pins: Record<string, { model_id: string }>;
      };
      status: RunSummary["status"]; engine_version: string; recorded_cost: number;
      discarded_ticks: number; config_hash: string;
    };
    outcomes: RunSummary["outcomes"]; status: RunSummary["status"];
  }>(path.join(dir, "result.json"));

  const gate = await readJson<GateReport>(path.join(dir, "gate-report.json"));
  const report = await readJson<StudyReport>(path.join(dir, "report.json"));

  if (result) {
    const { registry, outcomes, status } = result;
    return {
      run_id: registry.config.run_id,
      status, engine_version: registry.engine_version,
      recorded_cost: registry.recorded_cost, discarded_ticks: registry.discarded_ticks,
      config_hash: registry.config_hash, seeds: registry.config.seeds,
      budget: registry.config.budget, scenarios: registry.config.scenarios,
      world_ids: outcomes.map((o) => o.world_id), outcomes,
      has_gate_report: gate !== null, has_report: report !== null,
      trust_level: report?.trust.level ?? null,
      finding_count: report?.findings.length ?? 0,
    };
  }
  // Gate-only runs (coreset-gate wrote no result.json yet).
  if (gate) {
    return {
      run_id: runId, status: "partial", recorded_cost: 0, discarded_ticks: 0,
      seeds: [], scenarios: [], world_ids: [], outcomes: [],
      has_gate_report: true, has_report: false,
      trust_level: null, finding_count: 0,
    };
  }
  return null;
}

export async function listRuns(): Promise<RunSummary[]> {
  const out: RunSummary[] = [];
  for (const id of await listRunIds()) {
    const s = await readRunSummary(id);
    if (s) out.push(s);
  }
  return out;
}

export async function readRunDetail(runId: string) {
  const dir = path.join(engineRoot(), "runs", runId);
  const [summary, gate, manifest, digest, report, trace] = await Promise.all([
    readRunSummary(runId),
    readJson<GateReport>(path.join(dir, "gate-report.json")),
    readJson<PopulationManifest>(path.join(dir, "manifest.json")),
    readJson<{ digests: OutcomeDigest[]; run_id: string; summaries: Record<string, ScenarioSummary> }>(
      path.join(dir, "digest.json"),
    ),
    readJson<StudyReport>(path.join(dir, "report.json")),
    readJson<UITrace>(path.join(dir, "ui-trace.json")),
  ]);
  const result = await readJson<{ registry: { config: { pins: Record<string, { model_id: string }> } } }>(
    path.join(dir, "result.json"),
  );
  return { summary, gate, manifest, digest, report, trace, pins: result?.registry.config.pins ?? null };
}

export async function readAnchorsCheck() {
  return readJson<Record<string, unknown>>(
    path.join(engineRoot(), "runs", "run-ssrv2", "anchors-check.json"),
  );
}
