"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, PmfBar } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import { pmfMean, top2box, type OutcomeDigest, type RunSummary, type ScenarioSummary } from "@/lib/engine";

interface Detail {
  summary: RunSummary | null;
  digest: { digests: OutcomeDigest[]; summaries: Record<string, ScenarioSummary> } | null;
}

export default function AtlasPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const s = data?.summary ?? null;
  const digests = data?.digest?.digests ?? [];

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Sweep / <b>Scenario atlas</b></>}>
      <PageHead
        title="Sweep — scenarios × seeds"
        sub="One run over many worlds sharing one budget. Each cell is a world: its digest measured adoption and polarization, and the spread across a scenario's worlds is the variance estimate."
        actions={s && <span className="chip plain mono">{digests.length} world(s) · {s.seeds.length} seed(s)</span>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading sweep…</b></div>}
      {s && (
        <>
          <div className="panel">
            <div className="panel-head"><h2>Adoption plane</h2><span className="hint">measured top-2 box per world, audience-weighted</span></div>
            <div className="panel-body">
              <table className="tbl">
                <thead><tr><th>Scenario</th>{s.seeds.map((seed) => <th key={seed} className="num">seed {seed}</th>)}</tr></thead>
                <tbody>
                  {s.scenarios.map((sc, si) => (
                    <tr key={si}>
                      <td className="strong">{sc.variant.variant_id} · {sc.variant.name}<br /><span className="sub">${sc.price.amount} {sc.price.currency} · {sc.tick_unit} × {sc.horizon_ticks}{sc.interventions.length ? ` · ${sc.interventions.map((i) => `${i.kind}@${i.tick}`).join(", ")}` : ""}</span></td>
                      {s.seeds.map((seed) => {
                        const d = digests.find((x) => x.seed === seed);
                        return (
                          <td key={seed} className="num">
                            {d ? (
                              d.adoption != null ? (
                                <Link href={`/run?run=${runId}`}>
                                  <span className="heat" style={{ background: d.adoption > 0.5 ? "var(--primary-soft)" : "var(--surface-2)" }}>{(d.adoption * 100).toFixed(1)}%</span>
                                </Link>
                              ) : <span className="sub">unmeasured</span>
                            ) : <span className="sub">no world</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12, marginTop: 10 }}>
                Variant <span className="mono">{s.scenarios[0]?.variant.variant_id}</span> emphasizes claims <span className="mono">{s.scenarios[0]?.variant.emphasized_claims.join(", ")}</span> —
                the price is part of the scenario, never the variant. Audience weights <span className="mono">{Object.entries(s.scenarios[0]?.audience_weights ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>.
              </p>
            </div>
          </div>

          {digests.map((d) => (
            <div key={d.world_id} style={{ marginTop: 16 }}>
              <div className="panel">
                <div className="panel-head"><h2>World <span className="mono">{d.world_id}</span></h2>
                  <span className="hint">seed {d.seed} · {d.turn_count} turns</span>
                  <div className="tools">
                    {d.adoption != null
                      ? <span className="chip tier-pros"><span className="dot" />adoption {(d.adoption * 100).toFixed(1)}%</span>
                      : <span className="chip tier-explo"><span className="dot" />unmeasured: {d.unmeasured_reason}</span>}
                  </div></div>
                <div className="panel-body" style={{ display: "grid", gap: 10 }}>
                  {Object.entries(d.audience_pmfs).map(([a, pmf]) => (
                    <div key={a} style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                      <b className="mono" style={{ minWidth: 140 }}>{a}</b>
                      <div style={{ flex: 1, minWidth: 220 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                      <span className="mono sub">mean {pmfMean(pmf).toFixed(2)} · top-2 {(top2box(pmf) * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  {d.polarization == null && d.polarization_reason && (
                    <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>{d.polarization_reason}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </Shell>
  );
}
