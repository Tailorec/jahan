"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, PmfBar, TrustLine } from "@/components/ui";
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

export default function AtlasPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const s = data?.summary ?? null;
  const digests = data?.digest?.digests ?? [];
  const summaries = data?.digest?.summaries ?? {};
  const report = data?.report ?? null;

  // Phase 9: Findings authored by extraction (never generated)
  const rankingFindings = (report?.findings ?? []).filter((f) => f.kind === "ranking");
  const riskFindings = (report?.findings ?? []).filter((f) => f.kind === "risk");

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Sweep / <b>Scenario atlas</b></>}>
      <PageHead
        title="Sweep — scenarios × seeds"
        sub="One run over many worlds sharing one budget. Each cell is a world: its digest measured adoption and polarization, and the spread across a scenario's worlds is the variance estimate."
        actions={s && <span className="chip plain mono">{digests.length} world(s) · {s.seeds.length} seed(s)</span>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading sweep…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}

      {s && (
        <div style={{ display: "grid", gap: 20 }}>
          {/* Phase 9: Adoption against polarization plane */}
          <div className="panel">
            <div className="panel-head">
              <h2>Adoption against polarization plane</h2>
              <span className="hint">measured top-2 box and polarization per world, audience-weighted</span>
            </div>
            <div className="panel-body">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    {s.seeds.map((seed) => (
                      <th key={seed} className="num">seed {seed}</th>
                    ))}
                    <th>Replicate spread</th>
                  </tr>
                </thead>
                <tbody>
                  {s.scenarios.map((sc, si) => {
                    const scSummary = (sc.scenario_hash ? summaries[sc.scenario_hash] : null) ?? summaries[sc.variant.variant_id] ?? null;
                    const rungMixed = scSummary?.rung_mixed ?? false;

                    return (
                      <tr key={si}>
                        <td className="strong">
                          {sc.variant.variant_id} · {sc.variant.name}
                          <br />
                          <span className="sub">
                            ${sc.price.amount} {sc.price.currency} · {sc.tick_unit} × {sc.horizon_ticks}
                            {sc.interventions.length ? ` · ${sc.interventions.map((i) => `${i.kind}@${i.tick}`).join(", ")}` : ""}
                          </span>
                        </td>
                        {s.seeds.map((seed) => {
                          const d = digests.find((x) => x.seed === seed && (x.scenario_hash === sc.scenario_hash || digests.length <= s.seeds.length));
                          if (!d) return <td key={seed} className="num"><span className="sub">no world</span></td>;

                          // Phase 9 acceptance criterion: A cell whose worlds ran at different degradation rungs is marked rather than silently compared
                          const cellDegraded = (d.rungs ?? []).length > 0;

                          return (
                            <td key={seed} className="num">
                              <div style={{ display: "grid", gap: 4, justifyItems: "end" }}>
                                {d.adoption != null ? (
                                  <span className="heat" style={{ background: d.adoption > 0.5 ? "var(--primary-soft)" : "var(--surface-2)" }}>
                                    {(d.adoption * 100).toFixed(1)}%
                                  </span>
                                ) : (
                                  /* Phase 9 acceptance criterion: A quantity no world measured is stated as unmeasured with its reason, never drawn as zero */
                                  <span className="sub" style={{ fontStyle: "italic", fontSize: 11 }}>
                                    unmeasured: {d.unmeasured_reason ?? "unmeasured"}
                                  </span>
                                )}

                                {d.polarization != null ? (
                                  <span className="mono sub" style={{ fontSize: 11 }}>
                                    pol {d.polarization.toFixed(2)}
                                  </span>
                                ) : d.polarization_reason ? (
                                  <span className="sub" style={{ fontStyle: "italic", fontSize: 11 }}>
                                    {d.polarization_reason}
                                  </span>
                                ) : null}

                                {cellDegraded && (
                                  <span className="chip warn" style={{ fontSize: 10 }}>
                                    degraded rung ({d.rungs.join(", ")})
                                  </span>
                                )}
                              </div>
                            </td>
                          );
                        })}

                        {/* Replicate spread that says whether an ordering survives */}
                        <td style={{ minWidth: 160 }}>
                          {scSummary ? (
                            <div style={{ fontSize: 12 }}>
                              <div>
                                Spread: <span className="mono">{scSummary.adoption_spread != null ? `±${(scSummary.adoption_spread * 100).toFixed(1)}%` : "n/a"}</span>
                              </div>
                              {rungMixed && (
                                <span className="chip warn" style={{ fontSize: 10, marginTop: 4 }}>
                                  different degradation rungs
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="sub">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12, marginTop: 10 }}>
                Cells whose worlds ran at different degradation rungs are marked rather than silently compared. Unmeasured quantities render their reason where the number would have been.
              </p>
            </div>
          </div>

          {/* Phase 9: Ranking findings over scenario replicates */}
          {rankingFindings.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Ranking findings</h2>
                <span className="hint">authored by extraction from scenario replicates — carrying the spread that says whether the order survives</span>
              </div>
              <div className="panel-body" style={{ display: "grid", gap: 12 }}>
                {rankingFindings.map((f: Finding) => (
                  <div key={f.finding_id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <b className="mono">{f.finding_id}</b>
                      <Chip className="active">{f.confidence} confidence</Chip>
                      {f.ranked_scenarios && f.ranked_scenarios.length > 0 && (
                        <span className="mono sub">
                          ordered: {f.ranked_scenarios.map((h) => h.slice(0, 8)).join(" > ")}
                        </span>
                      )}
                    </div>
                    <p style={{ marginTop: 8, fontWeight: 500 }}>{f.statement}</p>
                    <p className="sub" style={{ marginTop: 6, fontSize: 12 }}>
                      <b>Disconfirming test:</b> {f.disconfirming_test}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Phase 9: Risk findings from anomalies */}
          {riskFindings.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Risk findings</h2>
                <span className="hint">authored from recorded anomalies — each with evidence and disconfirming test</span>
              </div>
              <div className="panel-body" style={{ display: "grid", gap: 12 }}>
                {riskFindings.map((f: Finding) => (
                  <div key={f.finding_id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <b className="mono">{f.finding_id}</b>
                      <Chip className="plain">{f.confidence} confidence</Chip>
                    </div>
                    <p style={{ marginTop: 8, fontWeight: 500 }}>{f.statement}</p>
                    <p className="sub" style={{ marginTop: 6, fontSize: 12 }}>
                      <b>Disconfirming test:</b> {f.disconfirming_test}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Phase 9: Per-tick trajectories for audiences and, separately, for communities */}
          <div className="grid g2">
            <div className="panel">
              <div className="panel-head">
                <h2>Per-tick trajectories: Audiences</h2>
                <span className="hint">per-tick movement per audience</span>
              </div>
              <div className="panel-body tight">
                {digests.map((d) => (
                  <div key={d.world_id} style={{ padding: 12, borderBottom: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                      <b className="mono">World {d.world_id}</b>
                      <span className="sub mono">seed {d.seed}</span>
                    </div>
                    {Object.entries(d.audience_pmfs).length === 0 ? (
                      <p className="sub" style={{ fontSize: 12 }}>
                        unmeasured: {d.unmeasured_reason ?? "no intent measured"}
                      </p>
                    ) : (
                      Object.entries(d.audience_pmfs).map(([a, pmf]) => (
                        <div key={a} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                          <span className="mono" style={{ minWidth: 120, fontSize: 12 }}>{a}</span>
                          <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                          <span className="mono sub" style={{ fontSize: 11 }}>
                            mean {pmfMean(pmf).toFixed(2)} · top-2 {(top2box(pmf) * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Per-tick trajectories: Communities</h2>
                <span className="hint">separately presented from audiences</span>
              </div>
              <div className="panel-body tight">
                {digests.map((d) => (
                  <div key={d.world_id} style={{ padding: 12, borderBottom: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                      <b className="mono">World {d.world_id}</b>
                      <span className="sub mono">seed {d.seed}</span>
                    </div>
                    {Object.entries(d.community_pmfs).length === 0 ? (
                      <p className="sub" style={{ fontSize: 12 }}>
                        {d.polarization_reason ?? "No communities formed in graph"}
                      </p>
                    ) : (
                      Object.entries(d.community_pmfs).map(([c, pmf]) => (
                        <div key={c} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                          <span className="mono" style={{ minWidth: 120, fontSize: 12 }}>{c}</span>
                          <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                          <span className="mono sub" style={{ fontSize: 11 }}>
                            mean {pmfMean(pmf).toFixed(2)} · top-2 {(top2box(pmf) * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}
