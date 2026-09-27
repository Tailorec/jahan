/* Server-side access to the engine, over HTTP and nothing else.
   Every engine number the interface shows arrives through the engine API
   (`python -m simcore.web`): the interface's own API routes are proxies to it,
   so there is one path to every number and no second implementation of anything
   the engine already does — no run directory is read, no process is started
   from here. The address is configuration (SIMCORE_WEB_URL), never a study input. */

import { NextResponse } from "next/server";
import type {
  CategoryOntology, GateReport, OutcomeDigest, PopulationManifest, PersonaRecord,
  RunSummary, StudyReport, UITrace, ScenarioSummary,
} from "./engine";
import { refusalText } from "./refusal";

export function engineApiBase(): string {
  const base = process.env.SIMCORE_WEB_URL;
  return (base && base.length ? base : "http://127.0.0.1:8000").replace(/\/$/, "");
}

/* A refusal from the engine, with the reason it gave. The status is the engine's own
   — a brief the engine turns away is a 422 to the browser, never a bare 502 — and the
   message is the sentence the engine wrote, which is the whole point of refusing. */
export class EngineError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function engineFetch<T>(apiPath: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${engineApiBase()}${apiPath}`, { cache: "no-store", ...init });
  } catch {
    throw new EngineError(
      502,
      `the engine API is not reachable at ${engineApiBase()} — start it with: python -m simcore.web`,
    );
  }
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* a refusal without a body */ }
    throw new EngineError(res.status, refusalText(body, `${apiPath}: ${res.status}`));
  }
  return res.json() as Promise<T>;
}

/* What a route answers when the engine refused or could not be reached: the engine's
   status and its reason, in the one shape the browser reads (`error`). */
export function refused(e: unknown): NextResponse {
  if (e instanceof EngineError) return NextResponse.json({ error: e.message }, { status: e.status });
  return NextResponse.json({ error: String(e) }, { status: 500 });
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

/* The engine serves one TraceSummary per run — the file the CLI wrote beside report.json
   when there is one, the same function computed live when there is not. It is the source of
   every number; evidence a finding cites is resolved through `resolve`, and passed in. */
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

/* One run's whole detail, assembled from the engine API: every engine number arrives over
   HTTP and no file is read. Resolved finding evidence is gathered per world
   through `resolve`, capped the way the export script caps it. */
export async function readRunDetailViaApi(runId: string) {
  const id = encodeURIComponent(runId);
  // The run itself must exist; everything else is what the run happens to have. A study
  // that never ran — a gate that refused its population — has a gate report and nothing
  // after it, and that is the case the population page most needs to explain.
  const summary = await engineFetch<RunSummary>(`/api/runs/${id}`);
  const [digest, report, gate, manifest, traceSummary, personas, ontology] = await Promise.all([
    engineFetch<{ digests: OutcomeDigest[]; run_id: string; summaries: Record<string, ScenarioSummary> }>(
      `/api/runs/${id}/digest`,
    ).catch(() => null),
    engineFetch<StudyReport>(`/api/runs/${id}/report`).catch(() => null),
    engineFetch<GateReport>(`/api/runs/${id}/gate`).catch(() => null),
    engineFetch<PopulationManifest>(`/api/runs/${id}/manifest`).catch(() => null),
    engineFetch<TraceSummaryFile>(`/api/runs/${id}/summary`).catch(() => null),
    engineFetch<{ personas: PersonaRecord[]; total: number }>(
      `/api/runs/${id}/personas?limit=6`,
    ).catch(() => null),
    engineFetch<CategoryOntology>(`/api/runs/${id}/ontology`).catch(() => null),
  ]);
  const resolved: UITrace["resolved"] = {};
  if (report && traceSummary) {
    const want: string[] = [];
    for (const f of report.findings ?? []) want.push(...(f.evidence_trace_ids ?? []).slice(0, 12));
    for (const c of report.objection_clusters ?? []) want.push(...(c.verbatim_trace_ids ?? []).slice(0, 4));
    const unique = [...new Set(want)];
    if (unique.length) {
      // One request across every world: a finding cites events from each replicate, and a
      // world's own `resolve` refuses ids that belong to a sibling.
      type Resolved = { events: UITrace["resolved"][string][] };
      const all = await engineFetch<Resolved>(
        `/api/runs/${id}/resolve?${unique.map((t) => `trace_id=${encodeURIComponent(t)}`).join("&")}`,
      ).catch(() => null);
      if (all) {
        for (const e of all.events) resolved[e.event_id] = e;
      } else {
        // The engine refuses a batch with one absent id. Ask for each, and keep what exists.
        const each = await Promise.all(unique.map((t) =>
          engineFetch<Resolved>(`/api/runs/${id}/resolve?trace_id=${encodeURIComponent(t)}`).catch(() => null),
        ));
        for (const chunk of each) for (const e of chunk?.events ?? []) resolved[e.event_id] = e;
      }
    }
  }
  return {
    summary,
    gate,
    manifest,
    digest,
    report,
    trace: traceSummary ? projectSummary(traceSummary, resolved) : null,
    pins: (summary as unknown as { pins: Record<string, { model_id: string }> | null }).pins ?? null,
    personas: personas?.personas ?? null,
    personaTotal: personas?.total ?? 0,
    ontology,
  };
}

export const readRunDetail = readRunDetailViaApi;
