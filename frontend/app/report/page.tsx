"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { useSessionState } from "@/lib/session";
import { PageHead, Chip, Callout, PmfBar, PmfLegend, ICONS, Tip, Kpi, Section } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import { pmfMean, type Finding, type StudyReport } from "@/lib/engine";
import { IntentOverWaves } from "@/components/charts";

interface Detail {
  summary: { run_id: string } | null;
  report: StudyReport | null;
}

const KIND: Record<string, { label: string; icon: keyof typeof ICONS; tone: string }> = {
  ranking: { label: "ranking", icon: "layers", tone: "tier-pros" },
  risk: { label: "risk", icon: "alert", tone: "risk" },
  objection: { label: "objection", icon: "forum", tone: "tier-cat" },
  belief_shift: { label: "belief shift", icon: "sliders", tone: "tier-cat" },
  wom_path: { label: "word of mouth", icon: "wom", tone: "tier-cat" },
  intent_trajectory: { label: "intent over waves", icon: "survey", tone: "tier-pros" },
  recommendation: { label: "recommendation", icon: "bulb", tone: "tier-pros" },
};
const CHANNEL: Record<string, { name: string; icon: keyof typeof ICONS }> = {
  social_feed: { name: "X-like feed", icon: "feed" }, forum: { name: "Reddit-like forum", icon: "forum" }, wom: { name: "word of mouth", icon: "wom" },
};
const TABS: [string, string, keyof typeof ICONS][] = [
  ["findings", "Findings", "bulb"], ["objections", "Objections", "forum"], ["digests", "Worlds", "layers"],
  ["ledger", "Assumption ledger", "info"], ["method", "Method", "sliders"],
];
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export default function ReportPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const [tab, setTab] = useSessionState("report:tab", "findings");
  const [query, setQuery] = useSessionState("report:query", "");
  const [kind, setKind] = useSessionState("report:kind", "all");
  const r = data?.report ?? null;
  const findings = (r?.findings ?? []).filter((f) =>
    (kind === "all" || f.kind === kind)
    && (!query || f.statement.toLowerCase().includes(query.toLowerCase()) || f.finding_id.includes(query)),
  );
  // Findings by kind, in the order a reader most needs them: what moved intent before what was said.
  const ORDER = ["intent_trajectory", "ranking", "risk", "belief_shift", "wom_path", "objection", "recommendation"];
  const kinds = ORDER.map((k) => [k, (r?.findings ?? []).filter((f) => f.kind === k).length] as const).filter(([, n]) => n > 0);
  // The headline world: the first the report lists. A sweep's others are one tab away.
  const lead = r?.digests[0] ?? null;
  const waves = lead?.waves ?? [];
  const first = waves.find((w) => w.adoption != null);
  const last = [...waves].reverse().find((w) => w.adoption != null);
  const moved = first && last && first !== last ? (last.adoption! - first.adoption!) : null;
  const biggest = Math.max(1, ...(r?.objection_clusters ?? []).map((c) => c.size));
  const counts: Record<string, number> = r ? { findings: r.findings.length, objections: r.objection_clusters.length, digests: r.digests.length, ledger: r.assumptions.length, method: 0 } : {};

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Report</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Study report"
        sub={r ? <>What the study found, and how. <Tip>Config <span className="mono">{r.config_hash.slice(0, 12)}…</span> · contract <span className="mono">{r.contract_version}</span> · engine commit <span className="mono">{r.engine_commit.slice(0, 12)}</span>. Every finding carries its trace evidence and the real-world test that would disprove it.</Tip></> : "Findings carry their trace evidence and the test that would falsify them."}
        actions={r && (
          <>{r.trust.level === "uncalibrated"
            ? <Chip className="tier-explo" title="Results have not been checked against real human data">uncalibrated</Chip>
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

          <div className="kpis" style={{ marginBottom: 16 }}>
            <Kpi icon="target" label="Adoption" tip="Share-weighted top-two-box purchase intent at the last survey wave: the share of personas who would probably or definitely buy."
              value={lead?.adoption != null ? pct(lead.adoption) : "—"} note={lead?.adoption == null ? "unmeasured" : undefined} />
            <Kpi icon="survey" label="Since launch" tip="How adoption moved from the first survey wave to the last."
              value={moved == null ? "—" : `${moved >= 0 ? "+" : "−"}${(Math.abs(moved) * 100).toFixed(1)} pts`} tone={moved == null ? undefined : moved > 0 ? "ok" : moved < 0 ? "no" : undefined} />
            <Kpi icon="bulb" label="Findings" tip="Statements the engine makes about what happened, each with its evidence and the test that would disprove it." value={String(r.findings.length)} />
            <Kpi icon="forum" label="Objections" tip="Groups of things personas said against the product, each labelled with something a persona actually wrote." value={String(r.objection_clusters.length)} />
            <Kpi icon="shield" label="Trust" tip="How far these results have been checked against real people. Uncalibrated means not at all yet." value={r.trust.level.replace(/_/g, " ")} tone={r.trust.level === "uncalibrated" ? "warn" : "ok"} />
          </div>

          {lead && waves.length > 0 && (
            <Section icon="survey" title="Purchase intent over survey waves" tip="Top-two-box intent at every survey wave, one line per audience and the share-weighted whole dashed — the study's headline. The table below it splits each wave into personas a channel had reached and those it had not.">
              <IntentOverWaves waves={waves} />
              {r.digests.length > 1 && <p className="sub" style={{ fontSize: 12, marginTop: 6 }}>{ICONS.info} World {lead.world_id} of {r.digests.length} — the others are under Worlds.</p>}
            </Section>
          )}

          <div className="tabs" role="tablist" style={{ marginTop: 16 }}>
            {TABS.map(([id, label, icon]) => (
              <button key={id} className={`tab tab-icon${tab === id ? " active" : ""}`} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                {ICONS[icon]}{label}{counts[id] ? <span className="count">{counts[id]}</span> : null}
              </button>
            ))}
            {tab === "findings" && <input className="input" placeholder="filter findings…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginLeft: "auto", maxWidth: 220 }} />}
          </div>

          {tab === "findings" && (
            <div style={{ display: "grid", gap: 10 }}>
              <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                <button className={`pick${kind === "all" ? " on" : ""}`} onClick={() => setKind("all")}>all <span className="n">{r.findings.length}</span></button>
                {kinds.map(([k, n]) => (
                  <button key={k} className={`pick${kind === k ? " on" : ""}`} onClick={() => setKind(k)}>{ICONS[KIND[k]?.icon ?? "info"]}{KIND[k]?.label ?? k} <span className="n">{n}</span></button>
                ))}
              </div>
              {[...findings].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind)).slice(0, 60).map((f) => <FindingCard key={f.finding_id} f={f} runId={runId} />)}
              {findings.length > 60 && <div className="sub" style={{ textAlign: "center", fontSize: 12 }}>Showing 60 of {findings.length} — pick a kind or filter to narrow.</div>}
              {findings.length === 0 && <div className="empty"><b>No findings match.</b></div>}
            </div>
          )}

          {tab === "objections" && (
            <div style={{ display: "grid", gap: 10 }}>
              {r.objection_clusters.slice(0, 30).map((c, i) => (
                <div key={i} className="rp-card">
                  <div className="row" style={{ alignItems: "flex-start" }}>
                    <span className="rp-quote">“</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <b style={{ fontSize: 14 }}>{c.label}</b>
                      <div className="rp-size"><span style={{ width: `${(c.size / biggest) * 100}%` }} /></div>
                      <div className="row sub" style={{ fontSize: 12, gap: 10, flexWrap: "wrap" }}>
                        <span>{ICONS.forum} {c.size} verbatims</span>
                        <span className="mono">cosine {c.threshold}</span>
                        {c.world_id && <span className="mono">world {c.world_id}</span>}
                        <Tip>Embed model <span className="mono">{c.embed_model_id}</span>. The label is the medoid — something a persona actually wrote, never a summary.</Tip>
                      </div>
                    </div>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    {c.verbatim_trace_ids.slice(0, 4).map((id) => (
                      <Link key={id} className="tag" href={`/trace?run=${runId}&resolve=${id}`}>{id.slice(0, 13)}…</Link>
                    ))}
                  </div>
                </div>
              ))}
              {r.objection_clusters.length === 0 && <div className="empty"><b>No objections were grouped.</b></div>}
            </div>
          )}

          {tab === "digests" && (
            <div style={{ display: "grid", gap: 4 }}>
              {r.digests.map((d) => (
                <Section key={d.world_id} icon="layers" title={`World ${d.world_id}`} tip={`Seed ${d.seed} · ${d.turn_count} turns · ${d.tick_unit}s. A world is one scenario run under one replicate seed.`}>
                  <div style={{ display: "grid", gap: 10 }}>
                    <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                      {d.adoption != null ? <span className="chip tier-pros"><span className="dot" />adoption {pct(d.adoption)}</span> : <span className="chip tier-explo"><span className="dot" />unmeasured</span>}
                      <span className="chip plain mono">seed {d.seed}</span>
                      {Object.entries(d.exposures_by_channel ?? {}).map(([c, k]) => (
                        <span key={c} className="chip plain" title={`${CHANNEL[c]?.name ?? c} showed ${k} exposures, reaching ${d.reached_by_channel?.[c] ?? 0} personas`}>
                          {ICONS[CHANNEL[c]?.icon ?? "radio"]} {CHANNEL[c]?.name ?? c} · {k} shown · {d.reached_by_channel?.[c] ?? 0} reached
                        </span>
                      ))}
                    </div>
                    {d.unmeasured_reason && <p className="sub" style={{ color: "var(--ink-3)" }}>{d.unmeasured_reason}</p>}
                    {(d.waves ?? []).length > 0 && d !== lead && <IntentOverWaves waves={d.waves!} />}
                    <div className="lbl">{ICONS.target} Where intent ended — the last wave, by audience</div>
                    {Object.entries(d.audience_pmfs ?? {}).map(([a, pmf]) => (
                      <div key={a} className="row" style={{ gap: 12 }}>
                        <b className="mono" style={{ minWidth: 140 }}>{a}</b>
                        <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                        <span className="mono sub">μ {pmfMean(pmf).toFixed(2)}</span>
                      </div>
                    ))}
                    <PmfLegend />
                  </div>
                </Section>
              ))}
            </div>
          )}

          {tab === "ledger" && (
            <Section icon="info" title="Assumption ledger" tip="What the study takes as true without evidence — gathered from the brief, not stored, and stated in every report.">
              <div style={{ display: "grid", gap: 8 }}>
                {r.assumptions.map((a, i) => (
                  <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                    <span className={`chip ${a.source === "assumed" ? "assump" : "plain"}`}><span className="dot" />{a.source.replace("_", " ")}</span>
                    <span style={{ fontSize: 13 }}>{a.text}</span>
                  </div>
                ))}
                {r.assumptions.length === 0 && <span className="sub">No assumptions were recorded.</span>}
              </div>
            </Section>
          )}

          {tab === "method" && (
            <Section icon="sliders" title="Method disclosure" tip="How the numbers were produced: channels and waves, the models every call was pinned to, the seeds, and the frozen templates and anchor scales.">
              <div className="method">
                {(r.method.scenarios ?? []).map((sc) => (
                  <MethodRow key={sc.variant_id} icon="radio" label={`Channels · ${sc.variant_id}`}>
                    {sc.channels.length ? sc.channels.map((c) => <span key={c} className="chip plain" style={{ marginRight: 4 }}>{ICONS[CHANNEL[c]?.icon ?? "radio"]} {CHANNEL[c]?.name ?? c}</span>) : "none — a concept test: every persona sees the concept alone"}
                    <div className="sub" style={{ marginTop: 4 }}>{ICONS.survey} a survey wave every {sc.survey_every} ticks, at tick 0 and the last of {sc.horizon_ticks}{sc.launch_reach != null ? `; launch reach ${(sc.launch_reach * 100).toFixed(0)}%` : ""}</div>
                  </MethodRow>
                ))}
                {(r.method.departures ?? []).map((d, i) => <MethodRow key={i} icon="info" label="Departures from OASIS"><span className="sub">{d}</span></MethodRow>)}
                <MethodRow icon="cpu" label="Pinned models">
                  {r.method.pins.map((p) => <div key={p.role} className="mono sub">{p.role}: {p.model_id}</div>)}
                </MethodRow>
                <MethodRow icon="shuffle" label="Fallbacks"><span className="mono sub">{r.method.fallbacks.length ? r.method.fallbacks.map((p) => `${p.role}: ${p.model_id}`).join(" · ") : "none"}</span></MethodRow>
                <MethodRow icon="shuffle" label="Seeds"><span className="mono">{r.method.seeds.join(", ")}</span></MethodRow>
                <MethodRow icon="code" label="Prompt templates"><span className="mono sub">{r.method.template_hashes.map((t) => `${t.name} ${t.hash.slice(0, 8)}`).join(" · ")}</span></MethodRow>
                <MethodRow icon="survey" label="Anchor sets"><span className="mono sub">{r.method.anchor_set_hashes.map((t) => `${t.name} ${t.hash.slice(0, 8)}`).join(" · ")}</span></MethodRow>
                <MethodRow icon="target" label="Validation"><span className="sub">{r.validation}</span></MethodRow>
              </div>
            </Section>
          )}
        </>
      )}
    </Shell>
  );
}

/* One finding: what kind, how sure, what it says, the test that would disprove it, and its evidence. */
function FindingCard({ f, runId }: { f: Finding; runId: string | null }) {
  const kind = KIND[f.kind] ?? { label: f.kind, icon: "info" as const, tone: "plain" };
  return (
    <div className={`rp-card${f.kind === "risk" ? " risk" : ""}`}>
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className={`chip ${kind.tone}`}>{ICONS[kind.icon]} {kind.label}</span>
        <span className={`conf conf-${f.confidence}`} title={`${f.confidence} confidence`}><i /><i /><i />{f.confidence}</span>
        <span className="mono sub" style={{ marginLeft: "auto", fontSize: 11 }}>{f.finding_id}</span>
      </div>
      <p className="rp-statement">{f.statement}</p>
      <div className="rp-test">{ICONS.target}<span><b>Disconfirming test:</b> {f.disconfirming_test}</span></div>
      <details className="fold" style={{ marginTop: 8 }}>
        <summary>{ICONS.code} {f.evidence_trace_ids.length} trace records</summary>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
          {f.evidence_trace_ids.slice(0, 12).map((id) => (
            <Link key={id} className="tag" href={`/trace?run=${runId}&resolve=${id}`}>{id.slice(0, 13)}…</Link>
          ))}
          {f.evidence_trace_ids.length > 12 && <Link href={`/trace?run=${runId}`} style={{ fontSize: 12 }}>+{f.evidence_trace_ids.length - 12} more in trace view →</Link>}
        </div>
      </details>
    </div>
  );
}

function MethodRow({ icon, label, children }: { icon: keyof typeof ICONS; label: string; children: React.ReactNode }) {
  return (
    <div className="method-row">
      <div className="lbl" style={{ margin: 0 }}>{ICONS[icon]}{label}</div>
      <div>{children}</div>
    </div>
  );
}
