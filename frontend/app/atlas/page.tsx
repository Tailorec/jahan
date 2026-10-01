"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, PmfBar, PmfLegend, TrustLine, ICONS, Section, Tip } from "@/components/ui";
import { IntentOverWaves } from "@/components/charts";
import { useApi, useRunId } from "@/lib/api";
import {
  pmfMean,
  top2box,
  type Finding,
  type OutcomeDigest,
  type RunSummary,
  type ScenarioSummary,
  type StudyReport,
  type UITrace,
} from "@/lib/engine";

interface Detail {
  summary: RunSummary | null;
  digest: { digests: OutcomeDigest[]; summaries: Record<string, ScenarioSummary> } | null;
  report: StudyReport | null;
  trace: UITrace | null;
}

const CHANNEL_ICON: Record<string, keyof typeof ICONS> = { social_feed: "feed", forum: "forum", wom: "wom" };
const CHANNEL_NAME: Record<string, string> = { social_feed: "X-like feed", forum: "Reddit-like forum", wom: "word of mouth" };

/* Adoption as a tinted cell: the stronger the tint, the higher the share that would buy. */
const heat = (adoption: number) => `color-mix(in srgb, var(--teal) ${Math.round(adoption * 60)}%, var(--bg))`;

export default function AtlasPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const s = data?.summary ?? null;
  const digests = data?.digest?.digests ?? [];
  const summaries = data?.digest?.summaries ?? {};
  const report = data?.report ?? null;

  // Findings authored by extraction (never generated)
  const rankingFindings = (report?.findings ?? []).filter((f) => f.kind === "ranking");
  const riskFindings = (report?.findings ?? []).filter((f) => f.kind === "risk");
  const measured = digests.filter((d) => d.adoption != null);
  const best = measured.length ? Math.max(...measured.map((d) => d.adoption as number)) : null;
  const spreads = Object.values(summaries).map((x) => x.adoption_spread).filter((x): x is number => x != null);

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Sweep / <b>Scenario atlas</b></>}>
      <PageHead
        title="Scenario atlas"
        sub={<>Every world of this run side by side. <Tip>One run over many worlds sharing one budget: each scenario runs once per replicate seed. Each cell is a world — its digest measured adoption and polarization — and the spread across a scenario&apos;s worlds is the variance estimate that says whether an ordering survives.</Tip></>}
        actions={s && <>
          <span className="chip plain">{ICONS.layers} {s.scenarios.length} scenario{s.scenarios.length === 1 ? "" : "s"}</span>
          <span className="chip plain">{ICONS.shuffle} {s.seeds.length} seed{s.seeds.length === 1 ? "" : "s"}</span>
        </>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading sweep…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}

      {s && (
        <div style={{ display: "grid", gap: 4 }}>
          <div className="kpis" style={{ marginBottom: 12 }}>
            <Kpi icon="layers" label="Worlds" tip="A world is one scenario run under one replicate seed." value={String(digests.length)} />
            <Kpi icon="target" label="Best adoption" tip="The highest share-weighted top-two-box purchase intent any world reached at its last survey wave."
              value={best != null ? `${(best * 100).toFixed(1)}%` : "—"} />
            <Kpi icon="shuffle" label="Replicate spread" tip="How far adoption moved between the seeds of one scenario. An ordering between scenarios only survives if their gap is bigger than this."
              value={spreads.length ? `±${(Math.max(...spreads) * 100).toFixed(1)}%` : "—"} />
            <Kpi icon="fork" label="Polarization" tip="How far communities split into opposing views. Unmeasured when the network formed no communities to compare."
              value={digests.some((d) => d.polarization != null) ? "measured" : "unmeasured"} />
          </div>

          <Section icon="table" title="Adoption against polarization" tip="Measured top-two box and polarization per world, audience-weighted. Cells whose worlds ran at different degradation rungs are marked rather than silently compared. Unmeasured quantities render their reason where the number would have been.">
            <div style={{ overflowX: "auto" }}>
              <table className="tbl atlas">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    {s.seeds.map((seed) => <th key={seed} className="num">seed {seed}</th>)}
                    <th>Spread <Tip>Replicate spread: the range of adoption across this scenario&apos;s seeds — what says whether an ordering survives.</Tip></th>
                  </tr>
                </thead>
                <tbody>
                  {s.scenarios.map((sc, si) => {
                    const scSummary = (sc.scenario_hash ? summaries[sc.scenario_hash] : null) ?? summaries[sc.variant.variant_id] ?? null;
                    const rungMixed = scSummary?.rung_mixed ?? false;
                    return (
                      <tr key={si}>
                        <td>
                          <b>{sc.variant.name}</b> <span className="mono sub">{sc.variant.variant_id}</span>
                          <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                            <span className="chip plain" title="price">{ICONS.dollar} {sc.price.amount} {sc.price.currency}</span>
                            <span className="chip plain" title="horizon">{ICONS.clock} {sc.horizon_ticks} {sc.tick_unit}s</span>
                            {(sc.channels ?? []).length === 0
                              ? <span className="chip plain" title="no channels: every persona sees the concept alone">{ICONS.survey} concept test</span>
                              : (sc.channels ?? []).map((c) => <span key={c} className="chip plain" title={CHANNEL_NAME[c] ?? c}>{ICONS[CHANNEL_ICON[c] ?? "radio"]} {CHANNEL_NAME[c] ?? c}</span>)}
                            {sc.interventions.length > 0 && <span className="chip plain">{sc.interventions.map((i) => `${i.kind}@${i.tick}`).join(", ")}</span>}
                          </div>
                        </td>
                        {s.seeds.map((seed) => {
                          const d = digests.find((x) => x.seed === seed && (x.scenario_hash === sc.scenario_hash || digests.length <= s.seeds.length));
                          if (!d) return <td key={seed} className="num"><span className="sub">no world</span></td>;
                          // A cell whose worlds ran at different degradation rungs is marked rather than silently compared.
                          const cellDegraded = (d.rungs ?? []).length > 0;
                          return (
                            <td key={seed} className="num">
                              <div className="atlas-cell" style={{ background: d.adoption != null ? heat(d.adoption) : "var(--surface-2)" }}>
                                {d.adoption != null
                                  ? <span className="big">{(d.adoption * 100).toFixed(1)}%</span>
                                  : <span className="sub" style={{ fontStyle: "italic", fontSize: 11 }}>unmeasured: {d.unmeasured_reason ?? "unmeasured"}</span>}
                                <span className="mono sub" style={{ fontSize: 11 }}>
                                  {d.polarization != null ? <>pol {d.polarization.toFixed(2)}</> : <>pol — <Tip>{d.polarization_reason ?? "Polarization was not measured."}</Tip></>}
                                </span>
                                {cellDegraded && <span className="chip tier-explo" style={{ fontSize: 10 }}>degraded rung ({d.rungs.join(", ")})</span>}
                              </div>
                            </td>
                          );
                        })}
                        <td style={{ minWidth: 120 }}>
                          {scSummary ? (
                            <div style={{ display: "grid", gap: 4 }}>
                              <span className="mono">{scSummary.adoption_spread != null ? `±${(scSummary.adoption_spread * 100).toFixed(1)}%` : "n/a"}</span>
                              {rungMixed && <span className="chip tier-explo" style={{ fontSize: 10 }}>different degradation rungs</span>}
                            </div>
                          ) : <span className="sub">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>

          {rankingFindings.length > 0 && (
            <Section icon="layers" title="Ranking findings" tip="Authored by extraction from scenario replicates — never generated — each carrying the spread that says whether the order survives, and the real-world test that would disprove it.">
              <div style={{ display: "grid", gap: 10 }}>
                {rankingFindings.map((f: Finding) => <FindingCard key={f.finding_id} f={f} />)}
              </div>
            </Section>
          )}

          {riskFindings.length > 0 && (
            <Section icon="alert" title="Risk findings" tip="Authored from recorded anomalies — each with its evidence and the real-world test that would disprove it.">
              <div style={{ display: "grid", gap: 10 }}>
                {riskFindings.map((f: Finding) => <FindingCard key={f.finding_id} f={f} />)}
              </div>
            </Section>
          )}

          <div className="grid g2">
            <div>
            <Section icon="survey" title="Intent over waves: audiences" tip="Purchase intent at every survey wave, one line per audience and the share-weighted whole dashed — one chart per world.">
              <div style={{ display: "grid", gap: 16 }}>
                {digests.map((d) => (
                  <div key={d.world_id}>
                    <div className="row" style={{ marginBottom: 6 }}>
                      <b className="mono">world {d.world_id}</b>
                      <span className="chip plain mono">seed {d.seed}</span>
                    </div>
                    {(d.waves ?? []).length > 0
                      ? <IntentOverWaves waves={d.waves!} />
                      : <p className="sub" style={{ fontSize: 12 }}>unmeasured: {d.unmeasured_reason ?? "no intent measured"}</p>}
                  </div>
                ))}
              </div>
            </Section>

            </div>
            <div>
            <Section icon="fork" title="Communities: where intent ended" tip="Groups that formed in the social network, separately presented from audiences: each community's answers at the last wave. Communities often cut across audiences.">
              <div style={{ display: "grid", gap: 16 }}>
                {digests.map((d) => (
                  <div key={d.world_id}>
                    <div className="row" style={{ marginBottom: 6 }}>
                      <b className="mono">world {d.world_id}</b>
                      <span className="chip plain mono">seed {d.seed}</span>
                    </div>
                    {Object.entries(d.community_pmfs).length === 0 ? (
                      <div className="row sub" style={{ fontSize: 12 }}>{ICONS.info} No communities formed <Tip>{d.polarization_reason ?? "No communities formed in the graph."}</Tip></div>
                    ) : (
                      <>
                        {Object.entries(d.community_pmfs).map(([c, pmf]) => (
                          <div key={c} className="row" style={{ marginTop: 4 }}>
                            <span className="mono" style={{ minWidth: 110, fontSize: 12 }}>{c}</span>
                            <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                            <span className="mono sub" style={{ fontSize: 11 }}>{(top2box(pmf) * 100).toFixed(0)}% · μ {pmfMean(pmf).toFixed(2)}</span>
                          </div>
                        ))}
                        <PmfLegend />
                      </>
                    )}
                  </div>
                ))}
              </div>
            </Section>
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}

/* One finding: what it says, how sure, and the test that would prove it wrong. */
function FindingCard({ f }: { f: Finding }) {
  return (
    <div className="item">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <b className="mono">{f.finding_id}</b>
        <Chip className={f.kind === "risk" ? "risk" : "tier-pros"}>{f.confidence} confidence</Chip>
        {f.ranked_scenarios && f.ranked_scenarios.length > 0 && (
          <span className="mono sub">ordered: {f.ranked_scenarios.map((h) => h.slice(0, 8)).join(" > ")}</span>
        )}
      </div>
      <p style={{ fontWeight: 500 }}>{f.statement}</p>
      <p className="sub" style={{ fontSize: 12 }}><b>Disconfirming test:</b> {f.disconfirming_test}</p>
    </div>
  );
}

/* One number at the top of the page, with its icon and what it means on hover. */
function Kpi({ icon, label, value, tip }: { icon: keyof typeof ICONS; label: string; value: string; tip: React.ReactNode }) {
  return (
    <div className="kpi">
      <div className="k">{ICONS[icon]}{label}<Tip>{tip}</Tip></div>
      <div className="v">{value}</div>
    </div>
  );
}
