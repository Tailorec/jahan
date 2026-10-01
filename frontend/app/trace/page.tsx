"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { useSessionState } from "@/lib/session";
import { PageHead, Chip, Callout, TrustLine, ICONS, Section, Tip, Kpi } from "@/components/ui";
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

const KIND_ICON: Record<string, keyof typeof ICONS> = {
  stimulus_published: "feed", exposure_dropped: "x", turn: "forum", guardrail_violation: "shield",
  reflection: "bulb", memory: "database", belief_snapshot: "sliders", probe: "target", cost: "dollar",
  intervention: "sparkles", degraded: "alert", tick_closed: "clock", lifecycle: "play",
};
const CHANNEL_ICON: Record<string, keyof typeof ICONS> = { social_feed: "feed", forum: "forum", wom: "wom" };
const CHANNEL_NAME: Record<string, string> = { social_feed: "X-like feed", forum: "Reddit-like forum", wom: "word of mouth" };
const DIM_TIP: Record<string, string> = {
  value: "Whether the product seems worth its price, from 0 to 1.",
  fit: "Whether the product suits this persona's life, from 0 to 1.",
  trust: "Whether this persona believes the brand's claims, from 0 to 1.",
};

/* A channel as its icon and plain name. */
// A persona's whole record in one page; one past this says so rather than silently stopping.
const PERSONA_EVENT_LIMIT = 5000;

function ChannelTag({ c }: { c: string }) {
  return <span className="row" style={{ gap: 4 }}>{ICONS[CHANNEL_ICON[c] ?? "radio"]}{CHANNEL_NAME[c] ?? c}</span>;
}

const DIMS = ["value", "fit", "trust"] as const;
const SERIES_COLOR = ["var(--seg1)", "var(--seg2)", "var(--seg4)", "var(--seg3)", "var(--seg5)", "var(--ink-3)"];

/* One value per tick: the last one the record wrote that tick, carried forward over ticks it wrote none. */
function byTick(history: BeliefPoint[]) {
  const ticks = Array.from(new Set(history.map((p) => p.tick))).sort((a, b) => a - b);
  const last = new Map<number, Record<string, number>>();
  for (const p of history) last.set(p.tick, p.beliefs);
  return ticks.map((tick) => ({ tick, beliefs: last.get(tick)! }));
}

/* A marker per series, so lines lying on top of each other stay told apart. */
function Marker({ i, x, y, color }: { i: number; x: number; y: number; color: string }) {
  if (i % 3 === 1) return <rect x={x - 3.5} y={y - 3.5} width={7} height={7} fill="var(--bg)" stroke={color} strokeWidth={1.8} />;
  if (i % 3 === 2) return <path d={`M${x},${y - 4.5} L${x + 4.5},${y + 3.5} L${x - 4.5},${y + 3.5} Z`} fill="var(--bg)" stroke={color} strokeWidth={1.8} />;
  return <circle cx={x} cy={y} r={3.8} fill="var(--bg)" stroke={color} strokeWidth={1.8} />;
}

function BeliefChart({ history, claims = false }: { history: BeliefPoint[]; claims?: boolean }) {
  const points = byTick(history);
  const claimKeys = Array.from(new Set(history.flatMap((p) => Object.keys(p.beliefs)))).filter((k) => !(DIMS as readonly string[]).includes(k)).sort();
  const keys = [...DIMS, ...claimKeys];
  const [on, setOn] = React.useState<Set<string>>(() => new Set(claims ? keys : DIMS));
  const [hover, setHover] = React.useState<number | null>(null);
  const W = 640, H = 220, L = 34, R = 624, T = 12, B = 192;
  const lo = points[0]?.tick ?? 0, hi = Math.max(points[points.length - 1]?.tick ?? 1, lo + 1);
  const x = (t: number) => L + ((t - lo) / (hi - lo)) * (R - L);
  // ponytail: a 2px nudge per series keeps identical lines visible; small against a 180px range.
  const y = (v: number, k: number) => B - v * (B - T) + (k - 1) * 2;
  const color = (k: string) => SERIES_COLOR[keys.indexOf(k) % SERIES_COLOR.length];
  const shown = keys.filter((k) => on.has(k));
  const toggle = (k: string) => setOn((prev) => { const next = new Set(prev); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const first = points[0]?.beliefs ?? {}, final = points[points.length - 1]?.beliefs ?? {};
  const hp = hover != null ? points[hover] : null;
  const prev = hover != null && hover > 0 ? points[hover - 1] : null;
  return (
    <div className="belief-chart">
      <div className="belief-legend" role="group" aria-label="Lines shown">
        {keys.map((k, ki) => (
          <button key={k} type="button" aria-pressed={on.has(k)} className={`belief-key${on.has(k) ? " on" : ""}`} onClick={() => toggle(k)}
            title={DIM_TIP[k] ?? `Credence in claim ${k}, from 0 to 1.`}>
            <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden>
              <line x1="1" x2="21" y1="6" y2="6" stroke={color(k)} strokeWidth="2" strokeDasharray={ki >= DIMS.length ? "4 3" : undefined} />
              <Marker i={ki} x={11} y={6} color={color(k)} />
            </svg>
            <span>{k}</span>
            <span className="mono sub">{(first[k] ?? 0).toFixed(2)}→{(final[k] ?? 0).toFixed(2)}</span>
          </button>
        ))}
      </div>
      <div className="belief-scroll"><div className="chart-wrap" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Belief history: ${shown.map((k) => `${k} ${(first[k] ?? 0).toFixed(2)} to ${(final[k] ?? 0).toFixed(2)}`).join(", ")}`}>
          <rect x={L} y={T} width={R - L} height={(B - T) / 2} fill="var(--surface-2)" opacity={0.5} />
          {[0, 0.25, 0.5, 0.75, 1].map((g) => (
            <g key={g}><line className="gridline" x1={L} x2={R} y1={B - g * (B - T)} y2={B - g * (B - T)} /><text x={L - 6} y={B - g * (B - T) + 3} textAnchor="end">{g}</text></g>
          ))}
          {points.map((p) => <text key={p.tick} x={x(p.tick)} y={H - 6} textAnchor="middle">t{p.tick}</text>)}
          {hp && <line x1={x(hp.tick)} x2={x(hp.tick)} y1={T} y2={B} stroke="var(--ink-3)" strokeDasharray="3 3" />}
          {shown.map((k) => {
            const ki = keys.indexOf(k);
            // Step after each tick: a belief holds until a turn moves it.
            const d = points.map((p, i) => {
              const px = x(p.tick).toFixed(1), py = y(p.beliefs[k] ?? 0.5, ki).toFixed(1);
              return i === 0 ? `M${px},${py}` : `H${px} V${py}`;
            }).join(" ");
            return (
              <g key={k}>
                <path d={d} fill="none" stroke={color(k)} strokeWidth={ki >= DIMS.length ? 1.5 : 2.2} strokeDasharray={ki >= DIMS.length ? "5 4" : undefined} />
                {points.map((p) => <Marker key={p.tick} i={ki} x={x(p.tick)} y={y(p.beliefs[k] ?? 0.5, ki)} color={color(k)} />)}
              </g>
            );
          })}
          {points.map((p, i) => {
            const half = points.length > 1 ? (R - L) / (points.length - 1) / 2 : (R - L) / 2;
            return <rect key={p.tick} x={x(p.tick) - half} y={T} width={half * 2} height={B - T} fill="transparent" onMouseEnter={() => setHover(i)} />;
          })}
        </svg>
        {hp && (
          <div className="belief-tip" style={{ left: `${Math.min(85, Math.max(15, (x(hp.tick) / W) * 100))}%` }}>
            <b className="mono">tick {hp.tick}</b>
            {shown.map((k) => {
              const v = hp.beliefs[k] ?? 0, dv = prev ? v - (prev.beliefs[k] ?? 0) : 0;
              return (
                <div key={k} className="row" style={{ gap: 6 }}>
                  <span className="dot" style={{ background: color(k) }} />{k}
                  <span className="mono" style={{ marginLeft: "auto" }}>{v.toFixed(2)}</span>
                  {Math.abs(dv) >= 0.005 && <span className="mono" style={{ color: dv > 0 ? "var(--ok)" : "var(--risk)" }}>{dv > 0 ? "▲" : "▼"}{Math.abs(dv).toFixed(2)}</span>}
                </div>
              );
            })}
          </div>
        )}
      </div></div>
    </div>
  );
}

/* Every tick's beliefs, with what moved since the tick before. */
function BeliefTable({ history }: { history: BeliefPoint[] }) {
  const points = byTick(history);
  const keys = [...DIMS, ...Array.from(new Set(history.flatMap((p) => Object.keys(p.beliefs)))).filter((k) => !(DIMS as readonly string[]).includes(k)).sort()];
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl nowrap" style={{ marginTop: 8 }}>
        <thead><tr><th className="num">Tick</th>{keys.map((k) => <th key={k} className="num">{k}</th>)}</tr></thead>
        <tbody>{points.map((p, i) => (
          <tr key={p.tick}><td className="num mono">t{p.tick}</td>{keys.map((k) => {
            const v = p.beliefs[k] ?? 0, dv = i > 0 ? v - (points[i - 1].beliefs[k] ?? 0) : 0;
            return (
              <td key={k} className="num">
                {v.toFixed(2)}{Math.abs(dv) >= 0.005 && <span className="mono" style={{ marginLeft: 6, fontSize: 11, color: dv > 0 ? "var(--ok)" : "var(--risk)" }}>{dv > 0 ? "▲" : "▼"}{Math.abs(dv).toFixed(2)}</span>}
              </td>
            );
          })}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function summarize(ev: TraceEvent): string {
  const p = ev.payload;
  switch (p.kind) {
    case "lifecycle": return `lifecycle → ${p.phase}`;
    case "tick_closed": return "tick recorded whole";
    case "turn": {
      // A turn records its reaction nested; older records kept action and text flat.
      const r = ((p.turn as { reaction?: Record<string, unknown> } | undefined)?.reaction ?? p) as Record<string, unknown>;
      const channel = (p.turn as { impression?: { channel?: string } } | undefined)?.impression?.channel;
      const said = r.verbatim ?? r.text;
      return `${r.action ? String(r.action) : "turn"}${channel ? ` · ${CHANNEL_NAME[channel] ?? channel.replace("_", " ")}` : ""}${said ? ` — “${String(said).slice(0, 160)}”` : ""}`;
    }
    case "belief_snapshot": {
      const b = (p.beliefs ?? {}) as Record<string, unknown>;
      const flat = { ...((b.dimensions ?? {}) as Record<string, number>), ...((b.claim_credence ?? {}) as Record<string, number>) };
      const vals = Object.keys(flat).length ? flat : (b as Record<string, number>);
      return `beliefs ${Object.entries(vals).map(([k, v]) => `${k} ${Number(v).toFixed(2)}`).join(" · ")}`;
    }
    case "memory": {
      const m = p.memory as { description?: string } | string | undefined;
      return `remembered: “${String((typeof m === "object" ? m?.description : m) ?? p.text ?? "").slice(0, 160)}”`;
    }
    case "exposure_dropped": return `not shown ${String(p.stimulus_id ?? "")}${p.channel ? ` on ${CHANNEL_NAME[String(p.channel)] ?? String(p.channel)}` : ""}${p.reason ? ` · ${String(p.reason).replace(/_/g, " ")}` : ""}`;
    case "reflection": return `reflection (${String(p.trigger ?? "")})`;
    case "cost": return `${String(p.role)} · ${Number(p.input_tokens ?? 0) + Number(p.output_tokens ?? 0)} tokens${p.cost != null ? ` · $${Number(p.cost).toFixed(4)}` : ""}`;
    case "stimulus_published": {
      const st = (p.stimulus ?? {}) as Record<string, unknown>;
      return `published ${String(st.kind ?? "stimulus")} ${String(p.stimulus_id ?? st.stimulus_id ?? "")}${st.text ? ` — “${String(st.text).slice(0, 120)}”` : ""}`;
    }
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
  const [tlKind, setTlKind] = React.useState<string>("story");
  const [personaTotal, setPersonaTotal] = React.useState<number>(0);
  const [vMode, setVMode] = useSessionState<"mine" | "persona" | "tick">("trace:verbatims", "mine");

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
    fetch(`/api/runs/${runId}/events?persona_id=${encodeURIComponent(activePersona)}${w ? `&world_id=${encodeURIComponent(w)}` : ""}&limit=${PERSONA_EVENT_LIMIT}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`status ${res.status}`))))
      .then((payload) => {
        if (!cancelled) {
          const rawEvents: TraceEvent[] = payload.events ?? [];
          // Phase 8 acceptance criterion:
          // A persona's events, beliefs and verbatims are shown in one timeline, and none of another persona's appear in it
          const filtered = rawEvents.filter((e) => e.persona_id === activePersona || !e.persona_id);
          setPersonaEvents(filtered);
          setPersonaTotal(Number(payload.total ?? rawEvents.length));
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

  // Influence neighbourhood drawn from recorded edges
  const personaEdges = (t?.edges_top ?? []).filter(
    (e) => activePersona && (e.u === activePersona || e.v === activePersona),
  );
  const heardFrom = personaEdges.filter((e) => e.v === activePersona);
  const heardBy = personaEdges.filter((e) => e.u === activePersona);

  // Belief movement before and after
  const initialBeliefs = hist && hist.length > 0 ? hist[0].beliefs : null;
  const finalBeliefs = hist && hist.length > 0 ? hist[hist.length - 1].beliefs : null;

  const counts = (w ? t?.event_counts[w] : undefined) ?? {};
  const totalEvents = Object.values(counts).reduce((a, b) => a + b, 0);
  const maxCount = Math.max(1, ...Object.values(counts));
  const tlKinds = Array.from(new Set(personaEvents.map((e) => e.payload.kind)));
  // "story" leaves out the per-call cost records, which outnumber everything else.
  const shown = tlKind === "all" ? personaEvents : tlKind === "story" ? personaEvents.filter((e) => e.payload.kind !== "cost") : personaEvents.filter((e) => e.payload.kind === tlKind);
  // Everything the picked persona said: every turn that carried words, survey answers included.
  const mine = personaEvents.flatMap((ev) => {
    if (ev.payload.kind !== "turn") return [];
    const turn = ev.payload.turn as { impression?: { channel?: string }; reaction?: { action?: string; verbatim?: string | null } } | undefined;
    const text = turn?.reaction?.verbatim ?? (ev.payload.text as string | undefined);
    if (!text) return [];
    return [{ ev, channel: turn?.impression?.channel ?? "", action: turn?.reaction?.action ?? String(ev.payload.action ?? ""), text }];
  });
  const mineByChannel = mine.reduce<Record<string, number>>((acc, m) => { acc[m.channel] = (acc[m.channel] ?? 0) + 1; return acc; }, {});
  const openPersona = (p: string) => { setPersona(p); setTlKind("story"); setQ("persona"); };

  const TABS: [typeof q, string, keyof typeof ICONS, number | null][] = [
    ["persona", "Persona", "users", histPersonas.length],
    ["events", "Events", "layers", totalEvents],
    ["beliefs", "Beliefs", "sliders", null],
    ["edges", "Edges", "network", t?.edges_top.length ?? 0],
    ["verbatims", "Verbatims", "forum", null],
    ["resolve", "Resolve", "target", null],
  ];

  const personaPicker = (
    <select className="input mono" aria-label="Persona" value={activePersona ?? ""} onChange={(e) => openPersona(e.target.value)} style={{ maxWidth: 260 }}>
      {histPersonas.map((p) => <option key={p} value={p}>{p}</option>)}
    </select>
  );

  const edgeTable = (rows: TraceEdge[], side: "u" | "v", head: string) => (
    <div style={{ overflowX: "auto" }}><table className="tbl tight nowrap" style={{ marginTop: 8 }}>
      <thead><tr><th>{head}</th><th>Channel</th><th className="num">Times</th><th className="num">Last tick</th></tr></thead>
      <tbody>
        {rows.map((e, idx) => (
          <tr key={idx}>
            <td><button type="button" className="linkish mono" onClick={() => openPersona(e[side])}>{e[side]}</button></td>
            <td><ChannelTag c={e.channel} /></td>
            <td className="num">{e.count}</td>
            <td className="num">{e.last_tick}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Trace view</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Trace view"
        sub={<>Ask the run&apos;s record a fixed set of questions. <Tip>Events, beliefs, edges, verbatims and resolve are the only questions the record answers. Nothing that reads it can reach past it, and prompts are rebuilt on demand, never stored.</Tip></>}
        actions={t && w && <>
          {worlds.length > 1
            ? <select className="input mono" aria-label="World" value={w} onChange={(e) => setWorld(e.target.value)} style={{ maxWidth: 180 }}>
                {worlds.map((x) => <option key={x} value={x}>world {x}</option>)}
              </select>
            : <span className="chip plain mono">{ICONS.layers} world {w}</span>}
          <span className="chip plain mono">{ICONS.clock} tick ≤ {t.max_tick[w]}</span>
        </>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading trace…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !t && <Callout icon="alert"><div>No trace-summary.json for this run yet — it is written beside report.json at the end of every run, or backfill with <span className="mono">scripts/export_ui_trace.py runs/{runId}</span>.</div></Callout>}
      {t && w && (
        <>
          <div className="kpis" style={{ marginBottom: 16 }}>
            <Kpi icon="layers" label="Events" tip="Every record this world wrote in closed ticks: turns, memories, belief snapshots, costs and the rest." value={totalEvents.toLocaleString()} />
            <Kpi icon="forum" label="Turns" tip="One persona acting once. The unit of simulation and of spend." value={(counts.turn ?? 0).toLocaleString()} />
            <Kpi icon="users" label="Personas traced" tip="Personas with a recorded belief history in this world." value={histPersonas.length.toLocaleString()} />
            <Kpi icon="network" label="Edges" tip="Persona pairs that passed a message, by channel. The busiest are kept here." value={t.edges_top.length.toLocaleString()} />
            <Kpi icon="clock" label="Last tick" tip="The last tick the record closed whole. Nothing after it is shown." value={String(t.max_tick[w] ?? "—")} />
          </div>

          <div className="tabs" role="tablist">
            {TABS.map(([id, label, icon, n]) => (
              <button key={id} className={`tab tab-icon${q === id ? " active" : ""}`} role="tab" aria-selected={q === id} onClick={() => setQ(id)}>
                {ICONS[icon]}{label}{n ? <span className="count">{n.toLocaleString()}</span> : null}
              </button>
            ))}
          </div>

          {/* One persona's whole history */}
          {q === "persona" && (
            <div style={{ display: "grid", gap: 16 }}>
              <Section icon="users" title="One persona’s whole history" tools={personaPicker}
                tip="Pick a persona: its belief movement, who it heard from and told, and every event it wrote, with each turn's prompt rebuilt on demand.">
                {!activePersona ? <div className="empty">No persona selected.</div> : (
                  <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <span className="chip plain mono">{ICONS.users} {activePersona}</span>
                    <span className="chip plain">{ICONS.layers} {personaEvents.length} events</span>
                    <span className="chip plain">{ICONS.forum} {personaEvents.filter((e) => e.payload.kind === "turn").length} turns</span>
                    <span className="chip plain">{ICONS.wom} heard from {heardFrom.length} · told {heardBy.length}</span>
                  </div>
                )}
              </Section>

              {activePersona && (
                <>
                  <Section icon="sliders" title="Belief movement" tip="Movement per dimension, before and after, from recorded snapshots and turns. Survey waves only read beliefs, so they never move them.">
                    {initialBeliefs && finalBeliefs ? (
                      <div className="kpis" style={{ marginBottom: 12 }}>
                        {["value", "fit", "trust"].map((dim) => {
                          const before = initialBeliefs[dim] ?? 0;
                          const after = finalBeliefs[dim] ?? 0;
                          const delta = after - before;
                          return (
                            <Kpi key={dim} icon={dim === "value" ? "dollar" : dim === "fit" ? "target" : "shield"} label={dim} tip={DIM_TIP[dim]}
                              tone={Math.abs(delta) < 0.005 ? undefined : delta > 0 ? "ok" : "warn"}
                              value={<>{before.toFixed(2)} → {after.toFixed(2)}</>}
                              note={delta >= 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2)} />
                          );
                        })}
                      </div>
                    ) : <p className="sub" style={{ fontSize: 12 }}>No belief snapshots for this persona.</p>}
                    {hist && hist.length > 0 && <BeliefChart key={activePersona} history={hist} />}
                  </Section>

                  <Section icon="network" title="Influence neighbourhood" tip="Recorded edges for this persona, naming the channel and how often. Click a persona to open its history.">
                    <div className="grid g2">
                      <div className="item">
                        <div className="row" style={{ gap: 6 }}>{ICONS.arrow}<b>Heard from</b><span className="count-pill">{heardFrom.length}</span></div>
                        {heardFrom.length === 0
                          ? <p className="sub" style={{ fontSize: 12 }}>Nobody — no message reached this persona.</p>
                          : edgeTable(heardFrom, "u", "From")}
                      </div>
                      <div className="item">
                        <div className="row" style={{ gap: 6 }}>{ICONS.share}<b>Heard by</b><span className="count-pill">{heardBy.length}</span></div>
                        {heardBy.length === 0
                          ? <p className="sub" style={{ fontSize: 12 }}>Nobody — this persona passed nothing on.</p>
                          : edgeTable(heardBy, "v", "To")}
                      </div>
                    </div>
                  </Section>

                  <Section icon="clock" title="Timeline" tip="What this persona was shown, what it said, how its beliefs moved tick by tick, and which memories it wrote. Only its own events appear."
                    tools={tlKinds.length > 1 && (
                      <select className="input" aria-label="Event kind" value={tlKind} onChange={(e) => setTlKind(e.target.value)} style={{ maxWidth: 180 }}>
                        <option value="story">all but cost ({personaEvents.filter((e) => e.payload.kind !== "cost").length})</option>
                        <option value="all">all kinds ({personaEvents.length})</option>
                        {tlKinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k} ({personaEvents.filter((e) => e.payload.kind === k).length})</option>)}
                      </select>
                    )}>
                    {personaEventsLoading && <div className="empty">Loading persona events…</div>}
                    {!personaEventsLoading && personaTotal > personaEvents.length && (
                      <Callout icon="alert"><div>Showing the first {personaEvents.length.toLocaleString()} of {personaTotal.toLocaleString()} events this persona wrote.</div></Callout>
                    )}
                    {!personaEventsLoading && personaEvents.length === 0 && (
                      <div className="empty">No recorded events for {activePersona} in world {w}.</div>
                    )}
                    {!personaEventsLoading && shown.length > 0 && (
                      <ol className="tr-timeline">
                        {shown.map((ev) => {
                          const isTurn = ev.payload.kind === "turn";
                          const isReconstructed = reconstructedTurnId === ev.event_id && reconstructedPrompt;
                          const isError = reconstructedTurnId === ev.event_id && promptError;
                          const isLoadingPrompt = reconstructedTurnId === ev.event_id && promptLoading;

                          return (
                            <li key={ev.event_id} className={`tr-item${isTurn ? " turn" : ""}`}>
                              <span className="tr-dot" title={KIND_LABEL[ev.payload.kind] ?? ev.payload.kind}>{ICONS[KIND_ICON[ev.payload.kind] ?? "info"]}</span>
                              <div style={{ minWidth: 0 }}>
                                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                                  <Chip className="plain">{KIND_LABEL[ev.payload.kind] ?? ev.payload.kind}</Chip>
                                  <span className="mono sub" style={{ fontSize: 11 }}>tick {ev.tick} · seq {ev.seq}</span>
                                  <span className="mono sub" style={{ fontSize: 11 }} title="trace id">{ev.event_id}</span>
                                  {isTurn && (
                                    <button type="button" className="btn btn-secondary" style={{ marginLeft: "auto", fontSize: 12, padding: "4px 8px" }}
                                      onClick={() => handleReconstructPrompt(ev.event_id)} disabled={Boolean(isLoadingPrompt)}>
                                      {ICONS.code}{isLoadingPrompt ? "Reconstructing…" : "Reconstruct prompt"}
                                    </button>
                                  )}
                                </div>
                                <div style={{ marginTop: 4, overflowWrap: "anywhere" }}>{summarize(ev)}</div>

                                {isTurn && Boolean(ev.payload.belief_change) && (
                                  <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>
                                    Belief delta: {JSON.stringify(ev.payload.belief_change)}
                                  </div>
                                )}

                                {isTurn && isReconstructed && (
                                  <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                                    <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                                      <Chip className="active">{ICONS.check} Hash verified</Chip>
                                      <span className="mono sub" style={{ fontSize: 11 }}>{reconstructedPrompt.shape}</span>
                                      <Tip>Reconstructed from records and checked against turn prompt hash. Never persisted: it leaves when you leave the page.</Tip>
                                    </div>
                                    <div style={{ display: "grid", gap: 8 }}>
                                      {reconstructedPrompt.messages.map((m, mIdx) => (
                                        <details key={mIdx} className="prompt-msg" open={m.role !== "system"}>
                                          <summary className="mono">{m.role.toUpperCase()} <span className="sub">· {m.content.length.toLocaleString()} chars</span></summary>
                                          <pre>{m.content}</pre>
                                        </details>
                                      ))}
                                    </div>
                                  </div>
                                )}

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
                            </li>
                          );
                        })}
                      </ol>
                    )}
                  </Section>
                </>
              )}
            </div>
          )}

          {q === "events" && (
            <Section icon="layers" title="Events" tip="How many records of each kind this world wrote, closed ticks only, ordered by (persona, tick, seq). Cost and memory dominate bulk volume; turns are the unit of simulation and of spend. Pick a kind to highlight it.">
              <div style={{ display: "grid", gap: 6 }}>
                {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, c]) => (
                  <button key={k} type="button" className={`bar-row${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
                    <span className="row" style={{ gap: 6, minWidth: 130 }}>{ICONS[KIND_ICON[k] ?? "info"]}{KIND_LABEL[k] ?? k}</span>
                    <span className="bar"><span style={{ width: `${(c / maxCount) * 100}%` }} /></span>
                    <span className="mono" style={{ minWidth: 60, textAlign: "right" }}>{c.toLocaleString()}</span>
                  </button>
                ))}
              </div>
              {resolveId && resolved && (
                <div className="item" style={{ marginTop: 12, borderColor: "var(--primary)" }}>
                  <div className="row" style={{ gap: 8, flexWrap: "wrap" }}><b className="mono">{resolved.event_id}</b> <span className="mono sub">tick {resolved.tick} · seq {resolved.seq}{resolved.persona_id ? ` · ${resolved.persona_id}` : ""}</span></div>
                  <p>{summarize(resolved)}</p>
                </div>
              )}
            </Section>
          )}

          {q === "beliefs" && (
            <Section icon="sliders" title="Belief history" tools={personaPicker} tip="Value, fit, trust and each claim's credence for one persona, tick by tick, from snapshots and turns. Click a key to hide or show its line; hover the chart for a tick's numbers. Arrows mark what moved since the tick before.">
              {hist && hist.length > 0 ? (
                <>
                  <BeliefChart key={activePersona} history={hist} claims />
                  <BeliefTable history={hist} />
                </>
              ) : <div className="empty"><b>No snapshots.</b>Pick a persona with belief history.</div>}
            </Section>
          )}

          {q === "edges" && (
            <Section icon="network" title="Influence edges" tip="Persona pair by channel: how many messages passed and the last tick one did. The thirty busiest are shown. Click a persona to open its history.">
              {t.edges_top.length === 0 ? (
                <div className="empty"><b>No edges.</b>Worlds with no channels leave no edges.</div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="tbl nowrap">
                    <thead><tr><th>From → to</th><th>Channel</th><th className="num">Messages</th><th className="num">Last tick</th></tr></thead>
                    <tbody>
                      {t.edges_top.slice(0, 30).map((e, i) => (
                        <tr key={i}>
                          <td className="mono">
                            <button type="button" className="linkish mono" onClick={() => openPersona(e.u)}>{e.u}</button> → <button type="button" className="linkish mono" onClick={() => openPersona(e.v)}>{e.v}</button>
                          </td>
                          <td><ChannelTag c={e.channel} /></td>
                          <td className="num">{e.count}</td>
                          <td className="num">{e.last_tick}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          )}

          {q === "verbatims" && (
            <Section icon="forum" title="Verbatims" tip="What personas said in their own words. 'This persona' is everything the picked persona said, survey answers included; the grouped views show the personas or ticks with the most to say, three lines each — click a persona to read all of it."
              tools={<>
                <div className="segctl" role="tablist" aria-label="Verbatims view">
                  {([["mine", "This persona", "users"], ["persona", "By persona", "layers"], ["tick", "By tick", "clock"]] as const).map(([id, label, icon]) => (
                    <button key={id} type="button" role="tab" aria-selected={vMode === id} className={vMode === id ? "on" : ""} onClick={() => setVMode(id)}>{ICONS[icon]}{label}</button>
                  ))}
                </div>
                {vMode === "mine" && personaPicker}
              </>}>
              {vMode === "mine" ? (
                personaEventsLoading ? <div className="empty">Loading what {activePersona} said…</div>
                : mine.length === 0 ? <div className="empty"><b>Nothing said.</b>{activePersona} wrote no words in world {w}.</div>
                : (
                  <div style={{ display: "grid", gap: 10 }}>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                      <span className="chip plain">{ICONS.forum} {mine.length} said</span>
                      {Object.entries(mineByChannel).map(([c, n]) => <span key={c} className="chip plain">{c === "survey_room" ? <>{ICONS.survey} survey</> : <ChannelTag c={c} />} · {n}</span>)}
                      {personaTotal > personaEvents.length && <span className="chip risk">{ICONS.alert} first {personaEvents.length.toLocaleString()} of {personaTotal.toLocaleString()} events</span>}
                    </div>
                    {mine.map(({ ev, channel, action, text }) => (
                      <div key={ev.event_id} className={`said${channel === "survey_room" ? " survey" : ""}`}>
                        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                          <span className="mono sub" style={{ fontSize: 11 }}>t{ev.tick}</span>
                          {channel === "survey_room"
                            ? <span className="chip plain">{ICONS.survey} survey answer</span>
                            : <span className="chip plain"><ChannelTag c={channel} /> · {action}</span>}
                          <button type="button" className="linkish mono" style={{ marginLeft: "auto", fontSize: 11 }} onClick={() => { setResolveId(ev.event_id); setQ("resolve"); }}>{ev.event_id}</button>
                        </div>
                        <blockquote className="verbatim">“{text}”</blockquote>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div style={{ display: "grid", gap: 10 }}>
                  {(t.verbatim_groups[vMode] ?? []).length === 0 && <p className="sub" style={{ fontSize: 12 }}>No verbatims recorded.</p>}
                  {(t.verbatim_groups[vMode] ?? []).length > 0 && (
                    <p className="sub" style={{ fontSize: 12 }}>
                      The {(t.verbatim_groups[vMode] ?? []).length} {vMode === "persona" ? "personas" : "ticks"} with the most said, their first three lines each.
                    </p>
                  )}
                  <div className="grid g2">
                    {(t.verbatim_groups[vMode] ?? []).map((grp) => (
                      <div key={grp.key} className="item">
                        <div className="row" style={{ gap: 6 }}>
                          {vMode === "persona"
                            ? <button type="button" className="linkish mono" onClick={() => { setPersona(grp.key); setVMode("mine"); }}>{grp.key}</button>
                            : <b className="mono">tick {grp.key}</b>}
                          <span className="count-pill">{grp.count}</span>
                        </div>
                        {grp.samples.map((smp) => (
                          <blockquote key={smp.event_id} className="verbatim">
                            “{smp.text}”
                            <span className="mono sub">{vMode === "tick" ? <button type="button" className="linkish mono" onClick={() => { setPersona(smp.persona_id); setVMode("mine"); }}>{smp.persona_id}</button> : `t${smp.tick}`} · {smp.action}</span>
                          </blockquote>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          )}

          {q === "resolve" && (
            <Section icon="target" title="Resolve trace ids" tip="Exact: an id the record does not hold is refused, so every finding can cite its evidence."
              tools={<input className="input mono" aria-label="Trace id" placeholder="ev-…" value={resolveId ?? ""} onChange={(e) => setResolveId(e.target.value)} style={{ maxWidth: 300 }} />}>
              {resolved ? (
                <div style={{ display: "grid", gap: 8 }}>
                  <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <b className="mono">{resolved.event_id}</b>
                    <Chip className="plain">{KIND_LABEL[resolved.payload.kind] ?? resolved.payload.kind}</Chip>
                    <span className="mono sub">tick {resolved.tick} · seq {resolved.seq}</span>
                    {resolved.persona_id && <button type="button" className="linkish mono" onClick={() => openPersona(resolved.persona_id!)}>{resolved.persona_id}</button>}
                  </div>
                  <p>{summarize(resolved)}</p>
                  <pre className="mono" style={{ fontSize: 11, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12, overflow: "auto", maxHeight: 320 }}>{JSON.stringify(resolved.payload, null, 1)}</pre>
                </div>
              ) : <div className="empty"><b>{resolveId ? "Unknown id." : "Paste a trace id."}</b>Use an evidence_trace_id from the report — e.g. from <Link href={`/report?run=${runId}`}>findings →</Link></div>}
            </Section>
          )}
        </>
      )}
    </Shell>
  );
}
