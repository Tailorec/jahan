"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, TrustLine } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import type {
  CategoryOntology, GateReport, GateResult, OutcomeDigest, PersonaRecord, PopulationManifest,
} from "@/lib/engine";

interface Detail {
  gate: GateReport | null;
  manifest: PopulationManifest | null;
  report: { trust: { level: string } } | null;
  digest: { digests: OutcomeDigest[] } | null;
  personas: PersonaRecord[] | null;
  personaTotal: number;
  ontology: CategoryOntology | null;
}

function gateStatistic(r: GateResult): string {
  if (r.kind === "categorical") {
    return `χ² ${r.chi_square?.toFixed(2) ?? "—"} · dof ${r.degrees_of_freedom ?? "—"} · p ${r.p_value?.toFixed(3) ?? "—"}`;
  }
  if (r.kind === "ordinal") {
    return `D ${r.ks_statistic?.toFixed(3) ?? "—"} · similarity ${r.ks_similarity?.toFixed(2) ?? "—"}`;
  }
  return `${r.measured ?? "—"} vs ${r.threshold ?? "—"}`;
}

function gateThreshold(r: GateResult): string {
  if (r.kind === "categorical") return `pass at p > ${r.significance_level ?? 0.05}`;
  if (r.kind === "ordinal") return `pass at similarity ≥ ${r.similarity_threshold ?? 0.8}`;
  return "inside its band";
}

function OriginTag({ origin }: { origin: string }) {
  const cls = origin === "measured" ? "ok" : origin === "extracted" ? "tier-cat" : "tier-explo";
  return <span className={`tag ${cls}`}>{origin}</span>;
}

export default function PopulationPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const gate = data?.gate ?? null;
  const manifest = data?.manifest ?? null;
  const digest = data?.digest?.digests[0] ?? null;
  const personas = data?.personas ?? null;
  const onto = data?.ontology ?? null;
  const completable: string[] = (onto?.completion_policy as { completable_domains?: string[] } | undefined)?.completable_domains ?? [];

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Population / <b>Population</b></>}>
      <PageHead
        title="Population — who is in this study"
        sub={runId ? <>Run <span className="mono">{runId}</span>{manifest && <> · population hash <span className="mono">{manifest.population_hash.slice(0, 12)}…</span> · draw seed <span className="mono">{manifest.population_seed}</span></>} · Nothing was simulated and nothing was spent until the gate passed.</> : "Pick a run."}
        actions={gate && <>{gate.overall ? <Chip className="ok">gate passed</Chip> : <Chip className="risk">gate failed</Chip>}<Chip className="tier-explo">evidence: weakest {gate.evidence}</Chip></>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading population…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !gate && <Callout icon="alert"><div>No gate-report.json for this run.</div></Callout>}
      {gate && !gate.overall && (
        <Callout icon="alert"><div><b>This study never ran.</b> The draw failed its distribution gates, so no personas were built, no worlds ran and nothing was spent. The table below is the case this page most needs to explain — each gate names its statistic, its threshold and its verdict, so the call can be recomputed.</div></Callout>
      )}
      {gate && (
        <>
          <div className="stat-strip" style={{ marginBottom: 20 }}>
            <div className="stat"><div className="k">Personas</div><div className="v">{manifest ? manifest.persona_ids.length.toLocaleString() : "none built"}</div><div className="d">{manifest ? "drawn for requested mix" : "the draw failed its gates, so no population was kept"}</div></div>
            <div className="stat"><div className="k">Source mix</div><div className="v">{Object.entries(gate.source_mix).map(([s, w]) => `${s} ${(w * 100).toFixed(1)}%`).join(" · ")}</div><div className="d">which corpus each row came from</div></div>
            <div className="stat"><div className="k">Synthesized</div><div className="v">{manifest ? <>{(manifest.synthesized_share * 100).toFixed(1)}<small>%</small></> : "—"}</div><div className="d">{manifest ? "model-completed fields only" : "no manifest to state it"}</div></div>
            <div className="stat"><div className="k">Relaxations</div><div className="v">{gate.relaxations.length}</div><div className="d">{gate.relaxations.length ? "filters loosened to fill quotas" : "audience matched as declared"}</div></div>
            <div className="stat"><div className="k">Reference</div><div className="v" style={{ fontSize: 16 }}>{gate.reference.replace("_", " ")}</div><div className="d">what the gates were judged against</div></div>
          </div>

          <div className="grid g2">
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Audience mix</h2><span className="hint">requested vs achieved</span></div>
                <div className="panel-body tight"><table className="tbl">
                  <thead><tr><th>Audience</th><th className="num">Requested</th><th className="num">Achieved</th></tr></thead>
                  <tbody>
                    {Object.keys(manifest?.requested_mix ?? gate.achieved_mix).map((a) => (
                      <tr key={a}><td className="strong mono">{a}</td>
                        <td className="num">{manifest ? `${(manifest.requested_mix[a] * 100).toFixed(1)}%` : "not recorded"}</td>
                        <td className="num">{((gate.achieved_mix[a] ?? 0) * 100).toFixed(1)}%</td></tr>
                    ))}
                  </tbody>
                </table></div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Distribution gates</h2><span className="hint">population marginals vs {gate.reference.replace("_", " ")} — recompute the call from statistic and threshold</span></div>
                <div className="panel-body tight"><table className="tbl">
                  <thead><tr><th>Gate</th><th>Statistic</th><th>Threshold</th><th></th></tr></thead>
                  <tbody>
                    {gate.results.map((r, i) => (
                      <tr key={i}><td className="mono">{r.kind}{r.attribute ? ` · ${r.attribute}` : ""}{r.check ? ` · ${r.check}` : ""}</td>
                        <td className="mono sub">{gateStatistic(r)}</td>
                        <td className="mono sub">{gateThreshold(r)}</td>
                        <td>{r.passed ? <Chip className="ok">pass</Chip> : <Chip className="risk">fail</Chip>}</td></tr>
                    ))}
                  </tbody>
                </table></div>
              </div>
              {gate.relaxations.length > 0 && (
                <Callout icon="alert"><div><b>{gate.relaxations.length} relaxation{gate.relaxations.length > 1 ? "s" : ""}.</b> The population no longer matches the audience as declared:
                  {gate.relaxations.map((r, i) => <div key={i} className="mono" style={{ fontSize: 12 }}>{r.audience} · {r.rung} · rows {r.rows_before} → {r.rows_after}</div>)}</div></Callout>
              )}
              <div className="panel">
                <div className="panel-head"><h2>Completion</h2><span className="hint">sparse fields only — demographics and psychographics are never synthesized</span></div>
                <div className="panel-body tight"><table className="tbl"><tbody>
                  <tr><td>May be completed</td><td className="mono sub">{completable.length ? completable.join(", ") : "—"}</td></tr>
                  <tr><td>Never synthesized</td><td className="mono sub">demographic, psychographic</td></tr>
                  <tr><td>Model</td><td className="num mono">{manifest?.completion?.model_id ?? "—"}</td></tr>
                  <tr><td>Graph</td><td className="num mono">{manifest ? (manifest.graph_hash ? `${manifest.graph_hash.slice(0, 12)}…` : "none attached") : "—"}</td></tr>
                </tbody></table></div>
              </div>
            </div>
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Sample personas</h2><span className="hint">{(data?.personaTotal ?? 0).toLocaleString()} in personas.json — every field states its origin</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                  {!personas && (manifest
                    ? <div className="empty"><b>No persona records.</b>Runs recorded before personas.json need a re-run — the manifest alone cannot say where a field came from.</div>
                    : <div className="empty"><b>No personas were built.</b>The draw failed its gates before any persona was kept, so there is no record to sample.</div>)}
                  {(personas ?? []).map((p) => (
                    <div key={p.persona_id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <b className="mono">{p.persona_id}</b>
                        <span className="tag">source: {p.source}</span>
                        <Link href={`/trace?run=${runId}&persona=${encodeURIComponent(p.persona_id)}`} style={{ marginLeft: "auto", fontSize: 12 }}>beliefs →</Link>
                      </div>
                      <div className="mono sub" style={{ marginTop: 6, fontSize: 11.5 }}>
                        {Object.entries({ ...p.conditioning, ...p.attributes }).map(([k, v]) => (
                          <span key={k} style={{ marginRight: 10 }}>{k}={String(v)} <OriginTag origin={p.origins[k] ?? "?"} /></span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Audiences vs communities</h2><span className="hint">declared slices against discovered structure</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                  <p className="sub" style={{ fontSize: 12.5 }}>Audiences are declared in the brief; communities emerge from the social graph and routinely cut across audiences — that divergence is a finding, not a defect.</p>
                  {digest && Object.keys(digest.community_sizes ?? {}).length > 0 ? (
                    <table className="tbl"><thead><tr><th>Community</th><th className="num">Share</th></tr></thead><tbody>
                      {Object.entries(digest.community_sizes).map(([c, s]) => (
                        <tr key={c}><td className="mono">{c}</td><td className="num">{(s * 100).toFixed(1)}%</td></tr>
                      ))}
                    </tbody></table>
                  ) : (
                    <div className="empty"><b>No communities formed.</b>{digest?.polarization_reason ? <> {digest.polarization_reason}</> : " The graph formed no qualifying partition, so polarization is unmeasured rather than zero."}</div>
                  )}
                  {digest && <p className="sub mono" style={{ fontSize: 11.5 }}>world {digest.world_id} · audience divergence {digest.audience_divergence != null ? digest.audience_divergence.toFixed(3) : "—"} · polarization {digest.polarization != null ? digest.polarization.toFixed(3) : "unmeasured"}</p>}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}
