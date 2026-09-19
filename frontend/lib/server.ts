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

/* When the engine API serves the record, the interface's own API routes become
   proxies to it rather than readers of disk — one path to every number. When
   unset, pages render the run directory's own artefacts (the server-less mode
   the trace, belief and report pages light up in). */
export function engineApiBase(): string | null {
  const base = process.env.SIMCORE_WEB_URL;
  return base && base.length ? base.replace(/\/$/, "") : null;
}

export async function engineFetch<T>(apiPath: string): Promise<T> {
  const base = engineApiBase();
  if (!base) throw new Error("SIMCORE_WEB_URL is not configured");
  const res = await fetch(`${base}${apiPath}`);
  if (!res.ok) throw new Error(`${apiPath}: ${res.status}`);
  return res.json() as Promise<T>;
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

export function toBrief(raw: Record<string, unknown>, name: string): Brief {
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

/* ---------- trace summary ---------- */

interface TraceSummaryFile {
  run_id: string;
  worlds: string[];
  per_world: {
    world_id: string;
    event_counts: Record<string, number>;
    max_tick: number;
    belief_histories: { persona_id: string; points: { tick: number; beliefs: Record<string, unknown> }[] }[];
    edges: { u: string; v: string; channel: string; count: number; last_tick: number }[];
    verbatim_groups: Record<string, {
      key: string;
      records: { event_id: string; persona_id: string; tick: number; text: string; action: string }[];
    }[]>;
  }[];
  costs: { role: string; calls: number; input_tokens: number; output_tokens: number; cost: number | null }[];
  recorded_cost: number;
}

function flattenBeliefs(b: Record<string, unknown>): Record<string, number> {
  const flat: Record<string, number> = {};
  for (const [k, v] of Object.entries((b.dimensions ?? {}) as Record<string, unknown>)) {
    if (typeof v === "number") flat[k] = v;
  }
  for (const [k, v] of Object.entries((b.claim_credence ?? {}) as Record<string, unknown>)) {
    if (typeof v === "number") flat[k] = v;
  }
  return flat;
}

/* The CLI writes trace-summary.json beside report.json; runs recorded before it
   carry only the legacy ui-trace.json the export script projected. The summary is
   the source of every number; the legacy file contributes resolved finding
   evidence where it exists. */
export function projectSummary(
  summary: TraceSummaryFile,
  resolved: UITrace["resolved"] = {},
): UITrace {
  const trace: UITrace = {
    run_id: summary.run_id,
    worlds: summary.worlds,
    event_counts: {},
    max_tick: {},
    belief_histories: {},
    belief_personas: {},
    edges_top: [],
    verbatim_groups: {},
    costs: summary.costs,
    recorded_cost: summary.recorded_cost,
    resolved,
  };
  for (const world of summary.per_world) {
    trace.event_counts[world.world_id] = world.event_counts;
    trace.max_tick[world.world_id] = world.max_tick;
    trace.belief_personas[world.world_id] = world.belief_histories.map((h) => h.persona_id);
    trace.belief_histories[world.world_id] = Object.fromEntries(
      world.belief_histories.map((h) => [
        h.persona_id,
        h.points.map((p) => ({ tick: p.tick, beliefs: flattenBeliefs(p.beliefs) })),
      ]),
    );
    trace.edges_top.push(...world.edges);
    for (const grouping of ["persona", "tick"] as const) {
      const groups = (world.verbatim_groups[grouping] ?? [])
        .map((g) => ({
          key: g.key,
          count: g.records.length,
          samples: g.records.slice(0, 3).map((r) => ({
            event_id: r.event_id, persona_id: r.persona_id, tick: r.tick,
            text: r.text.slice(0, 500), action: r.action,
          })),
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 24);
      trace.verbatim_groups[grouping] = [...(trace.verbatim_groups[grouping] ?? []), ...groups];
    }
  }
  trace.edges_top.sort((a, b) => b.count - a.count);
  trace.edges_top = trace.edges_top.slice(0, 60);
  for (const grouping of Object.keys(trace.verbatim_groups)) {
    trace.verbatim_groups[grouping].sort((a, b) => b.count - a.count);
    trace.verbatim_groups[grouping] = trace.verbatim_groups[grouping].slice(0, 24);
  }
  return trace;
}

export async function readTrace(runId: string): Promise<UITrace | null> {
  const dir = path.join(engineRoot(), "runs", runId);
  const [summary, legacy] = await Promise.all([
    readJson<TraceSummaryFile>(path.join(dir, "trace-summary.json")),
    readJson<UITrace>(path.join(dir, "ui-trace.json")),
  ]);
  if (!summary) return legacy;
  return projectSummary(summary, legacy?.resolved ?? {});
}

/* The same detail through the engine API: every engine number arrives over
   HTTP and no file is read. Resolved finding evidence is gathered per world
   through `resolve`, capped the way the export script caps it. */
export async function readRunDetailViaApi(runId: string) {
  const [summary, digest, report, gate, manifest, traceSummary] = await Promise.all([
    engineFetch<RunSummary>(`/api/runs/${runId}`),
    engineFetch<{ digests: OutcomeDigest[]; run_id: string; summaries: Record<string, ScenarioSummary> }>(
      `/api/runs/${runId}/digest`,
    ).catch(() => null),
    engineFetch<StudyReport>(`/api/runs/${runId}/report`).catch(() => null),
    engineFetch<GateReport>(`/api/runs/${runId}/gate`).catch(() => null),
    engineFetch<PopulationManifest>(`/api/runs/${runId}/manifest`).catch(() => null),
    engineFetch<TraceSummaryFile>(`/api/runs/${runId}/summary`),
  ]);
  const resolved: UITrace["resolved"] = {};
  if (report) {
    const want: string[] = [];
    for (const f of report.findings ?? []) want.push(...(f.evidence_trace_ids ?? []).slice(0, 12));
    for (const c of report.objection_clusters ?? []) want.push(...(c.verbatim_trace_ids ?? []).slice(0, 4));
    const unique = [...new Set(want)];
    for (const world of traceSummary.worlds ?? []) {
      const missing = unique.filter((id) => !(id in resolved));
      if (!missing.length) break;
      const chunk = await engineFetch<{ events: UITrace["resolved"][string][] }>(
        `/api/runs/${runId}/worlds/${world}/resolve?${missing.map((id) => `trace_id=${encodeURIComponent(id)}`).join("&")}`,
      ).catch(() => null);
      for (const e of chunk?.events ?? []) resolved[e.event_id] = e;
    }
  }
  return {
    summary,
    gate,
    manifest,
    digest,
    report,
    trace: projectSummary(traceSummary, resolved),
    pins: (summary as unknown as { pins: Record<string, { model_id: string }> | null }).pins ?? null,
  };
}

export async function readRunDetail(runId: string) {
  if (engineApiBase()) return readRunDetailViaApi(runId);
  const dir = path.join(engineRoot(), "runs", runId);
  const [summary, gate, manifest, digest, report, trace] = await Promise.all([
    readRunSummary(runId),
    readJson<GateReport>(path.join(dir, "gate-report.json")),
    readJson<PopulationManifest>(path.join(dir, "manifest.json")),
    readJson<{ digests: OutcomeDigest[]; run_id: string; summaries: Record<string, ScenarioSummary> }>(
      path.join(dir, "digest.json"),
    ),
    readJson<StudyReport>(path.join(dir, "report.json")),
    readTrace(runId),
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
