"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, ICONS } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { RunSummary } from "@/lib/engine";

interface Overview {
  runs: RunSummary[];
  ontologies: { category: string; version: string; attributes: string[]; conditioning_set: string[] }[];
  briefs: { name: string; product: string; category: string; claims: number; audiences: string[] }[];
}

function trustChip(level?: string | null) {
  if (level === "uncalibrated") return <Chip className="tier-explo">uncalibrated</Chip>;
  if (level === "category_benchmarked") return <Chip className="tier-cat">category-benchmarked</Chip>;
  if (level === "prospectively_validated") return <Chip className="tier-cust">prospective-validated</Chip>;
  return <span className="sub">—</span>;
}

export default function OverviewPage() {
  const { data, error } = useApi<Overview>("/api/overview");
  return (
    <Shell crumbs={<><span>Workspace</span> / <b>Overview</b></>}>
      <PageHead
        title="Studies"
        sub="Every row below is a real artefact in runs/ — written by the engine CLI, read live by this UI. Nothing here is mock state."
        actions={<Link className="btn primary" href="/intake">New study {ICONS.arrow}</Link>}
      />
      {error && <Callout icon="alert"><div>Could not reach the engine checkout: {error}. Set SIM_ENGINE_ROOT.</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading engine state…</b>reading runs/, ontologies/, examples/</div>}
      {data && (
        <>
          <div className="stat-strip" style={{ marginBottom: 20 }}>
            <div className="stat"><div className="k">Runs on disk</div><div className="v">{data.runs.length}</div><div className="d">{data.runs.filter((r) => r.has_report).length} with reports</div></div>
            <div className="stat"><div className="k">Recorded spend</div><div className="v">${data.runs.reduce((a, r) => a + r.recorded_cost, 0).toFixed(2)}</div><div className="d">sum of cost ledgers</div></div>
            <div className="stat"><div className="k">Worlds executed</div><div className="v">{data.runs.reduce((a, r) => a + r.world_ids.length, 0)}</div><div className="d">across all runs</div></div>
            <div className="stat"><div className="k">Ontologies</div><div className="v">{data.ontologies.length}</div><div className="d">category × version</div></div>
            <div className="stat"><div className="k">Briefs</div><div className="v">{data.briefs.length}</div><div className="d">examples/*.yaml</div></div>
          </div>

          <div className="sect-title">Runs</div>
          <div className="panel"><div className="panel-body tight">
            <table className="tbl">
              <thead><tr><th style={{ width: "30%" }}>Run</th><th>Status</th><th>Scenarios × seeds</th><th className="num">Cost</th><th>Trust</th><th className="num">Findings</th><th></th></tr></thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.run_id}>
                    <td className="strong mono">{r.run_id}{r.engine_version && <span className="sub"> · {r.engine_version}</span>}</td>
                    <td>
                      {r.status === "completed" && <Chip className="ok">completed</Chip>}
                      {r.status !== "completed" && <Chip className="plain">{r.status}</Chip>}
                      {!r.has_report && r.has_gate_report && <span style={{ marginLeft: 6 }}><Chip className="plain">gate only</Chip></span>}
                    </td>
                    <td className="mono">{r.scenarios.length} × {r.seeds.length || "—"}</td>
                    <td className="num">${r.recorded_cost.toFixed(2)}</td>
                    <td>{trustChip(r.trust_level)}</td>
                    <td className="num">{r.finding_count}</td>
                    <td className="num">
                      {r.has_report ? <Link href={`/report?run=${r.run_id}`}>Report {ICONS.ext}</Link>
                        : r.has_gate_report ? <Link href={`/cohort?run=${r.run_id}`}>Gates {ICONS.ext}</Link> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div></div>

          <div className="grid g2" style={{ marginTop: 24 }}>
            <div>
              <div className="sect-title">Category ontologies</div>
              <div className="panel"><div className="panel-body tight">
                <table className="tbl">
                  <thead><tr><th>Category</th><th className="num">Version</th><th>Conditioning set</th></tr></thead>
                  <tbody>
                    {data.ontologies.map((o) => (
                      <tr key={`${o.category}@${o.version}`}>
                        <td className="strong mono">{o.category}</td>
                        <td className="num mono">{o.version}</td>
                        <td className="mono sub">{o.conditioning_set.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div></div>
            </div>
            <div>
              <div className="sect-title">Briefs</div>
              <div className="panel"><div className="panel-body tight">
                <table className="tbl">
                  <thead><tr><th>Brief</th><th>Product</th><th className="num">Claims</th><th>Audiences</th></tr></thead>
                  <tbody>
                    {data.briefs.map((b) => (
                      <tr key={b.name}>
                        <td className="mono strong">{b.name}</td>
                        <td>{b.product} <span className="sub mono">· {b.category}</span></td>
                        <td className="num">{b.claims}</td>
                        <td className="mono sub">{b.audiences.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div></div>
              <Callout icon="info" style={{ marginTop: 16 }}>
                <div>Gate-only runs (e.g. <span className="mono">run-gate500</span>) stopped after the population gate — no worlds, no spend. That is the engine refusing a doomed study, not a failure.</div>
              </Callout>
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}
