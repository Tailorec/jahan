"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, PmfBar, PmfLegend } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import { pmfMean, type StudyReport } from "@/lib/engine";

interface Detail {
  summary: { run_id: string } | null;
  report: StudyReport | null;
}

const KIND_LABEL: Record<string, string> = {
  ranking: "ranking", risk: "risk", objection: "objection",
  belief_shift: "belief shift", wom_path: "word of mouth", recommendation: "recommendation",
};

export default function ReportPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const [tab, setTab] = React.useState("findings");
  const [query, setQuery] = React.useState("");
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
          r.trust.level === "uncalibrated"
            ? <Chip className="tier-explo">uncalibrated</Chip>
            : <Chip className="tier-cust">{r.trust.level.replace("_", " ")}</Chip>
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
                    {Object.entries(d.audience_pmfs).map(([a, pmf]) => (
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
