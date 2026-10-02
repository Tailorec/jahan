"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { useSessionState } from "@/lib/session";
import { PageHead, Chip, Callout, ICONS, Tip, Kpi, Section } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import type { Finding, ObjectionCluster, OutcomeDigest, RunSummary, StudyReport } from "@/lib/engine";
import { worldName } from "@/lib/worlds";
import { BeliefMoves, CommunityIntent, IntentDiverging, IntentOverWaves } from "@/components/charts";

interface Detail {
  summary: RunSummary | null;
  report: StudyReport | null;
  digest: { digests: OutcomeDigest[] } | null;
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
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

const SECTIONS: [string, string, keyof typeof ICONS][] = [
  ["answer", "Answer", "target"], ["who", "Who would buy", "users"], ["moved", "How it moved", "survey"],
  ["why", "Why", "forum"], ["findings", "Findings", "bulb"], ["trust", "Trust", "shield"], ["method", "Method", "sliders"],
];
const GROUPS_SHOWN = 8;

export default function ReportPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const [kind, setKind] = useSessionState("report:kind", "all");
  const r = data?.report ?? null;
  const s = data?.summary ?? null;
  // The full digests the run wrote carry what the report's compact ones leave out — communities among them.
  const full = data?.digest?.digests ?? [];
  const digestOf = (worldId: string) => full.find((d) => d.world_id === worldId) ?? r?.digests.find((d) => d.world_id === worldId) ?? null;
  // Findings by kind, in the order a reader most needs them: what moved intent before what was said.
  const ORDER = ["intent_trajectory", "ranking", "risk", "belief_shift", "wom_path", "objection", "recommendation"];
  const kinds = ORDER.map((k) => [k, (r?.findings ?? []).filter((f) => f.kind === k).length] as const).filter(([, n]) => n > 0);
  const shown = (r?.findings ?? []).filter((f) => kind === "all" || f.kind === kind).sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const confident = shown.filter((f) => f.confidence !== "low");
  const unsure = shown.filter((f) => f.confidence === "low");
  // The headline world: the first the report lists. A sweep's others follow, each named by its version and seed.
  const lead = r?.digests[0] ? digestOf(r.digests[0].world_id) : null;
  const waves = lead?.waves ?? [];
  const first = waves.find((w) => w.adoption != null);
  const last = [...waves].reverse().find((w) => w.adoption != null);
  const moved = first && last && first !== last ? (last.adoption! - first.adoption!) : null;
  const objections = r?.objection_clusters ?? [];
  const reasons = r?.reason_clusters ?? [];
  const rankings = (r?.findings ?? []).filter((f) => f.kind === "ranking");
  const nameOf = (d: { world_id: string; scenario_hash?: string; seed?: number }) =>
    (s && worldName(s.scenarios, s.seeds, d)) ?? `world ${d.world_id}`;

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Report</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Study report"
        sub={r ? <>The answer, who would buy, why — and how far to rely on it. <Tip>Config <span className="mono">{r.config_hash.slice(0, 12)}…</span> · contract <span className="mono">{r.contract_version}</span> · engine commit <span className="mono">{r.engine_commit.slice(0, 12)}</span>. Every finding carries its trace evidence and the real-world test that would disprove it.</Tip></> : "Findings carry their trace evidence and the test that would falsify them."}
        actions={r && (
          <>{r.trust.level === "uncalibrated"
            ? <Chip className="tier-explo" title="Results have not been checked against real human data">uncalibrated</Chip>
            : <Chip className="tier-cust">{r.trust.level.replace("_", " ")}</Chip>}
            {r.method.pins.length > 0 && r.method.pins.every((p) => p.model_id.startsWith("fake/")) &&
              <Chip className="tier-explo" title="No key, no corpus, no network">fake study</Chip>}
            <a className="btn sm" href={`/api/runs/${runId}/report.md`} download={`report-${runId}.md`}>{ICONS.share} report.md</a></>
        )}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading report…</b></div>}
      {data && !r && <Callout icon="alert"><div>This run has no report.json yet — run the study to completion first.</div></Callout>}
      {r && (
        <>
          <nav className="rp-toc" aria-label="Report sections">
            {SECTIONS.map(([id, label, icon]) => <a key={id} href={`#${id}`}>{ICONS[icon]}{label}</a>)}
          </nav>

          {/* 1 · The answer */}
          <div id="answer" className="rp-anchor" />
          <div className="kpis" style={{ marginBottom: 12 }}>
            <Kpi icon="target" label="Would buy" tip="Share-weighted top-two-box purchase intent at the last survey wave: the share of personas who would probably or definitely buy."
              value={lead?.adoption != null ? pct(lead.adoption) : "—"} note={lead?.adoption == null ? `unmeasured: ${lead?.unmeasured_reason ?? ""}` : undefined} />
            <Kpi icon="survey" label="Since the first wave" tip="How the share who would buy moved from the first survey wave to the last."
              value={moved == null ? "—" : `${moved >= 0 ? "+" : "−"}${(Math.abs(moved) * 100).toFixed(1)} pts`} tone={moved == null ? undefined : moved > 0 ? "ok" : moved < 0 ? "no" : undefined} />
            <Kpi icon="forum" label="Objections" tip="Distinct things personas held against the product, each grouped from what their turns recorded as objecting." value={String(objections.length)} />
            <Kpi icon="bulb" label="Reasons to buy" tip="Distinct things personas said for the product, grouped the same way." value={String(reasons.length)} />
            <Kpi icon="shield" label="Trust" tip="How far these results have been checked against real people. Uncalibrated means not at all yet." value={r.trust.level.replace(/_/g, " ")} tone={r.trust.level === "uncalibrated" ? "warn" : "ok"} />
          </div>
          <div className="rp-answer">
            {r.digests.map((d) => {
              const dd = digestOf(d.world_id) ?? d;
              const w = (dd.waves ?? []).filter((x) => x.adoption != null);
              return (
                <div key={d.world_id} className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <b>{nameOf(dd)}</b>
                  {dd.adoption == null
                    ? <span className="sub">unmeasured: {dd.unmeasured_reason}</span>
                    : <span>{pct(dd.adoption)} would buy{w.length > 1 && <span className="sub"> · from {pct(w[0].adoption!)} at the first wave</span>}</span>}
                </div>
              );
            })}
            {rankings.map((f) => <p key={f.finding_id} className="rp-verdict">{ICONS.layers} {f.statement} <span className={`conf conf-${f.confidence}`}><i /><i /><i />{f.confidence}</span></p>)}
            {r.digests.length > 1 && <Link className="btn sm" href={`/atlas?run=${runId}`} style={{ justifySelf: "start" }}>{ICONS.layers} Compare the versions in the atlas</Link>}
          </div>

          {/* 2 · Who would buy */}
          <div id="who" className="rp-anchor" />
          {lead && (
            <Section icon="users" title="Who would buy" tip="Purchase intent at the last wave, by audience and by the network's communities, as bars centred on 'maybe'. The headline world is shown; a sweep's others are in the atlas.">
              <div style={{ display: "grid", gap: 18 }}>
                {Object.keys(lead.audience_pmfs ?? {}).length > 0
                  ? <IntentDiverging pmfs={lead.audience_pmfs} weights={lead.audience_shares ?? {}} caption={(_, share) => `${(share * 100).toFixed(0)}% of the market`} />
                  : <p className="sub">unmeasured: {lead.unmeasured_reason ?? "no wave answered"}</p>}
                {"community_pmfs" in lead && <div><div className="lbl">{ICONS.fork} Communities</div><CommunityIntent d={lead as OutcomeDigest} /></div>}
              </div>
            </Section>
          )}

          {/* 3 · How it moved */}
          <div id="moved" className="rp-anchor" />
          {lead && waves.length > 0 && (
            <Section icon="survey" title="How it moved" tip="The share who would buy at every survey wave, by audience or split into personas a channel had reached against those it had not.">
              <IntentOverWaves waves={waves} />
            </Section>
          )}

          {/* 4 · Why */}
          <div id="why" className="rp-anchor" />
          <Section icon="forum" title="Why" tip="What held people back and what persuaded them — each group labelled with something a persona actually wrote, sized by how many times it was said — and how their beliefs moved.">
            <div className="rp-why">
              <Groups title="What held people back" icon="alert" tone="no" clusters={objections} runId={runId} empty="No objections were found: no persona's turn objected." />
              <Groups title="What persuaded" icon="check" tone="ok" clusters={reasons} runId={runId} empty={r.reason_clusters ? "No reasons to buy were found." : "This report was written before reasons to buy were collected."} />
            </div>
            {lead && <div style={{ marginTop: 16 }}><div className="lbl">{ICONS.sliders} How beliefs moved</div><BeliefMoves mean={lead.belief_movement_mean} abs={lead.belief_movement_abs} /></div>}
          </Section>

          {/* 5 · Findings */}
          <div id="findings" className="rp-anchor" />
          <Section icon="bulb" title="Findings" tip="Statements the engine authored from the record, never generated: each with its confidence, its evidence and the real-world test that would disprove it. Low-confidence ones are folded below.">
            <div style={{ display: "grid", gap: 10 }}>
              <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                <button className={`pick${kind === "all" ? " on" : ""}`} onClick={() => setKind("all")}>all <span className="n">{r.findings.length}</span></button>
                {kinds.map(([k, n]) => (
                  <button key={k} className={`pick${kind === k ? " on" : ""}`} onClick={() => setKind(k)}>{ICONS[KIND[k]?.icon ?? "info"]}{KIND[k]?.label ?? k} <span className="n">{n}</span></button>
                ))}
              </div>
              {confident.map((f) => <FindingCard key={f.finding_id} f={f} runId={runId} />)}
              {confident.length === 0 && <div className="empty"><b>No high- or medium-confidence findings{kind !== "all" ? " of this kind" : ""}.</b></div>}
              {unsure.length > 0 && (
                <details className="fold">
                  <summary>{ICONS.info} {unsure.length} low-confidence finding{unsure.length === 1 ? "" : "s"}</summary>
                  <div style={{ display: "grid", gap: 10, marginTop: 10 }}>{unsure.map((f) => <FindingCard key={f.finding_id} f={f} runId={runId} />)}</div>
                </details>
              )}
            </div>
          </Section>

          {/* 6 · Trust */}
          <div id="trust" className="rp-anchor" />
          <Section icon="shield" title="Trust: how far to rely on it" tip="How far these results have been checked against real people, what the study assumed without evidence, and what the record says about its own quality.">
            <div style={{ display: "grid", gap: 14 }}>
              <div className={`verdict ${r.trust.level === "uncalibrated" ? "tie" : "lead"}`}>
                <span className="sec-icon">{ICONS.shield}</span>
                <div><b>{r.trust.level.replace(/_/g, " ")}.</b> {r.trust.caveats.join(" ")}</div>
              </div>
              {((r.forced_from ?? []).length > 0 || (r.forced_inputs ?? []).length > 0) && (
                <Callout icon="alert"><div><b>Resumed past moved inputs.</b> This run was forced across {(r.forced_from ?? []).join(", ") || "a changed configuration"} — inputs {(r.forced_inputs ?? []).join(", ")} no longer match what the run started with. Treat ordering claims with extra suspicion.</div></Callout>
              )}
              <div>
                <div className="lbl">{ICONS.info} Assumed without evidence</div>
                {r.assumptions.length === 0 ? <span className="sub">No assumptions were recorded.</span> : (
                  <div style={{ display: "grid", gap: 6 }}>{r.assumptions.map((a, i) => (
                    <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                      <span className={`chip ${a.source === "assumed" ? "assump" : "plain"}`}><span className="dot" />{a.source.replace("_", " ")}</span>
                      <span style={{ fontSize: 13 }}>{a.text}</span>
                    </div>
                  ))}</div>
                )}
              </div>
              <div>
                <div className="lbl">{ICONS.database} What the record says about itself</div>
                <div style={{ overflowX: "auto" }}>
                  <table className="tbl tight nowrap">
                    <thead><tr><th>World</th><th className="num">Turns</th><th className="num">Scored no intent</th><th>Fidelity</th></tr></thead>
                    <tbody>{r.digests.map((d) => (
                      <tr key={d.world_id}><td>{nameOf(digestOf(d.world_id) ?? d)}</td><td className="num">{d.turn_count}</td><td className="num">{d.turns_without_intent}</td>
                        <td className="sub">{d.rungs.length ? `degraded: ${d.rungs.join(", ")}` : "full"}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </div>
            </div>
          </Section>

          {/* 7 · Method */}
          <div id="method" className="rp-anchor" />
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
            {r.digests.length > 1 && (
              <details className="fold" style={{ marginTop: 12 }}>
                <summary>{ICONS.layers} Every world</summary>
                <div style={{ display: "grid", gap: 14, marginTop: 10 }}>
                  {r.digests.map((d) => {
                    const dd = digestOf(d.world_id) ?? d;
                    return (
                      <div key={d.world_id}>
                        <div className="row" style={{ gap: 8, marginBottom: 6 }}><b>{nameOf(dd)}</b>{dd.adoption != null && <span className="chip tier-pros">{pct(dd.adoption)}</span>}</div>
                        {(dd.waves ?? []).length > 0 && <IntentOverWaves waves={dd.waves!} />}
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </Section>
        </>
      )}
    </Shell>
  );
}

/* Groups of what personas said, one direction: the largest first, each labelled with a sentence a persona
   wrote and sized by how many said something like it; the long tail folded, never dropped. */
function Groups({ title, icon, tone, clusters, runId, empty }: {
  title: string; icon: keyof typeof ICONS; tone: "ok" | "no"; clusters: ObjectionCluster[]; runId: string | null; empty: string;
}) {
  const biggest = Math.max(1, ...clusters.map((c) => c.size));
  const card = (c: ObjectionCluster, i: number) => (
    <div key={i} className={`rp-group ${tone}`}>
      <b>“{c.label}”</b>
      <div className="rp-size"><span style={{ width: `${(c.size / biggest) * 100}%` }} /></div>
      <div className="row sub" style={{ fontSize: 12, gap: 10, flexWrap: "wrap" }}>
        <span title="Sentences grouped here; one persona may have said it more than once">{c.size} mention{c.size === 1 ? "" : "s"}</span>
        {c.verbatim_trace_ids.slice(0, 3).map((id) => <Link key={id} className="tag" href={`/trace?run=${runId}&resolve=${id}`}>{id.slice(0, 11)}…</Link>)}
      </div>
    </div>
  );
  return (
    <div className="rp-groups">
      <div className="lbl">{ICONS[icon]} {title} <span className="count-pill">{clusters.length}</span></div>
      {clusters.length === 0 ? <p className="sub">{empty}</p> : (
        <>
          {clusters.slice(0, GROUPS_SHOWN).map(card)}
          {clusters.length > GROUPS_SHOWN && (
            <details className="fold"><summary>{clusters.length - GROUPS_SHOWN} smaller groups</summary>
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>{clusters.slice(GROUPS_SHOWN).map((c, i) => card(c, i + GROUPS_SHOWN))}</div>
            </details>
          )}
        </>
      )}
    </div>
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
