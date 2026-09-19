"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Callout, ICONS } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { BriefRef, CategoryOntology, ClaimSource } from "@/lib/engine";

interface GateResult {
  code: number;
  run_id: string | null;
  stdout: string;
  stderr: string;
  gate: {
    overall: boolean; evidence: string; reference: string;
    results: { kind: string; attribute?: string; p_value?: number; ks_similarity?: number; passed: boolean }[];
    source_mix: Record<string, number>;
    achieved_mix: Record<string, number>;
    relaxations: { audience: string; rung: string; rows_before: number; rows_after: number }[];
  } | null;
  manifest: { persona_ids: string[]; synthesized_share: number } | null;
}

function toYaml(o: Record<string, unknown>, indent = 0): string {
  const pad = "  ".repeat(indent);
  const lines: string[] = [];
  for (const [k, v] of Object.entries(o)) {
    if (Array.isArray(v)) {
      lines.push(`${pad}${k}:`);
      for (const item of v) {
        if (item && typeof item === "object") {
          const sub = toYaml(item as Record<string, unknown>, indent + 2);
          const [first, ...rest] = sub.split("\n");
          lines.push(`${pad}  - ${first.trim()}`);
          for (const r of rest) lines.push(`${pad}    ${r.trim()}`);
        } else {
          lines.push(`${pad}  - ${JSON.stringify(item)}`);
        }
      }
    } else if (v && typeof v === "object") {
      lines.push(`${pad}${k}:`);
      lines.push(toYaml(v as Record<string, unknown>, indent + 1));
    } else if (typeof v === "string") {
      lines.push(`${pad}${k}: ${v.includes(":") || v.includes("#") ? JSON.stringify(v) : v}`);
    } else {
      lines.push(`${pad}${k}: ${JSON.stringify(v)}`);
    }
  }
  return lines.join("\n");
}

export default function IntakePage() {
  const { data: briefs } = useApi<BriefRef[]>("/api/briefs");
  const { data: ontos } = useApi<CategoryOntology[]>("/api/ontologies?category=x&version=y".replace("?category=x&version=y", ""));
  const [ontoList, setOntoList] = React.useState<{ category: string; version: string }[]>([]);
  const [onto, setOnto] = React.useState<CategoryOntology | null>(null);

  const [product, setProduct] = React.useState({ name: "Protein water", category: "", description: "Clear protein-infused water with 20g whey isolate" });
  const [price, setPrice] = React.useState("2.49");
  const [claims, setClaims] = React.useState<{ text: string; source: ClaimSource; evidence_url: string }[]>([
    { text: "20g protein with zero sugar", source: "user_asserted", evidence_url: "https://example.com/nutrition-panel" },
    { text: "Hydrates like water, not milk", source: "assumed", evidence_url: "" },
  ]);
  const [target, setTarget] = React.useState("US urban adults 25-40 who train at least weekly");
  const [audiences, setAudiences] = React.useState<{ name: string; share: string; filters: Record<string, string> }[]>([
    { name: "gym_regulars", share: "0.6", filters: {} },
    { name: "protein_dieters", share: "0.4", filters: {} },
  ]);
  const [assumptions, setAssumptions] = React.useState("Respondents distinguish clear from milky protein formats");
  const [evidence, setEvidence] = React.useState<Record<string, { content_hash: string; fetched_at: string }>>({});
  const [n, setN] = React.useState("200");
  const [gate, setGate] = React.useState<GateResult | null>(null);
  const [gating, setGating] = React.useState(false);
  const [horizon, setHorizon] = React.useState("4");
  const [seeds, setSeeds] = React.useState("4021");
  const [budget, setBudget] = React.useState("20");
  const [launching, setLaunching] = React.useState(false);
  const [launched, setLaunched] = React.useState<{ run_id?: string; error?: string } | null>(null);
  const [elicits, setElicits] = React.useState("reaction");
  const [anchorVersion, setAnchorVersion] = React.useState("purchase_intent=v1");
  const [ledger, setLedger] = React.useState<{
    valid: boolean; product: string; category: string; ontology_version: string;
    claims: string[]; audiences: string[];
    assumption_ledger: { text: string; source: string }[];
  } | null>(null);
  const [ledgerError, setLedgerError] = React.useState<string | null>(null);
  const [checkingBrief, setCheckingBrief] = React.useState(false);
  const { data: endpoint } = useApi<{ endpoint_configured: boolean; fake_available: boolean }>("/api/status");

  React.useEffect(() => {
    api<{ category: string; version: string }[]>("/api/ontologies").then(setOntoList).catch(() => {});
  }, []);
  React.useEffect(() => {
    if (!briefs?.length) return;
    const b = briefs.find((x) => x.name === "protein_water") ?? briefs[0];
    setProduct({ name: b.brief.product.name, category: b.brief.product.category, description: b.brief.product.description });
    setPrice(String(b.brief.price.amount));
    setClaims(b.brief.claims.map((c) => ({ text: c.text, source: c.source, evidence_url: c.evidence_url ?? "" })));
    setTarget(b.brief.target_market);
    setAudiences(b.brief.audiences.map((a) => ({
      name: a.name, share: a.share != null ? String(a.share) : "",
      filters: Object.fromEntries(Object.entries(a.attribute_filters).map(([k, v]) => [k, Array.isArray(v) ? v[0] : String(v)])),
    })));
    setAssumptions(b.brief.assumptions.map((a) => a.text).join("\n"));
    api<{ evidence: Record<string, { content_hash: string; fetched_at: string }> }>(`/api/briefs/${b.name}`)
      .then((d) => { if (d.evidence) setEvidence(d.evidence); })
      .catch(() => {});
  }, [briefs]);
  React.useEffect(() => {
    if (!product.category) {
      if (ontoList.length) setProduct((p) => ({ ...p, category: ontoList[0].category }));
      return;
    }
    const match = ontoList.find((o) => o.category === product.category);
    if (match) api<CategoryOntology>(`/api/ontologies?category=${match.category}&version=${match.version}`).then(setOnto).catch(() => {});
  }, [product.category, ontoList]);
  void ontos;

  const briefYaml = React.useMemo(() => {
    const audiencesYaml = audiences.map((a) => ({
      name: a.name, ...(a.share !== "" ? { share: Number(a.share) } : {}),
      attribute_filters: a.filters,
    }));
    return toYaml({
      product: { name: product.name, category: product.category, description: product.description },
      price: { amount: Number(price), currency: "USD" },
      claims: claims.map((c) => ({
        text: c.text, source: c.source, ...(c.evidence_url ? { evidence_url: c.evidence_url } : {}),
      })),
      competitors: [],
      target_market: target,
      audiences: audiencesYaml,
      assumptions: assumptions.split("\n").filter(Boolean).map((t) => ({ text: t, source: "user_asserted" })),
      ontology_version: onto?.version ?? "1.0.0",
    });
  }, [product, price, claims, target, audiences, assumptions, onto]);

  const runGate = async () => {
    setGating(true);
    setGate(null);
    try {
      const r = await api<GateResult>("/api/gate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief_yaml: briefYaml, evidence_json: evidence, n: Number(n), seed: 4021 }),
      });
      setGate(r);
    } catch (e) {
      setGate({ code: 1, run_id: null, stdout: "", stderr: String(e), gate: null, manifest: null });
    }
    setGating(false);
  };

  const launchStudy = async () => {
    setLaunching(true);
    setLaunched(null);
    try {
      const r = await api<{ run_id: string }>("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brief_yaml: briefYaml, evidence_json: evidence,
          n: Number(n), horizon: Number(horizon), seeds,
          budget: Number(budget), channel: "survey_room", fake: true,
          elicits, anchor_versions: [anchorVersion],
        }),
      });
      setLaunched({ run_id: r.run_id });
    } catch (e) {
      setLaunched({ error: String(e) });
    }
    setLaunching(false);
  };

  const checkBrief = async () => {
    setCheckingBrief(true);
    setLedger(null);
    setLedgerError(null);
    try {
      const r = await api<{
        valid: boolean; product: string; category: string; ontology_version: string;
        claims: string[]; audiences: string[];
        assumption_ledger: { text: string; source: string }[];
      }>("/api/briefs/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief_yaml: briefYaml, evidence_json: evidence }),
      });
      setLedger(r);
    } catch (e) {
      setLedgerError(String(e));
    }
    setCheckingBrief(false);
  };

  const attrs = onto ? Object.keys(onto.attribute_domains) : [];

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>New study</b></>}>
      <PageHead
        title="New study"
        sub={<>Author a <b>brief</b> — the product, its claims, price, competitors, target market — against a pinned <b>category ontology</b>. Claims carry a <b>claim source</b> — asserted, public (needs evidence), or assumed — and the assumption ledger travels into every report.</>}
        actions={<>{endpoint && <span className={`chip ${endpoint.endpoint_configured ? "ok" : "plain"}`} title="The server's environment configures the endpoint — never the browser"><span className="dot" />{endpoint.endpoint_configured ? "endpoint configured" : "no endpoint — fake only"}</span>}<span className="chip plain mono">brief YAML · validated by intake</span></>}
      />
      <div className="grid g-32">
        <div>
          <div className="panel">
            <div className="panel-head"><h2>1 · Product brief</h2><span className="hint">what the population will see</span></div>
            <div className="panel-body">
              <div className="grid g2">
                <div className="field"><label>Product name</label><input className="input" value={product.name} onChange={(e) => setProduct({ ...product, name: e.target.value })} /></div>
                <div className="field"><label>Category (ontology)</label>
                  <select className="input" value={product.category} onChange={(e) => setProduct({ ...product, category: e.target.value })}>
                    {ontoList.map((o) => <option key={o.category} value={o.category}>{o.category} @ {o.version}</option>)}
                  </select>
                  <div className="help"><Link href="/ontology">Build or extend an ontology →</Link> what can be studied is bounded by the corpus, not by which files exist.</div></div>
              </div>
              <div className="field"><label>Concept statement</label>
                <textarea className="input" rows={2} value={product.description} onChange={(e) => setProduct({ ...product, description: e.target.value })} />
                <div className="help">Shown to personas verbatim. {onto && <>Conditioning set: <span className="mono">{onto.conditioning_set.join(", ")}</span></>}</div>
              </div>
              <div className="field"><label>Claims <span style={{ fontWeight: 400, color: "var(--ink-3)" }}>(C1… auto-numbered; public_source needs an evidence URL)</span></label>
                <div className="help">A <b>claim</b> is one assertion about the product — the atomic unit of stimulus: posts, feed cards and findings all reference it.</div>
                <div style={{ display: "grid", gap: 8 }}>
                  {claims.map((c, i) => (
                    <div key={i} style={{ display: "grid", gap: 6, border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span className="mono" style={{ color: "var(--ink-3)" }}>C{i + 1}</span>
                        <input className="input" value={c.text} style={{ flex: 1 }} onChange={(e) => setClaims((cs) => cs.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
                        <select className="input" style={{ width: 140 }} value={c.source} onChange={(e) => setClaims((cs) => cs.map((x, j) => (j === i ? { ...x, source: e.target.value as ClaimSource } : x)))}>
                          <option value="user_asserted">user_asserted</option>
                          <option value="public_source">public_source</option>
                          <option value="assumed">assumed</option>
                        </select>
                        <button className="btn quiet sm" onClick={() => setClaims((cs) => cs.filter((_, j) => j !== i))}>✕</button>
                      </div>
                      {c.source === "public_source" && (
                        <>
                          <input className="input mono" placeholder="evidence_url — required for public_source" value={c.evidence_url} onChange={(e) => setClaims((cs) => cs.map((x, j) => (j === i ? { ...x, evidence_url: e.target.value } : x)))} />
                          {c.evidence_url && (
                            <div style={{ display: "flex", gap: 8 }}>
                              <input className="input mono" placeholder="sidecar content_hash (64 hex)" value={evidence[c.evidence_url]?.content_hash ?? ""} style={{ flex: 1 }}
                                onChange={(e) => setEvidence((ev) => ({ ...ev, [c.evidence_url]: { content_hash: e.target.value, fetched_at: ev[c.evidence_url]?.fetched_at ?? new Date().toISOString() } }))} />
                              <span className="tag">{evidence[c.evidence_url]?.content_hash ? "sidecar ✓" : "sidecar missing — intake will refuse"}</span>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                  <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setClaims((cs) => [...cs, { text: "", source: "assumed", evidence_url: "" }])}>+ Add claim</button>
                </div>
              </div>
              <div className="grid g2">
                <div className="field"><label>Price (USD)</label><input className="input mono" value={price} onChange={(e) => setPrice(e.target.value)} /></div>
                <div className="field"><label>Target market</label><input className="input" value={target} onChange={(e) => setTarget(e.target.value)} /></div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>2 · Audiences</h2><span className="hint">named slices of the target market; filters must use ontology attributes</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              {audiences.map((a, i) => (
                <div key={i} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="input mono" style={{ maxWidth: 200 }} value={a.name} onChange={(e) => setAudiences((xs) => xs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                    <input className="input mono" style={{ maxWidth: 100 }} placeholder="share" value={a.share} onChange={(e) => setAudiences((xs) => xs.map((x, j) => (j === i ? { ...x, share: e.target.value } : x)))} />
                    <button className="btn quiet sm" style={{ marginLeft: "auto" }} onClick={() => setAudiences((xs) => xs.filter((_, j) => j !== i))}>✕</button>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                    {Object.entries(a.filters).map(([k, v]) => (
                      <span key={k} className="tag">{k} = {v} <button aria-label="remove filter" style={{ border: "none", background: "none", cursor: "pointer" }} onClick={() => setAudiences((xs) => xs.map((x, j) => (j === i ? { ...x, filters: Object.fromEntries(Object.entries(x.filters).filter(([kk]) => kk !== k)) } : x)))}>✕</button></span>
                    ))}
                    <select className="input" style={{ width: 220 }} defaultValue="" onChange={(e) => {
                      if (!e.target.value) return;
                      const [attr, band] = e.target.value.split("=");
                      setAudiences((xs) => xs.map((x, j) => (j === i ? { ...x, filters: { ...x.filters, [attr]: band } } : x)));
                      e.target.value = "";
                    }}>
                      <option value="">+ filter…</option>
                      {onto?.ordinal_scales.flatMap((s) => s.bands.map((b) => (
                        <option key={`${s.attribute}=${b.label}`} value={`${s.attribute}=${b.label}`}>{s.attribute} = {b.label}</option>
                      )))}
                      {attrs.filter((at) => !onto?.ordinal_scales.some((s) => s.attribute === at)).map((at) => (
                        <option key={at} value={`${at}=`}>{at} = …</option>
                      ))}
                    </select>
                  </div>
                </div>
              ))}
              <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setAudiences((xs) => [...xs, { name: `audience_${xs.length + 1}`, share: "", filters: {} }])}>+ Add audience</button>
              <div className="field"><label>Stated assumptions (one per line)</label>
                <div className="help">An <b>assumption</b> is taken as true without evidence — recorded and surfaced in every report, never resolved away.</div>
                <textarea className="input" rows={2} value={assumptions} onChange={(e) => setAssumptions(e.target.value)} /></div>
            </div>
          </div>
        </div>

        <div>
          <div className="panel">
            <div className="panel-head"><h2>Brief YAML</h2><span className="hint">exactly what intake reads</span></div>
            <div className="panel-body">
              <pre className="mono" style={{ fontSize: 11, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12, maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap" }}>{briefYaml}</pre>
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><h2>Brief check</h2><span className="hint">the engine's own contracts — before a run can start</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <button className="btn" disabled={checkingBrief} onClick={checkBrief}>{checkingBrief ? "Checking…" : "Validate brief"}</button>
              {ledger && (
                <>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span className="chip ok"><span className="dot" />valid</span>
                    <span className="mono sub">{ledger.product} · {ledger.category}@{ledger.ontology_version}</span>
                    <span className="mono sub">claims {ledger.claims.join(", ")}</span>
                    <span className="mono sub">audiences {ledger.audiences.join(", ") || "—"}</span>
                  </div>
                  <div className="sub" style={{ fontSize: 12 }}>Assumption ledger — stated, assumed and unstated:</div>
                  {ledger.assumption_ledger.map((a, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span className={`chip ${a.source === "assumed" ? "assump" : "plain"}`}><span className="dot" />{a.source.replace("_", " ")}</span>
                      <span style={{ fontSize: 13 }}>{a.text}</span>
                    </div>
                  ))}
                </>
              )}
              {ledgerError && <Callout icon="alert"><div><b>The brief is refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{ledgerError}</pre></div></Callout>}
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><h2>Population gate</h2><span className="hint">real coreset-gate · --fake corpus · no spend</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="field" style={{ margin: 0 }}><label>n personas</label><input className="input mono" value={n} onChange={(e) => setN(e.target.value)} /></div>
              <button className="btn primary" disabled={gating} onClick={runGate}>{gating ? "Gating…" : `Run gate ${ICONS.arrow}`}</button>
              {gate && (
                gate.gate ? (
                  <>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <span className={`chip ${gate.gate.overall ? "ok" : "risk"}`}><span className="dot" />{gate.gate.overall ? "pass" : "fail"} (exit {gate.code})</span>
                      <span className="chip tier-explo"><span className="dot" />evidence: {gate.gate.evidence}</span>
                      <span className="chip plain mono">{gate.run_id}</span>
                    </div>
                    <table className="tbl"><tbody>
                      {gate.gate.results.map((r, i) => (
                        <tr key={i}><td className="mono sub">{r.kind} · {r.attribute ?? r.kind}</td>
                          <td className="num">{r.p_value != null ? `p ${r.p_value.toFixed(3)}` : r.ks_similarity != null ? `KS ${r.ks_similarity.toFixed(2)}` : "—"}</td>
                          <td>{r.passed ? <span className="chip ok"><span className="dot" />pass</span> : <span className="chip risk"><span className="dot" />fail</span>}</td></tr>
                      ))}
                    </tbody></table>
                    {gate.manifest && <p className="sub mono" style={{ color: "var(--ink-3)" }}>{gate.manifest.persona_ids.length} personas · synthesized {(gate.manifest.synthesized_share * 100).toFixed(1)}% · saved under runs/</p>}
                    {gate.gate.overall && gate.run_id && <Link className="btn sm" href={`/population?run=${gate.run_id}`}>Open gate report {ICONS.arrow}</Link>}
                  </>
                ) : (
                  <Callout icon="alert"><div><b>Intake refused the brief (exit {gate.code}).</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{gate.stderr || gate.stdout}</pre></div></Callout>
                )
              )}
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>A failing draw exits 2 with its gate report — a doomed study costs nothing.</p>
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><h2>Launch study</h2><span className="hint">fake first — no key, no corpus, no network</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Horizon (ticks)</label><input className="input mono" value={horizon} onChange={(e) => setHorizon(e.target.value)} /></div>
                <div className="field" style={{ margin: 0 }}><label>Seeds</label><input className="input mono" value={seeds} onChange={(e) => setSeeds(e.target.value)} /></div>
              </div>
              <div className="field" style={{ margin: 0 }}><label>Budget (USD)</label><input className="input mono" value={budget} onChange={(e) => setBudget(e.target.value)} /></div>
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Asked — what personas answer</label>
                  <select className="input" value={elicits} onChange={(e) => setElicits(e.target.value)}>
                    <option value="reaction">reaction</option>
                    <option value="purchase">purchase intent</option>
                  </select>
                  <div className="help">A purchase-intent study is scored by the anchor version below.</div></div>
                <div className="field" style={{ margin: 0 }}><label>Anchor version</label><input className="input mono" value={anchorVersion} onChange={(e) => setAnchorVersion(e.target.value)} /></div>
              </div>
              <button className="btn primary" disabled={launching} onClick={launchStudy}>{launching ? "Launching…" : `Run fake study ${ICONS.arrow}`}</button>
              {launched?.run_id && <Link className="btn sm" href={`/run?run=${launched.run_id}`}>Watch {launched.run_id} {ICONS.arrow}</Link>}
              {launched?.error && <Callout icon="alert"><div><b>Launch refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{launched.error}</pre></div></Callout>}
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>Runs as a subprocess under the same id a resume reuses. The first study is always <span className="mono">--fake</span>, marked as fake in every view of it.</p>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
