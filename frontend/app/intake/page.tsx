"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Callout, ICONS } from "@/components/ui";
import { api, useApi, whyNot } from "@/lib/api";
import { briefToYaml, formFromBrief, type BriefForm } from "@/lib/briefYaml";
import type { BriefRef, CategoryOntology, ClaimSource } from "@/lib/engine";
import {
  CHANNELS, CHANNEL_GUIDE, ONE_ENVIRONMENT_NOTE, cachedShards, defaultAnchor, defaultSources, gateRequest, problems, studyRequest,
  type AnchorCatalogue, type ChannelName, type CorpusInfo, type StudyForm,
} from "@/lib/study";

/* What the population gate answers: the report and manifest the engine wrote, or — when the
   draw was refused before a report existed — the engine's reason, never a path. */
interface GateResult {
  code: number;
  run_id: string | null;
  refusal: string | null;
  gate: {
    overall: boolean; evidence: string; reference: string;
    results: { kind: string; attribute?: string; p_value?: number; ks_similarity?: number; passed: boolean }[];
    source_mix: Record<string, number>;
    achieved_mix: Record<string, number>;
    relaxations: { audience: string; rung: string; rows_before: number; rows_after: number }[];
  } | null;
  manifest: { persona_ids: string[]; synthesized_share: number } | null;
}

const BLANK: BriefForm = {
  product: { name: "", category: "", description: "" },
  price: "", currency: "USD",
  claims: [{ text: "", source: "assumed", evidence_url: "" }],
  competitors: [],
  target: "",
  audiences: [{ name: "audience_1", share: "1", filters: {} }],
  assumptions: [],
  ontologyVersion: "1.0.0",
};

export default function IntakePage() {
  const { data: briefs } = useApi<BriefRef[]>("/api/briefs");
  const [ontoList, setOntoList] = React.useState<{ category: string; version: string }[]>([]);
  const [onto, setOnto] = React.useState<CategoryOntology | null>(null);

  // The brief, as the form holds it. Nothing about it lives anywhere else: the YAML below is
  // this state written out, and it is what the engine's intake reads.
  const [form, setForm] = React.useState<BriefForm>(BLANK);
  const setProduct = (patch: Partial<BriefForm["product"]>) => setForm((f) => ({ ...f, product: { ...f.product, ...patch } }));
  const [evidence, setEvidence] = React.useState<Record<string, { content_hash: string; fetched_at: string }>>({});

  // The study: what is run, not what is said about the product.
  const [n, setN] = React.useState("200");
  const [horizon, setHorizon] = React.useState("4");
  const [tickUnit, setTickUnit] = React.useState("day");
  const [seeds, setSeeds] = React.useState("4021");
  const [budget, setBudget] = React.useState("20");
  const [elicits, setElicits] = React.useState("reaction");
  const [anchorVersion, setAnchorVersion] = React.useState("");
  const [mode, setMode] = React.useState<"fake" | "real">("fake");
  const [model, setModel] = React.useState("");
  const [embedModel, setEmbedModel] = React.useState("");
  // What a real study also decides: where the population is drawn from, which draw, and what the models cost.
  // Defaults come from what is actually there — the cached shards, the measured sources, a scale that passed.
  const [channel, setChannel] = React.useState<ChannelName>("survey_room");
  const [populationSeed, setPopulationSeed] = React.useState("4021");
  const [shards, setShards] = React.useState<string[]>([]);
  const [sources, setSources] = React.useState<string[]>([]);
  const [priceChatIn, setPriceChatIn] = React.useState("");
  const [priceChatOut, setPriceChatOut] = React.useState("");
  const [priceEmbedIn, setPriceEmbedIn] = React.useState("");
  const [validation, setValidation] = React.useState("");
  const { data: corpus } = useApi<CorpusInfo>("/api/corpus");
  const { data: anchors } = useApi<AnchorCatalogue>("/api/anchors");
  React.useEffect(() => {
    if (corpus) { setShards(cachedShards(corpus)); setSources(defaultSources(corpus)); }
  }, [corpus]);
  React.useEffect(() => {
    if (anchors && !anchorVersion) setAnchorVersion(defaultAnchor(anchors));
  }, [anchors, anchorVersion]);

  const [gate, setGate] = React.useState<GateResult | null>(null);
  const [gating, setGating] = React.useState(false);
  const [launching, setLaunching] = React.useState(false);
  const [launched, setLaunched] = React.useState<{ run_id?: string; error?: string } | null>(null);
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
  // A brief the engine already holds is where authoring usually starts; the first one loaded
  // fills the form once, and after that the form is the person's.
  const loadBrief = React.useCallback((b: BriefRef) => {
    setForm(formFromBrief(b.brief));
    setEvidence({});
    setGate(null);
    setLedger(null);
    api<{ evidence: Record<string, { content_hash: string; fetched_at: string }> | null }>(`/api/briefs/${b.name}`)
      .then((d) => { if (d.evidence) setEvidence(d.evidence); })
      .catch(() => {});
  }, []);
  const loadedFirst = React.useRef(false);
  React.useEffect(() => {
    if (!briefs?.length || loadedFirst.current) return;
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("from") === "who") return;
    loadedFirst.current = true;
    loadBrief(briefs.find((x) => x.name === "protein_water") ?? briefs[0]);
  }, [briefs, loadBrief]);
  // Arriving from Who you study: audiences, assumptions, sources and study size, with the ontology version it saved.
  const appliedWho = React.useRef(false);
  React.useEffect(() => {
    if (appliedWho.current || typeof window === "undefined") return;
    if (!new URLSearchParams(window.location.search).get("from")) return;
    let handoff: {
      audiences?: { name: string; share: number | null; attribute_filters: Record<string, string | string[]> }[];
      assumptions?: { text: string; source: string }[];
      sources?: string[]; studySize?: number; category?: string; ontologyVersion?: string;
    } | null = null;
    try {
      handoff = JSON.parse(localStorage.getItem("who-launch") ?? "null");
    } catch { handoff = null; }
    if (!handoff) return;
    appliedWho.current = true;
    setForm((f) => ({
      ...f,
      product: { ...f.product, category: handoff.category ?? f.product.category },
      ontologyVersion: handoff.ontologyVersion ?? f.ontologyVersion,
      audiences: (handoff.audiences ?? []).map((a) => ({
        name: a.name,
        share: a.share === null || a.share === undefined ? "" : String(a.share),
        filters: Object.fromEntries(Object.entries(a.attribute_filters ?? {}).map(([k, v]) => [
          k, Array.isArray(v) ? { kind: "one_of" as const, values: v.map(String) } : { kind: "exactly" as const, value: String(v) },
        ])),
      })),
      assumptions: (handoff.assumptions ?? []).map((a) => ({ text: a.text, source: "assumed" as const })),
    }));
    if (handoff.sources) setSources(handoff.sources);
    if (handoff.studySize) setN(String(handoff.studySize));
  }, []);
  // A brief names one exact ontology version, and the form says which: the version the brief
  // was loaded with, or the one picked here — never a silent substitution of the newest.
  React.useEffect(() => {
    if (!form.product.category) {
      if (ontoList.length) setForm((f) => ({ ...f, product: { ...f.product, category: ontoList[0].category }, ontologyVersion: ontoList[0].version }));
      return;
    }
    let live = true;
    api<CategoryOntology>(
      `/api/ontologies?category=${encodeURIComponent(form.product.category)}&version=${encodeURIComponent(form.ontologyVersion)}`,
    ).then((o) => { if (live) setOnto(o); }).catch(() => { if (live) setOnto(null); });
    return () => { live = false; };
  }, [form.product.category, form.ontologyVersion, ontoList]);

  const briefYaml = React.useMemo(() => briefToYaml(form), [form]);
  const realNeedsEndpoint = mode === "real" && endpoint?.endpoint_configured === false;
  const studyForm: StudyForm = {
    mode, n, horizon, tickUnit, seeds, budget, channel, elicits, anchorVersion, model, embedModel,
    populationSeed, shards, sources, priceChatIn, priceChatOut, priceEmbedIn, validation,
  };
  const mistakes = problems(studyForm);
  const chosenAnchor = anchors?.anchors.find((a) => `${a.construct}=${a.version}` === anchorVersion);
  const anchorMismatch = mode === "real" && !!chosenAnchor?.embed_model_id && !!embedModel.trim() && chosenAnchor.embed_model_id !== embedModel.trim();
  const toggle = (list: string[], set: (v: string[]) => void, value: string) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value].sort());

  const post = <T,>(path: string, body: unknown) => api<T>(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });

  const runGate = async () => {
    setGating(true);
    setGate(null);
    try {
      setGate(await post<GateResult>("/api/gate", gateRequest(studyForm, briefYaml, evidence)));
    } catch (e) {
      setGate({ code: 1, run_id: null, refusal: whyNot(e), gate: null, manifest: null });
    }
    setGating(false);
  };

  const launchStudy = async () => {
    setLaunching(true);
    setLaunched(null);
    try {
      // Model pins, the corpus a draw reads, its seed and what the models cost are study inputs — recorded and
      // hashed. The endpoint and the key are the server's environment and are never asked for here.
      const r = await post<{ run_id: string }>("/api/runs", studyRequest(studyForm, briefYaml, evidence));
      setLaunched({ run_id: r.run_id });
    } catch (e) {
      setLaunched({ error: whyNot(e) });
    }
    setLaunching(false);
  };

  const checkBrief = async () => {
    setCheckingBrief(true);
    setLedger(null);
    setLedgerError(null);
    try {
      setLedger(await post("/api/briefs/validate", { brief_yaml: briefYaml, evidence_json: evidence }));
    } catch (e) {
      setLedgerError(whyNot(e));
    }
    setCheckingBrief(false);
  };

  const setClaim = (i: number, patch: Partial<BriefForm["claims"][number]>) =>
    setForm((f) => ({ ...f, claims: f.claims.map((x, j) => (j === i ? { ...x, ...patch } : x)) }));
  const setCompetitor = (i: number, patch: Partial<BriefForm["competitors"][number]>) =>
    setForm((f) => ({ ...f, competitors: f.competitors.map((x, j) => (j === i ? { ...x, ...patch } : x)) }));
  const setAssumption = (i: number, patch: Partial<BriefForm["assumptions"][number]>) =>
    setForm((f) => ({ ...f, assumptions: f.assumptions.map((x, j) => (j === i ? { ...x, ...patch } : x)) }));

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
              {briefs && briefs.length > 0 && (
                <div className="field" style={{ marginBottom: 12 }}>
                  <label>Start from a brief the engine already holds</label>
                  <select className="input mono" aria-label="Start from a brief" defaultValue="" onChange={(e) => {
                    const chosen = briefs.find((b) => b.name === e.target.value);
                    if (chosen) loadBrief(chosen);
                  }}>
                    <option value="">— author one below, or choose —</option>
                    {briefs.map((b) => <option key={b.name} value={b.name}>{b.name} — {b.brief.product.name}</option>)}
                  </select>
                  <div className="help">Loading replaces the form. Nothing is written until you launch: the brief you see below is what the study is run on.</div>
                </div>
              )}
              <div className="grid g2">
                <div className="field"><label>Product name</label><input className="input" value={form.product.name} onChange={(e) => setProduct({ name: e.target.value })} /></div>
                <div className="field"><label>Category (ontology)</label>
                  <select
                    className="input"
                    value={`${form.product.category}@${form.ontologyVersion}`}
                    onChange={(e) => {
                      const [category, version] = e.target.value.split("@");
                      setForm((f) => ({ ...f, product: { ...f.product, category }, ontologyVersion: version }));
                    }}
                  >
                    {!ontoList.some((o) => o.category === form.product.category && o.version === form.ontologyVersion) && form.product.category && (
                      <option value={`${form.product.category}@${form.ontologyVersion}`}>{form.product.category} @ {form.ontologyVersion} (not held here)</option>
                    )}
                    {ontoList.map((o) => <option key={`${o.category}@${o.version}`} value={`${o.category}@${o.version}`}>{o.category} @ {o.version}</option>)}
                  </select>
                  <div className="help"><Link href="/who">Describe who you study →</Link> what can be studied is bounded by the corpus, not by which files exist.</div></div>
              </div>
              <div className="field"><label>Concept statement</label>
                <textarea className="input" rows={2} value={form.product.description} onChange={(e) => setProduct({ description: e.target.value })} />
                <div className="help">Shown to personas verbatim. {onto && <>Conditioning set: <span className="mono">{onto.conditioning_set.join(", ")}</span></>}</div>
              </div>
              <div className="field"><label>Claims <span style={{ fontWeight: 400, color: "var(--ink-3)" }}>(C1… auto-numbered; public_source needs an evidence URL)</span></label>
                <div className="help">A <b>claim</b> is one assertion about the product — the atomic unit of stimulus: posts, feed cards and findings all reference it.</div>
                <div style={{ display: "grid", gap: 8 }}>
                  {form.claims.map((c, i) => (
                    <div key={i} style={{ display: "grid", gap: 6, border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span className="mono" style={{ color: "var(--ink-3)" }}>C{i + 1}</span>
                        <input className="input" value={c.text} style={{ flex: 1 }} onChange={(e) => setClaim(i, { text: e.target.value })} />
                        <select className="input" style={{ width: 140 }} value={c.source} onChange={(e) => setClaim(i, { source: e.target.value as ClaimSource })}>
                          <option value="user_asserted">user_asserted</option>
                          <option value="public_source">public_source</option>
                          <option value="assumed">assumed</option>
                        </select>
                        <button className="btn quiet sm" onClick={() => setForm((f) => ({ ...f, claims: f.claims.filter((_, j) => j !== i) }))}>✕</button>
                      </div>
                      {c.source === "public_source" && (
                        <>
                          <input className="input mono" placeholder="evidence_url — required for public_source" value={c.evidence_url} onChange={(e) => setClaim(i, { evidence_url: e.target.value })} />
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
                  <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, claims: [...f.claims, { text: "", source: "assumed", evidence_url: "" }] }))}>+ Add claim</button>
                </div>
              </div>
              <div className="grid g2">
                <div className="field"><label>Price</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="input mono" value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))} />
                    <input className="input mono" style={{ width: 80 }} aria-label="currency" value={form.currency} onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value.toUpperCase() }))} />
                  </div></div>
                <div className="field"><label>Target market</label><input className="input" value={form.target} onChange={(e) => setForm((f) => ({ ...f, target: e.target.value }))} /></div>
              </div>
              <div className="field"><label>Competitors <span style={{ fontWeight: 400, color: "var(--ink-3)" }}>(what the population weighs the product against)</span></label>
                <div style={{ display: "grid", gap: 8 }}>
                  {form.competitors.map((c, i) => (
                    <div key={i} style={{ display: "grid", gap: 6, border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                      <div style={{ display: "flex", gap: 8 }}>
                        <input className="input" placeholder="name" value={c.name} style={{ flex: 1 }} onChange={(e) => setCompetitor(i, { name: e.target.value })} />
                        <input className="input mono" placeholder="price" style={{ width: 90 }} value={c.price} onChange={(e) => setCompetitor(i, { price: e.target.value })} />
                        <input className="input mono" placeholder={form.currency || "USD"} aria-label="competitor currency" style={{ width: 70 }} value={c.currency} onChange={(e) => setCompetitor(i, { currency: e.target.value.toUpperCase() })} />
                        <button className="btn quiet sm" onClick={() => setForm((f) => ({ ...f, competitors: f.competitors.filter((_, j) => j !== i) }))}>✕</button>
                      </div>
                      <textarea className="input" rows={2} placeholder="what it claims — one per line" value={c.claims} onChange={(e) => setCompetitor(i, { claims: e.target.value })} />
                    </div>
                  ))}
                  <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, competitors: [...f.competitors, { name: "", price: "", currency: "", claims: "" }] }))}>+ Add competitor</button>
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>2 · Audiences</h2><span className="hint">named slices of the target market — authored in Who you study</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              {form.audiences.map((a, i) => (
                <div key={i} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <b className="mono">{a.name}</b>
                    <span className="mono sub" style={{ fontSize: 11 }}>share {a.share === "" ? "—" : a.share}</span>
                  </div>
                  <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>
                    {Object.entries(a.filters).map(([k, f]) => `${k} ${f.kind === "exactly" ? `= ${f.value}` : f.kind === "one_of" ? `in (${f.values.join(", ")})` : `from ${f.first} to ${f.last}`}`).join(" · ") || "no filters"}
                  </div>
                </div>
              ))}
              <div className="help"><Link href="/who">Author audiences in Who you study →</Link> filters are picked from value lists with live counts, never typed.</div>
              <div className="field"><label>Assumptions</label>
                <div className="help">An <b>assumption</b> is taken as true without evidence — recorded and surfaced in every report, never resolved away. Each keeps the source it was stated with.</div>
                <div style={{ display: "grid", gap: 6 }}>
                  {form.assumptions.map((a, i) => (
                    <div key={i} style={{ display: "flex", gap: 8 }}>
                      <input className="input" style={{ flex: 1 }} value={a.text} onChange={(e) => setAssumption(i, { text: e.target.value })} />
                      <select className="input" style={{ width: 140 }} value={a.source} onChange={(e) => setAssumption(i, { source: e.target.value as ClaimSource })}>
                        <option value="user_asserted">user_asserted</option>
                        <option value="assumed">assumed</option>
                      </select>
                      <button className="btn quiet sm" onClick={() => setForm((f) => ({ ...f, assumptions: f.assumptions.filter((_, j) => j !== i) }))}>✕</button>
                    </div>
                  ))}
                  <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, assumptions: [...f.assumptions, { text: "", source: "assumed" }] }))}>+ Add assumption</button>
                </div>
              </div>
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
            <div className="panel-head"><h2>Population gate</h2><span className="hint">{mode === "fake" ? "coreset-gate · fake corpus · no spend" : "coreset-gate · your real corpus · a few model calls at most"}</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="field" style={{ margin: 0 }}><label>n personas</label><input className="input mono" value={n} onChange={(e) => setN(e.target.value)} /></div>
              <button className="btn primary" disabled={gating || realNeedsEndpoint || mistakes.length > 0} onClick={runGate}>{gating ? "Gating…" : <>Run gate {ICONS.arrow}</>}</button>
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
                    {gate.manifest && <p className="sub mono" style={{ color: "var(--ink-3)" }}>{gate.manifest.persona_ids.length} personas · synthesized {(gate.manifest.synthesized_share * 100).toFixed(1)}% · kept with the run</p>}
                    {gate.run_id && <Link className="btn sm" href={`/population?run=${gate.run_id}`}>Open gate report {ICONS.arrow}</Link>}
                  </>
                ) : (
                  <Callout icon="alert"><div><b>The gate could not draw this population (exit {gate.code}).</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{gate.refusal}</pre></div></Callout>
                )
              )}
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>A failing draw exits 2 with its gate report — a doomed study costs nothing. A failed gate stays readable on the population page.</p>
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><h2>Launch study</h2><span className="hint">{mode === "fake" ? "fake first — no key, no corpus, no network" : "a real study, on the server's endpoint"}</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="field" style={{ margin: 0 }}><label>Kind of study</label>
                <select className="input" value={mode} onChange={(e) => setMode(e.target.value as "fake" | "real")}>
                  <option value="fake">fake — deterministic stand-ins, marked as fake everywhere</option>
                  <option value="real">real — asks the models named below</option>
                </select>
                {mode === "real" && (
                  <div className="help">{endpoint?.endpoint_configured
                    ? "The endpoint and its key are the server's environment. This form never asks for either."
                    : <b>No endpoint is configured where the server runs — set SIMCORE_INFERENCE_BASE_URL (and its key) in its environment, then restart it. A key is never typed into a browser.</b>}</div>
                )}
              </div>
              {mode === "real" && (
                <div className="grid g2">
                  <div className="field" style={{ margin: 0 }}><label>Chat model (pinned)</label><input className="input mono" value={model} placeholder="model id" onChange={(e) => setModel(e.target.value)} /></div>
                  <div className="field" style={{ margin: 0 }}><label>Embedding model (pinned)</label><input className="input mono" value={embedModel} placeholder="model id" onChange={(e) => setEmbedModel(e.target.value)} />
                    <div className="help">Pins are study inputs — recorded, hashed, and fixed for the whole run.</div></div>
                </div>
              )}
              {mode === "real" && (
                <div style={{ display: "grid", gap: 10 }}>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Draw from these shards</label>
                    {!corpus?.available
                      ? <div className="help"><b>No corpus is cached where the server runs.</b> A real study draws real personas; fetch the release first, or run a fake study.</div>
                      : <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                          {corpus.shards.map((sh) => (
                            <label key={sh.id} className="mono" style={{ fontSize: 12, opacity: sh.cached ? 1 : 0.45 }} title={sh.cached ? "" : "not cached on this machine"}>
                              <input type="checkbox" disabled={!sh.cached} checked={shards.includes(sh.id)} onChange={() => toggle(shards, setShards, sh.id)} /> {sh.id}{sh.rows ? ` · ${sh.rows.toLocaleString()}` : ""}{sh.cached ? "" : " · not cached"}
                            </label>
                          ))}
                        </div>}
                    <div className="help">Named explicitly, so the draw does not depend on which machine it ran on.</div>
                  </div>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Admit these persona sources</label>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                      {(corpus?.measured_sources ?? []).map((src) => (
                        <label key={src} className="mono" style={{ fontSize: 12 }}>
                          <input type="checkbox" checked={sources.includes(src)} onChange={() => toggle(sources, setSources, src)} /> {src}{corpus?.sources[src] ? ` · ${corpus.sources[src].toLocaleString()}` : ""}
                        </label>
                      ))}
                    </div>
                    <div className="help">Synthetic rows are left out on purpose: a persona may not have synthesized demographics, so a draw that reaches them is refused after it is built. Which sources dominate a draw decides who your personas really are — the gate report shows the mix.</div>
                  </div>
                  <div className="grid g2">
                    <div className="field" style={{ margin: 0 }}><label>Population seed</label><input className="input mono" value={populationSeed} onChange={(e) => setPopulationSeed(e.target.value)} />
                      <div className="help">Which persona draw. A draw the gate refuses is a draw refused — re-draw with another seed and say you did.</div></div>
                    <div className="field" style={{ margin: 0 }}><label>Environment</label>
                      <select className="input" value={channel} onChange={(e) => setChannel(e.target.value as ChannelName)}>
                        {CHANNELS.map((c) => <option key={c} value={c}>{c} — {CHANNEL_GUIDE[c].summary}</option>)}
                      </select>
                      <div className="help">{CHANNEL_GUIDE[channel].use} <i>{ONE_ENVIRONMENT_NOTE}</i></div></div>
                  </div>
                  <div className="field" style={{ margin: 0 }}>
                    <label>What the models cost (USD per million tokens) — optional</label>
                    <div className="grid g2">
                      <input className="input mono" value={priceChatIn} placeholder="chat input, e.g. 0.035" onChange={(e) => setPriceChatIn(e.target.value)} />
                      <input className="input mono" value={priceChatOut} placeholder="chat output, e.g. 0.14" onChange={(e) => setPriceChatOut(e.target.value)} />
                    </div>
                    <input className="input mono" style={{ marginTop: 6 }} value={priceEmbedIn} placeholder="embedding input, e.g. 0.02" onChange={(e) => setPriceEmbedIn(e.target.value)} />
                    <div className="help">Prices are what let the budget ladder measure spend. Without them a cost the gateway does not quote stays unknown, and a run where nothing is priced stops rather than spend blind.</div>
                  </div>
                </div>
              )}
              {mode === "fake" && (
                <div className="field" style={{ margin: 0 }}><label>Environment</label>
                  <select className="input" value={channel} onChange={(e) => setChannel(e.target.value as ChannelName)}>
                    {CHANNELS.map((c) => <option key={c} value={c}>{c} — {CHANNEL_GUIDE[c].summary}</option>)}
                  </select>
                  <div className="help">{CHANNEL_GUIDE[channel].use} <i>{ONE_ENVIRONMENT_NOTE}</i></div></div>
              )}
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Horizon (ticks)</label><input className="input mono" value={horizon} onChange={(e) => setHorizon(e.target.value)} /></div>
                <div className="field" style={{ margin: 0 }}><label>Tick unit</label>
                  <select className="input" value={tickUnit} onChange={(e) => setTickUnit(e.target.value)}>
                    <option value="hour">hour</option><option value="day">day</option><option value="week">week</option>
                  </select></div>
              </div>
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Replicate seeds</label><input className="input mono" value={seeds} onChange={(e) => setSeeds(e.target.value)} />
                  <div className="help">Comma-separated. More than one is what says whether an ordering survives.</div></div>
                <div className="field" style={{ margin: 0 }}><label>Budget (USD)</label><input className="input mono" value={budget} onChange={(e) => setBudget(e.target.value)} /></div>
              </div>
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Asked — what personas answer</label>
                  <select className="input" value={elicits} onChange={(e) => setElicits(e.target.value)}>
                    <option value="reaction">reaction</option>
                    <option value="purchase">purchase intent</option>
                  </select>
                  <div className="help">A purchase-intent study is scored by the anchor version below.</div></div>
                <div className="field" style={{ margin: 0 }}><label>Anchor version</label>
                  {anchors && anchors.anchors.length > 0
                    ? <select className="input mono" value={anchorVersion} onChange={(e) => setAnchorVersion(e.target.value)}>
                        {anchors.anchors.map((a) => {
                          const value = `${a.construct}=${a.version}`;
                          return <option key={value} value={value}>{value} — {a.passed ? "passed its check" : a.checked ? "FAILED its check" : "never checked"}</option>;
                        })}
                      </select>
                    : <input className="input mono" value={anchorVersion} onChange={(e) => setAnchorVersion(e.target.value)} />}
                  {chosenAnchor && !chosenAnchor.passed && <div className="help"><b>This version did not pass its check, so nothing will be scored against it.</b> {chosenAnchor.detail}</div>}
                  {chosenAnchor?.passed && chosenAnchor.unchanged_since_check === false && <div className="help"><b>This file changed after its check passed:</b> a changed statement is a new version, so it will not be pinned.</div>}
                  {anchorMismatch && <div className="help"><b>It was checked against {chosenAnchor?.embed_model_id}, not {embedModel.trim()}.</b> A check is evidence about one embedding model, so it will not score with another.</div>}
                </div>
              </div>
              <div className="field" style={{ margin: 0 }}><label>Recommended real-world validation — optional</label>
                <input className="input" value={validation} placeholder="e.g. Interview twenty parents before building anything." onChange={(e) => setValidation(e.target.value)} />
                <div className="help">Printed last in the report: what a reader should do to check this against real people.</div></div>
              {mistakes.length > 0 && <Callout icon="alert"><div><b>Before this can start:</b><ul style={{ margin: "6px 0 0 16px" }}>{mistakes.map((m) => <li key={m}>{m}</li>)}</ul></div></Callout>}
              <button className="btn primary" disabled={launching || realNeedsEndpoint || mistakes.length > 0} onClick={launchStudy}>{launching ? "Launching…" : <>Run {mode} study {ICONS.arrow}</>}</button>
              {launched?.run_id && <Link className="btn sm" href={`/run?run=${launched.run_id}`}>Watch {launched.run_id} {ICONS.arrow}</Link>}
              {launched?.error && <Callout icon="alert"><div><b>Launch refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{launched.error}</pre></div></Callout>}
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>Runs as a subprocess under the same id a resume reuses, and writes the same artefacts the command line does. A fake study is marked as fake in every view of it.</p>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
