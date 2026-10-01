"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { useSessionState } from "@/lib/session";
import { PageHead, Chip, Callout, TrustLine } from "@/components/ui";
import { useApi, useRunId, whyNot } from "@/lib/api";
import type { BeliefPoint, TraceEdge, TraceEvent, UITrace } from "@/lib/engine";

interface Detail {
  trace: UITrace | null;
  manifest: { persona_ids: string[] } | null;
  report: { trust: { level: string } } | null;
}

interface ReconstructedPromptData {
  event_id: string;
  shape: string;
  messages: { role: string; content: string }[];
  rejected_verified?: boolean;
}

const KIND_LABEL: Record<string, string> = {
  stimulus_published: "stimulus", exposure_dropped: "dropped", turn: "turn",
  guardrail_violation: "violation", reflection: "reflection", memory: "memory",
  belief_snapshot: "belief", probe: "probe", cost: "cost", intervention: "intervention",
  degraded: "degraded", tick_closed: "tick closed", lifecycle: "lifecycle",
};

function BeliefChart({ history }: { history: BeliefPoint[] }) {
  const W = 560, H = 180, L = 40, R = 552, T = 14, B = 158;
  const dims = ["value", "fit", "trust"] as const;
  const colors = ["var(--seg1)", "var(--seg2)", "var(--seg3)"];
  const maxTick = Math.max(...history.map((p) => p.tick), 1);
  const x = (t: number) => L + (t / maxTick) * (R - L);
  const y = (v: number) => B - ((v - 1) / 4) * (B - T);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Belief history">
      {[1, 2, 3, 4, 5].map((g) => (
        <g key={g}><line className="gridline" x1={L} x2={R} y1={y(g)} y2={y(g)} /><text x={L - 6} y={y(g) + 3} textAnchor="end">{g}</text></g>
      ))}
      {dims.map((d, di) => (
        <polyline key={d} fill="none" stroke={colors[di]} strokeWidth="2"
          points={history.map((p) => `${x(p.tick).toFixed(1)},${y(p.beliefs[d] ?? 3).toFixed(1)}`).join(" ")} />
      ))}
      {dims.map((d, di) => <text key={d} x={R} y={14 + di * 13} fill={colors[di]} textAnchor="end" style={{ fontWeight: 600 }}>{d}</text>)}
    </svg>
  );
}

function summarize(ev: TraceEvent): string {
  const p = ev.payload;
  switch (p.kind) {
    case "lifecycle": return `lifecycle → ${p.phase}`;
    case "tick_closed": return "tick recorded whole";
    case "turn": return `turn${p.action ? ` · ${String(p.action)}` : ""}${p.text ? ` — “${String(p.text).slice(0, 120)}”` : ""}`;
    case "belief_snapshot": return `beliefs ${Object.entries((p.beliefs ?? {}) as Record<string, number>).map(([k, v]) => `${k} ${Number(v).toFixed(2)}`).join(" · ")}`;
    case "memory": return `remembered: “${String(p.text ?? p.memory ?? "").slice(0, 120)}”`;
    case "reflection": return `reflection (${String(p.trigger ?? "")})`;
    case "cost": return `${String(p.role)} · ${Number(p.input_tokens ?? 0) + Number(p.output_tokens ?? 0)} tokens${p.cost != null ? ` · $${Number(p.cost).toFixed(4)}` : ""}`;
    case "stimulus_published": return `stimulus ${String(p.stimulus_id ?? (p.stimulus as Record<string, unknown> | undefined)?.id ?? "")}`;
    case "probe": return `character probe → ${String(p.result ?? JSON.stringify(p).slice(0, 80))}`;
    case "degraded": return `degraded to rung ${String(p.rung)}`;
    case "intervention": return `intervention ${String(p.intervention_kind ?? "")}`;
    default: return p.kind;
  }
}

export default function TracePage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const [q, setQ] = useSessionState<"persona" | "events" | "beliefs" | "edges" | "verbatims" | "resolve">("trace:q", "persona");
  const [world, setWorld] = React.useState<string | null>(null);
  const [kind, setKind] = useSessionState<string>("trace:kind", "turn");
  const [persona, setPersona] = React.useState<string | null>(null);
  const [resolveId, setResolveId] = React.useState<string | null>(null);

  // Phase 8: ephemeral reconstructed prompt state.
  // CRITICAL: Prompts are never stored or persisted (no localStorage, no sessionStorage, no file write).
  const [reconstructedTurnId, setReconstructedTurnId] = React.useState<string | null>(null);
  const [reconstructedPrompt, setReconstructedPrompt] = React.useState<ReconstructedPromptData | null>(null);
  const [promptLoading, setPromptLoading] = React.useState<boolean>(false);
  const [promptError, setPromptError] = React.useState<string | null>(null);

  // Phase 8: persona events timeline loaded from engine
  const [personaEvents, setPersonaEvents] = React.useState<TraceEvent[]>([]);
  const [personaEventsLoading, setPersonaEventsLoading] = React.useState<boolean>(false);

  const t = data?.trace ?? null;
  const worlds = t?.worlds ?? [];
  const w = world ?? worlds[0] ?? null;

  const histories: Record<string, BeliefPoint[]> = (w ? t?.belief_histories[w] : undefined) ?? {};
  const histPersonas: string[] = (w ? t?.belief_personas[w] : undefined) ?? [];
  const activePersona = persona ?? histPersonas[0] ?? null;

  React.useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const r = qs.get("resolve");
    if (r) { setResolveId(r); setQ("resolve"); }
    const p = qs.get("persona");
    if (p) { setPersona(p); setQ("persona"); }
    const ww = qs.get("world");
    if (ww) setWorld(ww);
  }, []);

  // Fetch persona's own events for the timeline
  React.useEffect(() => {
    if (!runId || !activePersona) return;
    let cancelled = false;
    setPersonaEventsLoading(true);
    fetch(`/api/runs/${runId}/events?persona_id=${encodeURIComponent(activePersona)}${w ? `&world_id=${encodeURIComponent(w)}` : ""}&limit=200`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`status ${res.status}`))))
      .then((payload) => {
        if (!cancelled) {
          const rawEvents: TraceEvent[] = payload.events ?? [];
          // Phase 8 acceptance criterion:
          // A persona's events, beliefs and verbatims are shown in one timeline, and none of another persona's appear in it
          const filtered = rawEvents.filter((e) => e.persona_id === activePersona || !e.persona_id);
          setPersonaEvents(filtered);
        }
      })
      .catch(() => {
        if (!cancelled) setPersonaEvents([]);
      })
      .finally(() => {
        if (!cancelled) setPersonaEventsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, activePersona, w]);

  // Phase 8: Prompt reconstruction action
  const handleReconstructPrompt = async (turnEventId: string) => {
    if (!runId || !w) return;
    setReconstructedTurnId(turnEventId);
    setPromptLoading(true);
    setPromptError(null);
    setReconstructedPrompt(null);
    try {
      const res = await fetch(`/api/runs/${runId}/worlds/${w}/turns/${turnEventId}/prompt`);
      const body = await res.json();
      if (!res.ok) {
        // Acceptance criterion: A prompt that cannot be reconstructed says so and why, rather than showing an approximation
        setPromptError(body.error || body.detail || `Cannot reconstruct prompt (status ${res.status})`);
      } else {
        setReconstructedPrompt(body);
      }
    } catch (e: unknown) {
      setPromptError(`Cannot reconstruct prompt: ${whyNot(e)}`);
    } finally {
      setPromptLoading(false);
    }
  };

  const resolved: TraceEvent | null = (resolveId && t?.resolved[resolveId]) ? t.resolved[resolveId] : null;
  const hist = activePersona ? histories[activePersona] : null;

  // Phase 8: Influence neighbourhood drawn from recorded edges
  const personaEdges = (t?.edges_top ?? []).filter(
    (e) => activePersona && (e.u === activePersona || e.v === activePersona),
  );
  const heardFrom = personaEdges.filter((e) => e.v === activePersona);
  const heardBy = personaEdges.filter((e) => e.u === activePersona);

  // Phase 8: Belief movement before and after
  const initialBeliefs = hist && hist.length > 0 ? hist[0].beliefs : null;
  const finalBeliefs = hist && hist.length > 0 ? hist[hist.length - 1].beliefs : null;

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Trace view</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Trace view"
        sub="The fixed set of questions that can be asked of a run's record — events, beliefs, edges, verbatims, resolve. Nothing that reads it can reach past it."
        actions={w && <><span className="chip plain mono">world {w}</span><span className="chip plain mono">tick ≤ {t?.max_tick[w]}</span></>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading trace…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !t && <Callout icon="alert"><div>No trace-summary.json for this run yet — it is written beside report.json at the end of every run, or backfill with <span className="mono">scripts/export_ui_trace.py runs/{runId}</span>.</div></Callout>}
      {t && w && (
        <>
          <div className="tabs" role="tablist">
            {[
              ["persona", "Persona history"],
              ["events", "Events"],
              ["beliefs", "Beliefs"],
              ["edges", "Edges"],
              ["verbatims", "Verbatims"],
              ["resolve", "Resolve"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={`tab${q === id ? " active" : ""}`}
                role="tab"
                aria-selected={q === id}
                onClick={() => setQ(id as typeof q)}
              >
                {label}
              </button>
            ))}
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <select className="input" value={w} onChange={(e) => setWorld(e.target.value)} style={{ maxWidth: 160 }}>
                {worlds.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </div>
          </div>

          {/* Phase 8: One persona's whole history */}
          {q === "persona" && (
            <div style={{ display: "grid", gap: 16 }}>
              <div className="panel">
                <div className="panel-head">
                  <h2>One persona’s whole history</h2>
                  <span className="hint">Timeline of events, beliefs, verbatims and verified prompts</span>
                  <div className="tools">
                    <select
                      className="input mono"
                      value={activePersona ?? ""}
                      onChange={(e) => setPersona(e.target.value)}
                      style={{ maxWidth: 280 }}
                    >
                      {histPersonas.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </div>
                </div>
                <div className="panel-body">
                  {!activePersona ? (
                    <div className="empty">No persona selected.</div>
                  ) : (
                    <div style={{ display: "grid", gap: 20 }}>
                      {/* Belief movement per dimension and per claim, before and after */}
                      <div>
                        <h3>Belief movement</h3>
                        <p className="sub" style={{ fontSize: 13, marginBottom: 12 }}>
                          Movement per dimension and per claim, before and after, from recorded snapshots and turns.
                        </p>
                        {initialBeliefs && finalBeliefs ? (
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
                            {["value", "fit", "trust"].map((dim) => {
                              const before = initialBeliefs[dim] ?? 0;
                              const after = finalBeliefs[dim] ?? 0;
                              const delta = after - before;
                              return (
                                <div key={dim} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12 }}>
                                  <div className="mono sub" style={{ fontSize: 11, textTransform: "uppercase" }}>{dim}</div>
                                  <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
                                    <span style={{ fontSize: 18, fontWeight: 600 }}>{before.toFixed(2)} → {after.toFixed(2)}</span>
                                    <span className="mono" style={{ fontSize: 12, color: delta >= 0 ? "var(--seg1)" : "var(--warn)" }}>
                                      {delta >= 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2)}
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                        {hist && hist.length > 0 && (
                          <div className="chart-wrap" style={{ marginTop: 8 }}><BeliefChart history={hist} /></div>
                        )}
                      </div>

                      {/* Influence neighbourhood */}
                      <div>
                        <h3>Influence neighbourhood</h3>
                        <p className="sub" style={{ fontSize: 13, marginBottom: 10 }}>
                          Recorded edges for this persona naming the channel and how often.
                        </p>
                        <div className="grid g2">
                          <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12 }}>
                            <b>Heard from</b> <span className="sub">({heardFrom.length} contacts)</span>
                            {heardFrom.length === 0 ? (
                              <p className="sub" style={{ marginTop: 8, fontSize: 12 }}>None — persona received no word-of-mouth edges.</p>
                            ) : (
                              <table className="tbl tight" style={{ marginTop: 8 }}>
                                <thead><tr><th>From</th><th>Channel</th><th className="num">Times</th><th className="num">Last tick</th></tr></thead>
                                <tbody>
                                  {heardFrom.map((e, idx) => (
                                    <tr key={idx}>
                                      <td className="mono">{e.u}</td>
                                      <td className="mono">{e.channel}</td>
                                      <td className="num">{e.count}</td>
                                      <td className="num">{e.last_tick}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                          <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12 }}>
                            <b>Heard by</b> <span className="sub">({heardBy.length} contacts)</span>
                            {heardBy.length === 0 ? (
                              <p className="sub" style={{ marginTop: 8, fontSize: 12 }}>None — persona delivered no word-of-mouth edges.</p>
                            ) : (
                              <table className="tbl tight" style={{ marginTop: 8 }}>
                                <thead><tr><th>To</th><th>Channel</th><th className="num">Times</th><th className="num">Last tick</th></tr></thead>
                                <tbody>
                                  {heardBy.map((e, idx) => (
                                    <tr key={idx}>
                                      <td className="mono">{e.v}</td>
                                      <td className="mono">{e.channel}</td>
                                      <td className="num">{e.count}</td>
                                      <td className="num">{e.last_tick}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Timeline */}
                      <div>
                        <h3>Timeline</h3>
                        <p className="sub" style={{ fontSize: 13, marginBottom: 12 }}>
                          One persona’s timeline — what it was shown, what it said, how its beliefs moved tick by tick, and which memories it wrote. None of another persona’s appear in it.
                        </p>
                        {personaEventsLoading && <div className="empty">Loading persona events…</div>}
                        {!personaEventsLoading && personaEvents.length === 0 && (
                          <div className="empty">No recorded events for {activePersona} in world {w}.</div>
                        )}
                        {!personaEventsLoading && personaEvents.length > 0 && (
                          <div style={{ display: "grid", gap: 10 }}>
                            {personaEvents.map((ev) => {
                              const isTurn = ev.payload.kind === "turn";
                              const isReconstructed = reconstructedTurnId === ev.event_id && reconstructedPrompt;
                              const isError = reconstructedTurnId === ev.event_id && promptError;
                              const isLoadingPrompt = reconstructedTurnId === ev.event_id && promptLoading;

                              return (
                                <div
                                  key={ev.event_id}
                                  style={{
                                    border: "1px solid var(--line)",
                                    borderRadius: "var(--r-md)",
                                    padding: 12,
                                    background: isTurn ? "var(--surface-2)" : undefined,
                                  }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                    <b className="mono">{ev.event_id}</b>
                                    <span className="mono sub">tick {ev.tick} · seq {ev.seq}</span>
                                    <Chip className="plain">{KIND_LABEL[ev.payload.kind] ?? ev.payload.kind}</Chip>
                                    {isTurn && (
                                      <button
                                        type="button"
                                        className="btn btn-secondary"
                                        style={{ marginLeft: "auto", fontSize: 12, padding: "4px 8px" }}
                                        onClick={() => handleReconstructPrompt(ev.event_id)}
                                        disabled={isLoadingPrompt}
                                      >
                                        {isLoadingPrompt ? "Reconstructing…" : "Reconstruct prompt"}
                                      </button>
                                    )}
                                  </div>

                                  <div style={{ marginTop: 8 }}>{summarize(ev)}</div>

                                  {/* Turn details: belief change delta if any */}
                                  {isTurn && Boolean(ev.payload.belief_change) && (
                                    <div className="mono sub" style={{ fontSize: 11, marginTop: 6 }}>
                                      Belief delta: {JSON.stringify(ev.payload.belief_change)}
                                    </div>
                                  )}

                                  {/* Prompt reconstruction display */}
                                  {isTurn && isReconstructed && (
                                    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                        <Chip className="active">Hash verified</Chip>
                                        <span className="sub" style={{ fontSize: 12 }}>
                                          Shape: <span className="mono">{reconstructedPrompt.shape}</span> · Reconstructed from records and checked against turn prompt hash. Never persisted.
                                        </span>
                                      </div>
                                      <div style={{ display: "grid", gap: 8 }}>
                                        {reconstructedPrompt.messages.map((m, mIdx) => (
                                          <div
                                            key={mIdx}
                                            style={{
                                              background: "var(--surface)",
                                              border: "1px solid var(--line)",
                                              borderRadius: "var(--r-sm)",
                                              padding: 10,
                                            }}
                                          >
                                            <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: "var(--primary)" }}>
                                              {m.role.toUpperCase()}
                                            </div>
                                            <pre
                                              style={{
                                                fontSize: 12,
                                                whiteSpace: "pre-wrap",
                                                marginTop: 4,
                                                fontFamily: "var(--font-mono)",
                                                maxHeight: 280,
                                                overflow: "auto",
                                              }}
                                            >
                                              {m.content}
                                            </pre>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Prompt reconstruction error */}
                                  {isTurn && isError && (
                                    <div style={{ marginTop: 10 }}>
                                      <Callout icon="alert">
                                        <div>
                                          <b>Cannot reconstruct prompt:</b> {promptError}
                                          <div className="sub" style={{ fontSize: 11, marginTop: 4 }}>
                                            The record cannot be verified against the turn’s recorded hash, so no approximation is shown.
                                          </div>
                                        </div>
                                      </Callout>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {q === "events" && (
            <div className="panel"><div className="panel-head"><h2>Events</h2><span className="hint">ordered by (persona, tick, seq) — closed ticks only</span>
              <div className="tools"><select className="input" value={kind} onChange={(e) => setKind(e.target.value)} style={{ maxWidth: 200 }}>
                {Object.keys(t.event_counts[w] ?? {}).map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k} ({t.event_counts[w][k]})</option>)}
              </select></div></div>
              <div className="panel-body" style={{ display: "grid", gap: 6 }}>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {Object.entries(t.event_counts[w] ?? {}).map(([k, c]) => (
                    <span key={k} className="tag">{KIND_LABEL[k] ?? k}: {c}</span>
                  ))}
                </div>
                <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>
                  {t.event_counts[w]?.[kind] ?? 0} <span className="mono">{kind}</span> events in this world.
                  Cost and memory dominate bulk volume; turns ({t.event_counts[w]?.turn ?? 0}) are the unit of simulation and of spend.
                </p>
                {resolveId && resolved && (
                  <div style={{ border: "1px solid var(--primary)", borderRadius: "var(--r-md)", padding: 12 }}>
                    <b className="mono">{resolved.event_id}</b> <span className="mono sub">tick {resolved.tick} · seq {resolved.seq}{resolved.persona_id ? ` · ${resolved.persona_id}` : ""}</span>
                    <p style={{ marginTop: 6 }}>{summarize(resolved)}</p>
                  </div>
                )}
              </div></div>
          )}

          {q === "beliefs" && (
            <div className="panel"><div className="panel-head"><h2>Belief history</h2><span className="hint">snapshots + turns, per persona</span>
              <div className="tools"><select className="input" value={persona ?? histPersonas[0] ?? ""} onChange={(e) => setPersona(e.target.value)} style={{ maxWidth: 260 }}>
                {histPersonas.map((p) => <option key={p} value={p}>{p}</option>)}
              </select></div></div>
              <div className="panel-body">
                {hist && hist.length > 0 ? (
                  <>
                    <div className="chart-wrap"><BeliefChart history={hist} /></div>
                    <table className="tbl" style={{ marginTop: 8 }}><thead><tr><th className="num">Tick</th><th className="num">value</th><th className="num">fit</th><th className="num">trust</th></tr></thead>
                      <tbody>{hist.slice(-12).map((p, i) => (
                        <tr key={i}><td className="num mono">{p.tick}</td><td className="num">{(p.beliefs.value ?? 0).toFixed(2)}</td><td className="num">{(p.beliefs.fit ?? 0).toFixed(2)}</td><td className="num">{(p.beliefs.trust ?? 0).toFixed(2)}</td></tr>
                      ))}</tbody></table>
                  </>
                ) : <div className="empty"><b>No snapshots.</b>Pick a persona with belief history.</div>}
              </div></div>
          )}

          {q === "edges" && (
            <div className="panel"><div className="panel-head"><h2>Influence edges</h2><span className="hint">persona pair × channel — count + last tick</span></div>
              <div className="panel-body tight"><table className="tbl">
                <thead><tr><th>From → to</th><th>Channel</th><th className="num">Messages</th><th className="num">Last tick</th></tr></thead>
                <tbody>
                  {t.edges_top.length === 0 && <tr><td colSpan={4} className="sub" style={{ textAlign: "center" }}>no word-of-mouth edges — survey-room-only worlds leave no edges</td></tr>}
                  {t.edges_top.slice(0, 30).map((e, i) => (
                    <tr key={i}><td className="mono">{e.u} → {e.v}</td><td className="mono">{e.channel}</td><td className="num">{e.count}</td><td className="num">{e.last_tick}</td></tr>
                  ))}
                </tbody>
              </table></div></div>
          )}

          {q === "verbatims" && (
            <div className="grid g2">
              {(["persona", "tick"] as const).map((g) => (
                <div key={g} className="panel"><div className="panel-head"><h2>Verbatims by {g}</h2></div>
                  <div className="panel-body" style={{ display: "grid", gap: 10 }}>
                    {(t.verbatim_groups[g] ?? []).slice(0, 8).map((grp) => (
                      <div key={grp.key} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                        <b className="mono">{grp.key}</b> <span className="sub">· {grp.count} records</span>
                        {grp.samples.map((smp) => (
                          <div key={smp.event_id} className="quote" style={{ borderLeft: "2px solid var(--line-2)", paddingLeft: 10, marginTop: 6, fontStyle: "italic", fontSize: 12.5 }}>
                            “{smp.text}” <span className="mono sub" style={{ fontStyle: "normal" }}>— {smp.persona_id} · t{smp.tick} · {smp.action}</span>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div></div>
              ))}
            </div>
          )}

          {q === "resolve" && (
            <div className="panel"><div className="panel-head"><h2>Resolve trace ids</h2><span className="hint">exact — missing ids raise, so findings can cite them</span>
              <div className="tools"><input className="input mono" placeholder="ev-…" value={resolveId ?? ""} onChange={(e) => setResolveId(e.target.value)} style={{ maxWidth: 300 }} /></div></div>
              <div className="panel-body">
                {resolved ? (
                  <><b className="mono">{resolved.event_id}</b> <Chip className="plain">{KIND_LABEL[resolved.payload.kind] ?? resolved.payload.kind}</Chip>
                    <p style={{ marginTop: 8 }}>{summarize(resolved)}</p>
                    <pre className="mono" style={{ fontSize: 11, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12, overflow: "auto", maxHeight: 320 }}>{JSON.stringify(resolved.payload, null, 1)}</pre></>
                ) : <div className="empty"><b>Unknown id.</b>Paste an evidence_trace_id from the report — e.g. from <Link href={`/report?run=${runId}`}>findings →</Link></div>}
              </div></div>
          )}
        </>
      )}
    </Shell>
  );
}
