"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, TrustLine } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import type { GateReport, PopulationManifest } from "@/lib/engine";

interface Detail {
  gate: GateReport | null;
  manifest: PopulationManifest | null;
  report: { trust: { level: string } } | null;
}

export default function CohortPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const gate = data?.gate ?? null;
  const manifest = data?.manifest ?? null;
  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Population / <b>Cohort gate</b></>}>
      <PageHead
        title="Cohort gate — trust checkpoint"
        sub={runId ? <>Run <span className="mono">{runId}</span> · population hash <span className="mono">{manifest?.population_hash.slice(0, 12)}…</span> · draw seed <span className="mono">{manifest?.population_seed}</span>. Nothing was simulated and nothing was spent until this gate passed.</> : "Pick a run."}
        actions={gate && <>{gate.overall ? <Chip className="ok">gate passed</Chip> : <Chip className="risk">gate failed</Chip>}<Chip className="tier-explo">evidence: weakest {gate.evidence}</Chip></>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading gate report…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !gate && <Callout icon="alert"><div>No gate-report.json for this run.</div></Callout>}
      {gate && manifest && (
        <>
          <div className="stat-strip" style={{ marginBottom: 20 }}>
            <div className="stat"><div className="k">Personas</div><div className="v">{manifest.persona_ids.length.toLocaleString()}</div><div className="d">drawn for requested mix</div></div>
            <div className="stat"><div className="k">Source mix</div><div className="v">{Object.entries(gate.source_mix).map(([s, w]) => `${s} ${(w * 100).toFixed(1)}%`).join(" · ")}</div><div className="d">which corpus each row came from</div></div>
            <div className="stat"><div className="k">Synthesized</div><div className="v">{(manifest.synthesized_share * 100).toFixed(1)}<small>%</small></div><div className="d">model-completed fields only</div></div>
            <div className="stat"><div className="k">Relaxations</div><div className="v">{gate.relaxations.length}</div><div className="d">{gate.relaxations.length ? "filters loosened to fill quotas" : "audience matched as declared"}</div></div>
            <div className="stat"><div className="k">Reference</div><div className="v" style={{ fontSize: 16 }}>{gate.reference.replace("_", " ")}</div><div className="d">what the gates were judged against</div></div>
          </div>

          <div className="grid g2">
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Audience mix</h2><span className="hint">requested vs achieved</span></div>
                <div className="panel-body tight"><table className="tbl">
                  <thead><tr><th>Audience</th><th className="num">Requested</th><th className="num">Achieved</th><th>Field origins</th></tr></thead>
                  <tbody>
                    {Object.keys(manifest.requested_mix).map((a) => (
                      <tr key={a}><td className="strong mono">{a}</td>
                        <td className="num">{(manifest.requested_mix[a] * 100).toFixed(1)}%</td>
                        <td className="num">{((gate.achieved_mix[a] ?? 0) * 100).toFixed(1)}%</td>
                        <td className="mono sub">{Object.entries(gate.attribute_origins).map(([f, o]) => `${f}:${o}`).join(" · ")}</td></tr>
                    ))}
                  </tbody>
                </table></div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Distribution gates</h2><span className="hint">population marginals vs {gate.reference.replace("_", " ")}</span></div>
                <div className="panel-body tight"><table className="tbl">
                  <thead><tr><th>Gate</th><th className="num">χ² p</th><th className="num">KS similarity</th><th></th></tr></thead>
                  <tbody>
                    {gate.results.map((r, i) => (
                      <tr key={i}><td className="mono">{r.kind}{r.attribute ? ` · ${r.attribute}` : ""}{r.check ? ` · ${r.check}` : ""}</td>
                        <td className="num">{r.p_value != null ? r.p_value.toFixed(3) : "—"}</td>
                        <td className="num">{r.ks_similarity != null ? r.ks_similarity.toFixed(2) : r.measured != null ? String(r.measured) : "—"}</td>
                        <td>{r.passed ? <Chip className="ok">pass</Chip> : <Chip className="risk">fail</Chip>}</td></tr>
                    ))}
                  </tbody>
                </table></div>
              </div>
              {gate.relaxations.length > 0 && (
                <Callout icon="alert"><div><b>{gate.relaxations.length} relaxation{gate.relaxations.length > 1 ? "s" : ""}.</b> The population no longer matches the audience as declared:
                  {gate.relaxations.map((r, i) => <div key={i} className="mono" style={{ fontSize: 12 }}>{r.audience} · {r.rung} · rows {r.rows_before} → {r.rows_after}</div>)}</div></Callout>
              )}
            </div>
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Sample personas</h2><span className="hint">first rows of the manifest — every id traceable to its corpus row</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                  {manifest.persona_ids.slice(0, 6).map((id) => (
                    <div key={id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <b className="mono">{id}</b>
                      <span className="tag">source: {id.split(":")[0].replace("p-persona-", "").replace("p-", "")}</span>
                      <Link href={`/trace?run=${runId}&persona=${encodeURIComponent(id)}`} style={{ marginLeft: "auto", fontSize: 12 }}>beliefs →</Link>
                    </div>
                  ))}
                  <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>…and {(manifest.persona_ids.length - 6).toLocaleString()} more in manifest.json</p>
                </div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Completion</h2><span className="hint">sparse fields only — demographics never synthesized</span></div>
                <div className="panel-body tight"><table className="tbl"><tbody>
                  <tr><td>Model</td><td className="num mono">{manifest.completion?.model_id ?? "—"}</td></tr>
                  <tr><td>Template</td><td className="num mono">{manifest.completion?.template_id ?? "—"} · {manifest.completion?.template_hash.slice(0, 12)}…</td></tr>
                  <tr><td>Graph</td><td className="num mono">{manifest.graph_hash ? `${manifest.graph_hash.slice(0, 12)}…` : "none attached"}</td></tr>
                </tbody></table></div>
              </div>
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}
