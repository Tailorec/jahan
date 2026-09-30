"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { useSessionState } from "@/lib/session";
import { PageHead, Chip, Callout, PmfBar, PmfLegend } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import { pmfMean, type StudyReport, type WaveDigest } from "@/lib/engine";

interface Detail {
  summary: { run_id: string } | null;
  report: StudyReport | null;
}

const KIND_LABEL: Record<string, string> = {
  ranking: "ranking", risk: "risk", objection: "objection",
  belief_shift: "belief shift", wom_path: "word of mouth", intent_trajectory: "intent over waves", recommendation: "recommendation",
};

const SERIES = ["var(--seg1)", "var(--seg2)", "var(--seg3)", "var(--seg4)", "var(--seg5)"];

/* Purchase intent (top-two box) at every survey wave: one line per audience, and the share-weighted
   whole dashed. Every number is the engine's; the page only places it. */
function IntentOverWaves({ waves }: { waves: WaveDigest[] }) {
  const W = 520, H = 180, L = 36, R = 12, T = 10, B = 26;
  const ticks = waves.map((w) => w.tick);
  const lo = Math.min(...ticks), hi = Math.max(...ticks);
  const x = (t: number) => L + (hi === lo ? (W - L - R) / 2 : ((t - lo) / (hi - lo)) * (W - L - R));
  const y = (v: number) => T + (1 - v) * (H - T - B);
  const audiences = [...new Set(waves.flatMap((w) => Object.keys(w.audience_adoption ?? {})))].sort();
  const path = (points: [number, number][]) => points.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const whole = waves.filter((w) => w.adoption != null).map((w) => [w.tick, w.adoption!] as [number, number]);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W }} role="img" aria-label="Purchase intent over survey waves, by audience">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize="10" fill="var(--ink-3)">{Math.round(v * 100)}%</text></g>
        ))}
        {ticks.map((t) => <text key={t} x={x(t)} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--ink-3)">tick {t}</text>)}
        {audiences.map((a, i) => {
          const points = waves.filter((w) => w.audience_adoption?.[a] != null).map((w) => [w.tick, w.audience_adoption[a]] as [number, number]);
          return <g key={a}><path d={path(points)} fill="none" stroke={SERIES[i % SERIES.length]} strokeWidth="2" />
            {points.map(([t, v]) => <circle key={t} cx={x(t)} cy={y(v)} r="3" fill={SERIES[i % SERIES.length]} />)}</g>;
        })}
        {whole.length > 0 && <path d={path(whole)} fill="none" stroke="var(--ink-2)" strokeWidth="1.5" strokeDasharray="4 3" />}
      </svg>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12 }}>
        {audiences.map((a, i) => <span key={a}><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: SERIES[i % SERIES.length], marginRight: 4 }} />{a}</span>)}
        <span style={{ color: "var(--ink-2)" }}>- - - all audiences, share-weighted</span>
      </div>
      <table className="tbl" style={{ marginTop: 8 }}>
        <thead><tr><th className="num">Tick</th><th className="num">Answered</th><th className="num">Adoption</th><th className="num">Reached by a channel</th><th className="num">Not reached</th></tr></thead>
        <tbody>{waves.map((w) => (
          <tr key={w.tick}><td className="num">{w.tick}</td><td className="num">{w.respondents}</td>
            <td className="num">{w.adoption != null ? `${(w.adoption * 100).toFixed(1)}%` : "—"}</td>
            <td className="num">{w.reached}{w.reached_adoption != null ? ` · ${(w.reached_adoption * 100).toFixed(1)}%` : ""}</td>
            <td className="num">{w.unreached}{w.unreached_adoption != null ? ` · ${(w.unreached_adoption * 100).toFixed(1)}%` : ""}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function ReportPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const [tab, setTab] = useSessionState("report:tab", "findings");
  const [query, setQuery] = useSessionState("report:query", "");
  const r = data?.report ?? null;
  const findings = (r?.findings ?? []).filter((f) =>
    !query || f.statement.toLowerCase().includes(query.toLowerCase()) || f.finding_id.includes(query),
  );

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Report</b>{runId && <> / <span className="mono">{runId}</span></>}</>}>
      <PageHead
        title="Study report"
        sub={r ? <>Config <span className="mono">{r.config_hash.slice(0, 12)}…</span> · contract <span className="mono">{r.contract_version}</span> · engine commit <span className="mono">{r.engine_commit.slice(0, 12)}</span></> : "Findings carry their trace evidence and the test that would falsify them."}
        actions={r && (
          <>{r.trust.level === "uncalibrated"
            ? <Chip className="tier-explo">uncalibrated</Chip>
            : <Chip className="tier-cust">{r.trust.level.replace("_", " ")}</Chip>}
            {r.method.pins.length > 0 && r.method.pins.every((p) => p.model_id.startsWith("fake/")) &&
              <Chip className="tier-explo" title="No key, no corpus, no network">fake study</Chip>}</>
        )}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading report…</b></div>}
      {data && !r && <Callout icon="alert"><div>This run has no report.json yet — run the study to completion first.</div></Callout>}
      {r && (
        <>
          {r.trust.caveats.length > 0 && (
            <Callout icon="alert" style={{ marginBottom: 16 }}><div><b>Trust: {r.trust.level.replace("_", " ")}.</b> {r.trust.caveats.join(" ")}</div></Callout>
          )}
          {((r.forced_from ?? []).length > 0 || (r.forced_inputs ?? []).length > 0) && (
            <Callout icon="alert" style={{ marginBottom: 16 }}><div><b>Resumed past moved inputs.</b> This run was forced across {(r.forced_from ?? []).join(", ") || "a changed configuration"} — inputs {(r.forced_inputs ?? []).join(", ")} no longer match what the run started with. Treat ordering claims with extra suspicion.</div></Callout>
          )}
          <div className="tabs" role="tablist">
            {[["findings", `Findings (${r.findings.length})`], ["objections", `Objections (${r.objection_clusters.length})`], ["digests", `Digests (${r.digests.length})`], ["ledger", "Assumption ledger"], ["method", "Method"]].map(([id, label]) => (
              <button key={id} className={`tab${tab === id ? " active" : ""}`} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>
            ))}
            <input className="input" placeholder="filter findings…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginLeft: "auto", maxWidth: 220 }} />
          </div>

          {tab === "findings" && (
            <div style={{ display: "grid", gap: 12 }}>
              {findings.map((f) => (
                <div key={f.finding_id} className="ob-cluster">
                  <div className="ob-head"><b className="mono">{f.finding_id}</b>
                    <span className={`chip ${f.kind === "risk" ? "risk" : f.kind === "ranking" ? "tier-pros" : "tier-cat"}`}><span className="dot" />{KIND_LABEL[f.kind] ?? f.kind}</span>
                    <span className="chip plain">confidence: {f.confidence}</span>
                  </div>
                  <p style={{ marginTop: 6 }}>{f.statement}</p>
                  <p className="sub" style={{ color: "var(--ink-2)", marginTop: 6 }}><b>Disconfirming test:</b> {f.disconfirming_test}</p>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    <span className="sub" style={{ color: "var(--ink-3)" }}>{f.evidence_trace_ids.length} trace records</span>
                    {f.evidence_trace_ids.slice(0, 6).map((id) => (
                      <Link key={id} className="tag" href={`/trace?run=${runId}&resolve=${id}`}>{id.slice(0, 13)}…</Link>
                    ))}
                    {f.evidence_trace_ids.length > 6 && <Link href={`/trace?run=${runId}`} style={{ fontSize: 12 }}>+{f.evidence_trace_ids.length - 6} more in trace view →</Link>}
                  </div>
                </div>
              ))}
              {findings.length === 0 && <div className="empty"><b>No findings match.</b></div>}
            </div>
          )}

          {tab === "objections" && (
            <div style={{ display: "grid", gap: 12 }}>
              {r.objection_clusters.slice(0, 30).map((c, i) => (
                <div key={i} className="ob-cluster">
                  <div className="ob-head"><b>“{c.label}”</b>
                    <span className="mono sub" style={{ color: "var(--ink-3)" }}>{c.size} verbatims · cosine {c.threshold}{c.world_id ? ` · world ${c.world_id}` : ""}</span></div>
                  <p className="sub" style={{ color: "var(--ink-3)", marginTop: 4 }}>embed model <span className="mono">{c.embed_model_id}</span> · label is the medoid — something a persona actually wrote.</p>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    {c.verbatim_trace_ids.slice(0, 4).map((id) => (
                      <Link key={id} className="tag" href={`/trace?run=${runId}&resolve=${id}`}>{id.slice(0, 13)}…</Link>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "digests" && (
            <div style={{ display: "grid", gap: 16 }}>
              {r.digests.map((d) => (
                <div key={d.world_id} className="panel">
                  <div className="panel-head"><h2>World <span className="mono">{d.world_id}</span></h2><span className="hint">seed {d.seed} · {d.turn_count} turns · {d.tick_unit}s</span>
                    <div className="tools">{d.adoption != null ? <span className="chip tier-pros"><span className="dot" />adoption {(d.adoption * 100).toFixed(1)}%</span> : <span className="chip tier-explo"><span className="dot" />unmeasured</span>}</div></div>
                  <div className="panel-body" style={{ display: "grid", gap: 10 }}>
                    {d.unmeasured_reason && <p className="sub" style={{ color: "var(--ink-3)" }}>{d.unmeasured_reason}</p>}
                    {(d.waves ?? []).length > 0 && <><h3 style={{ fontSize: 13, margin: 0 }}>Purchase intent over survey waves</h3><IntentOverWaves waves={d.waves!} /></>}
                    {Object.keys(d.exposures_by_channel ?? {}).length > 0 && (
                      <p className="sub">Channels: {Object.entries(d.exposures_by_channel!).map(([c, k]) => `${c} showed ${k} exposures, reaching ${d.reached_by_channel?.[c] ?? 0} personas`).join(" · ")}</p>
                    )}
                    {(d.waves ?? []).length > 0 && <h3 style={{ fontSize: 13, margin: 0 }}>Where intent ended — the last wave, by audience</h3>}
                    {Object.entries(d.audience_pmfs ?? {}).map(([a, pmf]) => (
                      <div key={a} style={{ display: "flex", gap: 12, alignItems: "center" }}>
                        <b className="mono" style={{ minWidth: 140 }}>{a}</b>
                        <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                        <span className="mono sub">mean {pmfMean(pmf).toFixed(2)}</span>
                      </div>
                    ))}
                    <PmfLegend />
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "ledger" && (
            <div className="panel"><div className="panel-head"><h2>Assumption ledger</h2><span className="hint">gathered, not stored — in every report</span></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                {r.assumptions.map((a, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span className={`chip ${a.source === "assumed" ? "assump" : "plain"}`}><span className="dot" />{a.source.replace("_", " ")}</span>
                    <span style={{ fontSize: 13 }}>{a.text}</span>
                  </div>
                ))}
              </div></div>
          )}

          {tab === "method" && (
            <div className="panel"><div className="panel-head"><h2>Method disclosure</h2><span className="hint">how the numbers were produced</span></div>
              <div className="panel-body tight"><table className="tbl"><tbody>
                {(r.method.scenarios ?? []).map((sc) => (
                  <tr key={sc.variant_id}><td>Channels and waves · {sc.variant_id}</td><td className="sub">{sc.channels.length ? sc.channels.join(", ") : "none — a concept test: every persona sees the concept alone"}; a survey wave every {sc.survey_every} ticks, at tick 0 and the last of {sc.horizon_ticks}{sc.launch_reach != null ? `; launch reach ${(sc.launch_reach * 100).toFixed(0)}%` : ""}</td></tr>
                ))}
                {(r.method.departures ?? []).map((d, i) => <tr key={i}><td>Departures from OASIS</td><td className="sub">{d}</td></tr>)}
                <tr><td>Pinned models</td><td className="mono sub">{r.method.pins.map((p) => `${p.role}: ${p.model_id}`).join(" · ")}</td></tr>
                <tr><td>Fallbacks</td><td className="mono sub">{r.method.fallbacks.length ? r.method.fallbacks.map((p) => `${p.role}: ${p.model_id}`).join(" · ") : "none"}</td></tr>
                <tr><td>Seeds</td><td className="num mono">{r.method.seeds.join(", ")}</td></tr>
                <tr><td>Prompt templates</td><td className="mono sub">{r.method.template_hashes.map((t) => `${t.name} ${t.hash.slice(0, 8)}`).join(" · ")}</td></tr>
                <tr><td>Anchor sets</td><td className="mono sub">{r.method.anchor_set_hashes.map((t) => `${t.name} ${t.hash.slice(0, 8)}`).join(" · ")}</td></tr>
                <tr><td>Validation</td><td className="sub">{r.validation}</td></tr>
              </tbody></table></div></div>
          )}
        </>
      )}
      <style>{`.ob-cluster { border: 1px solid var(--line); border-radius: var(--r-md); padding: 14px 16px; } .ob-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }`}</style>
    </Shell>
  );
}
