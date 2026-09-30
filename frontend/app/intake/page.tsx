"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { useSessionState } from "@/lib/session";
import { PageHead, Callout, ICONS } from "@/components/ui";
import { api, useApi, whyNot } from "@/lib/api";
import { briefToYaml, type BriefForm } from "@/lib/briefYaml";
import type { AudienceSet, CategoryOntology, ClaimSource } from "@/lib/engine";
import {
  CHANNELS, CHANNEL_GUIDE, defaultAnchor, defaultSources, gateRequest, leftOut, problems, shardsFor, studyRequest, womAlone, DEFAULT_RECSYS_MODEL,
  type AnchorCatalogue, type ChannelName, type CorpusInfo, type StudyForm,
} from "@/lib/study";
import { TEXT_SOURCES } from "@/lib/sources";

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
  audiences: [],
  assumptions: [],
  ontologyVersion: "",
};

export default function IntakePage() {
  const [onto, setOnto] = React.useState<CategoryOntology | null>(null);

  // The brief, as the form holds it. Nothing about it lives anywhere else: the YAML below is
  // this state written out, and it is what the engine's intake reads.
  const [form, setForm] = useSessionState<BriefForm>("intake:form", BLANK);
  const setProduct = (patch: Partial<BriefForm["product"]>) => setForm((f) => ({ ...f, product: { ...f.product, ...patch } }));
  const [evidence, setEvidence] = useSessionState<Record<string, { content_hash: string; fetched_at: string }>>("intake:evidence", {});

  // The study: what is run, not what is said about the product.
  const [n, setN] = useSessionState("intake:n", "200");
  const [horizon, setHorizon] = useSessionState("intake:horizon", "4");
  const [tickUnit, setTickUnit] = useSessionState("intake:tickUnit", "day");
  const [seeds, setSeeds] = useSessionState("intake:seeds", "4021");
  const [budget, setBudget] = useSessionState("intake:budget", "20");
  const [anchorVersion, setAnchorVersion] = useSessionState("intake:anchorVersion", "");
  const [model, setModel] = useSessionState("intake:model", "");
  const [embedModel, setEmbedModel] = useSessionState("intake:embedModel", "");
  // What a real study also decides: where the population is drawn from, which draw, and what the models cost.
  // Defaults come from what is actually there — the cached shards, the measured sources, a scale that passed.
  // Which channels spread information, when intent is measured, and — for word of mouth alone —
  // the launch reach. No channels ticked is the concept test: every persona sees the concept alone.
  const [channels, setChannels] = useSessionState<ChannelName[]>("intake:channels", []);
  const [surveyEvery, setSurveyEvery] = useSessionState("intake:surveyEvery", "1");
  const [launchReach, setLaunchReach] = useSessionState("intake:launchReach", "0.10");
  // The feed ranks like X by its own model, TwHIN-BERT served beside the gateway.
  const [recsysEmbedModel, setRecsysEmbedModel] = useSessionState("intake:recsysEmbedModel", DEFAULT_RECSYS_MODEL);
  const [populationSeed, setPopulationSeed] = useSessionState("intake:populationSeed", "4021");
  const [shards, setShards] = useSessionState<string[]>("intake:shards", []);
  const [sources, setSources] = useSessionState<string[]>("intake:sources", []);
  const [priceChatIn, setPriceChatIn] = useSessionState("intake:priceChatIn", "");
  const [priceChatOut, setPriceChatOut] = useSessionState("intake:priceChatOut", "");
  const [priceEmbedIn, setPriceEmbedIn] = useSessionState("intake:priceEmbedIn", "");
  const [validation, setValidation] = useSessionState("intake:validation", "");
  const { data: corpus } = useApi<CorpusInfo>("/api/corpus");
  const { data: anchors } = useApi<AnchorCatalogue>("/api/anchors");
  React.useEffect(() => {
    // Defaults only fill an empty choice: an audience set's sources, or ones kept from earlier in this tab, stay.
    if (corpus) setSources((s) => (s.length ? s : defaultSources(corpus)));
  }, [corpus]);
  // The shards are the ones the chosen sources' people are in, until the person picks them by hand.
  const [shardsByHand, setShardsByHand] = useSessionState("intake:shardsByHand", false);
  React.useEffect(() => {
    if (corpus && !shardsByHand) setShards(shardsFor(corpus, sources));
  }, [corpus, sources, shardsByHand, setShards]);
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
  const { data: endpoint } = useApi<{ endpoint_configured: boolean }>("/api/status");

  // Who is studied comes from an audience set Who you study saved: its audiences, assumptions, sources and
  // study size, together with the one ontology version they were drafted against — never the ontology alone.
  const { data: sets } = useApi<{ audience_sets: AudienceSet[] }>("/api/audience-sets");
  const [chosenSet, setChosenSet] = useSessionState("intake:chosenSet", "");
  const applySet = React.useCallback((set: AudienceSet) => {
    setChosenSet(`${set.category}/${set.id}`);
    setForm((f) => ({
      ...f,
      product: { ...f.product, category: set.category },
      ontologyVersion: set.ontology_version,
      audiences: set.audiences.map((a) => ({
        name: a.name,
        share: a.share === null || a.share === undefined ? "" : String(a.share),
        filters: Object.fromEntries(Object.entries(a.attribute_filters ?? {}).map(([k, v]) => [
          k, Array.isArray(v) ? { kind: "one_of" as const, values: v.map(String) } : { kind: "exactly" as const, value: String(v) },
        ])),
      })),
      assumptions: set.assumptions.map((a) => ({ text: a.text, source: "assumed" as const })),
    }));
    setSources(set.sources);
    setN(String(set.study_size));
  }, []);
  React.useEffect(() => {
    if (chosenSet || !sets) return;
    const ref = new URLSearchParams(window.location.search).get("set");
    const named = sets.audience_sets.find((x) => `${x.category}/${x.id}` === ref);
    if (named) applySet(named);
  }, [sets, chosenSet, applySet]);
  // A brief names one exact ontology version: the one Who you study drafted its audiences against.
  React.useEffect(() => {
    if (!form.product.category) return;
    let live = true;
    api<CategoryOntology>(
      `/api/ontologies?category=${encodeURIComponent(form.product.category)}&version=${encodeURIComponent(form.ontologyVersion)}`,
    ).then((o) => { if (live) setOnto(o); }).catch(() => { if (live) setOnto(null); });
    return () => { live = false; };
  }, [form.product.category, form.ontologyVersion]);

  const briefYaml = React.useMemo(() => briefToYaml(form), [form]);
  const realNeedsEndpoint = endpoint?.endpoint_configured === false;
  const studyForm: StudyForm = {
    n, horizon, tickUnit, seeds, budget, channels, surveyEvery, launchReach, recsysEmbedModel, anchorVersion, model, embedModel,
    populationSeed, shards, sources, priceChatIn, priceChatOut, priceEmbedIn, validation,
  };
  const wordOfMouthAlone = womAlone(channels);
  const feedTicked = channels.includes("social_feed");
  // The wave ticks and the answers they take are the engine's to derive (ADR 0045); the page asks.
  const [wavePlan, setWavePlan] = React.useState<{ ticks: number[]; answers: number } | null>(null);
  React.useEffect(() => {
    const body = { survey_every: Number(surveyEvery), horizon: Number(horizon), n: Number(n), replicates: seeds.split(",").filter((x) => x.trim()).length || 1 };
    let live = true;
    setWavePlan(null);
    api<{ ticks: number[]; answers: number }>("/api/waves", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then((plan) => { if (live) setWavePlan(plan); })
      .catch(() => { if (live) setWavePlan(null); });
    return () => { live = false; };
  }, [surveyEvery, horizon, n, seeds]);
  // Whether the feed's ranking model answers — asked of the engine, which holds the key.
  const [recsysCheck, setRecsysCheck] = React.useState<{ model: string; reachable: boolean; detail: string | null } | null>(null);
  React.useEffect(() => {
    const model = recsysEmbedModel.trim();
    setRecsysCheck(null);
    if (!feedTicked || !model) return;
    let live = true;
    const timer = setTimeout(() => {
      api<{ model: string; reachable: boolean; detail: string | null }>("/api/recsys/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) })
        .then((result) => { if (live) setRecsysCheck(result); })
        .catch((e) => { if (live) setRecsysCheck({ model, reachable: false, detail: whyNot(e) }); });
    }, 400);
    return () => { live = false; clearTimeout(timer); };
  }, [feedTicked, recsysEmbedModel]);
  // Who is studied comes only from Who you study: without its audiences there is nothing to draw.
  const mistakes = [
    ...(form.audiences.length ? [] : ["Choose an audience set — Who you study saves them."]),
    ...problems(studyForm),
    ...(feedTicked && recsysCheck && !recsysCheck.reachable
      ? [`The feed's ranking model ${recsysCheck.model} does not answer: ${recsysCheck.detail} — start tools/twhin_server.py and its gateway entry (RUN.md), or untick the feed.`]
      : []),
  ];
  const chosenAnchor = anchors?.anchors.find((a) => `${a.construct}=${a.version}` === anchorVersion);
  const anchorMismatch = !!chosenAnchor?.embed_model_id && !!embedModel.trim() && chosenAnchor.embed_model_id !== embedModel.trim();
  const toggle = <T extends string,>(list: T[], set: (v: T[]) => void, value: T) =>
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
        actions={<>{endpoint && <span className={`chip ${endpoint.endpoint_configured ? "ok" : "plain"}`} title="The server's environment configures the endpoint — never the browser"><span className="dot" />{endpoint.endpoint_configured ? "endpoint configured" : "no endpoint — studies cannot run"}</span>}<span className="chip plain mono">brief YAML · validated by intake</span></>}
      />
      <div className="grid g-32">
        <div>
          <div className="panel">
            <div className="panel-head"><h2>1 · Product brief</h2><span className="hint">what the population will see</span></div>
            <div className="panel-body">
              <div className="grid g2">
                <div className="field"><label>Product name</label><input className="input" value={form.product.name} onChange={(e) => setProduct({ name: e.target.value })} /></div>
                <div className="field"><label>Audience set</label>
                  <select className="input" aria-label="Audience set" value={chosenSet} onChange={(e) => {
                    const picked = sets?.audience_sets.find((x) => `${x.category}/${x.id}` === e.target.value);
                    if (picked) applySet(picked);
                  }}>
                    <option value="" disabled>{sets?.audience_sets.length ? "choose one…" : "none saved yet"}</option>
                    {(sets?.audience_sets ?? []).map((x) => (
                      <option key={`${x.category}/${x.id}`} value={`${x.category}/${x.id}`}>{x.name} — {x.category} {x.ontology_version} · {x.created_at.slice(0, 10)}</option>
                    ))}
                  </select>
                  <div className="help">
                    {form.product.category && <>Category (ontology) <span className="mono">{form.product.category} @ {form.ontologyVersion}</span>, chosen with its audiences. </>}
                    <Link href={chosenSet ? `/who?set=${chosenSet}` : "/who"}>{chosenSet ? "Change them in Who you study →" : "Make one in Who you study →"}</Link>
                  </div></div>
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
              {form.audiences.length === 0 && (
                <div className="empty"><b>No audience set chosen.</b>Choose one above, or <Link href="/who">make one in Who you study →</Link> The study cannot start without one.</div>
              )}
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
            <div className="panel-head"><h2>Population gate</h2><span className="hint">coreset-gate · your real corpus · a few model calls at most</span></div>
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
                    {gate.gate.overall && !gate.manifest && (
                      <Callout icon="alert"><div><b>Every check passed, but the population was not built.</b>
                        <pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{gate.refusal ?? "No reason was given."}</pre></div></Callout>
                    )}
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
            <div className="panel-head"><h2>Launch study</h2><span className="hint">on the server&apos;s endpoint, with the models named below</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="help" style={{ marginTop: 0 }}>{endpoint?.endpoint_configured
                ? "The endpoint and its key are the server's environment. This form never asks for either."
                : <b>No endpoint is configured where the server runs — set SIMCORE_INFERENCE_BASE_URL (and its key) in its environment, then restart it. A key is never typed into a browser.</b>}</div>
                <div className="grid g2">
                  <div className="field" style={{ margin: 0 }}><label>Chat model (pinned)</label><input className="input mono" value={model} placeholder="model id" onChange={(e) => setModel(e.target.value)} /></div>
                  <div className="field" style={{ margin: 0 }}><label>Embedding model (pinned)</label><input className="input mono" value={embedModel} placeholder="model id" onChange={(e) => setEmbedModel(e.target.value)} />
                    <div className="help">Pins are study inputs — recorded, hashed, and fixed for the whole run.</div></div>
                </div>
                <div style={{ display: "grid", gap: 10 }}>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Draw from these shards</label>
                    {!corpus?.available
                      ? <div className="help"><b>No corpus is cached where the server runs.</b> A study draws real personas; fetch the release first.</div>
                      : <ShardPicker corpus={corpus} shards={shards} sources={sources}
                          onToggle={(id) => { setShardsByHand(true); toggle(shards, setShards, id); }}
                          onFollowSources={() => { setShardsByHand(false); setShards(shardsFor(corpus, sources)); }} />}
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
                    <div className="field" style={{ margin: 0 }}><label>Channels — what spreads information</label>
                      <div style={{ display: "grid", gap: 4 }}>
                        {CHANNELS.map((c) => (
                          <label key={c} style={{ fontSize: 13 }}>
                            <input type="checkbox" checked={channels.includes(c)} onChange={() => toggle(channels, setChannels, c)} /> <span className="mono">{c}</span> — {CHANNEL_GUIDE[c].summary}
                          </label>
                        ))}
                      </div>
                      <div className="help">{channels.length === 0
                        ? "Concept test — every persona sees the concept alone."
                        : channels.map((c) => CHANNEL_GUIDE[c].use).join(" ")}</div></div>
                  </div>
                  {feedTicked && (
                    <div className="field" style={{ margin: 0 }}><label>Feed ranking model</label>
                      <input className="input mono" value={recsysEmbedModel} onChange={(e) => setRecsysEmbedModel(e.target.value)} />
                      <div className="help">The feed ranks like X — posts from ties and follows first, then interest × recency — with TwHIN-BERT, served on this machine beside the gateway. {recsysCheck === null
                        ? "Checking it answers…"
                        : recsysCheck.reachable ? <b>It answers.</b> : <b>It does not answer: {recsysCheck.detail}</b>}</div></div>
                  )}
                  <div className="grid g2">
                    <div className="field" style={{ margin: 0 }}><label>Survey every k ticks</label>
                      <input className="input mono" value={surveyEvery} onChange={(e) => setSurveyEvery(e.target.value)} />
                      <div className="help">{wavePlan
                        ? <>Waves at ticks <span className="mono">{wavePlan.ticks.join(", ")}</span> — every persona answers the purchase-intent question: <b>{wavePlan.answers.toLocaleString()} answers</b>, one chat call and one embedding each. The budget never thins a wave; a study pauses before one it cannot afford.</>
                        : "How often every persona is surveyed for purchase intent."}</div></div>
                    {wordOfMouthAlone && (
                      <div className="field" style={{ margin: 0 }}><label>Launch reach</label>
                        <input className="input mono" value={launchReach} onChange={(e) => setLaunchReach(e.target.value)} />
                        <div className="help">The share of personas who hear first-hand at launch, chosen at random — without them nobody has anything to pass on.</div></div>
                    )}
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
              <button className="btn primary" disabled={launching || realNeedsEndpoint || mistakes.length > 0} onClick={launchStudy}>{launching ? "Launching…" : <>Run study {ICONS.arrow}</>}</button>
              {launched?.run_id && <Link className="btn sm" href={`/run?run=${launched.run_id}`}>Watch {launched.run_id} {ICONS.arrow}</Link>}
              {launched?.error && <Callout icon="alert"><div><b>Launch refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{launched.error}</pre></div></Callout>}
              <p className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>Runs as a subprocess under the same id a resume reuses, and writes the same artefacts the command line does.</p>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}


/* Each shard as the people in it, not a file number: which sources it holds and how many, whether they were
   surveyed, read from text by a model, or synthetic and never drawn. */
function ShardPicker({ corpus, shards, sources, onToggle, onFollowSources }: {
  corpus: CorpusInfo; shards: string[]; sources: string[]; onToggle: (id: string) => void; onFollowSources: () => void;
}) {
  const needed = shardsFor(corpus, sources);
  const following = needed.length === shards.length && needed.every((id) => shards.includes(id));
  const missing = Object.entries(leftOut(corpus, shards, sources));
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div className="help" style={{ marginTop: 0 }}>
        {sources.length === 0 ? "Choose the sources to admit below; the shards follow them."
          : needed.length ? <>Your sources&apos; people are in <b className="mono">{needed.join(", ")}</b>.{!following && <> <button className="btn sm" onClick={onFollowSources}>Use exactly those</button></>}</>
          : "None of your sources is in a cached shard."}
      </div>
      {missing.length > 0 && (
        <div className="help" style={{ color: "var(--risk)", marginTop: 0 }}>
          Unticked shards leave out {missing.map(([src, n]) => `${n.toLocaleString()} ${src}`).join(" and ")} — they can never be drawn.
        </div>
      )}
      <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)" }}>
        {corpus.shards.map((sh, i) => {
          const held = Object.entries(sh.sources ?? {});
          const synthetic = held.length > 0 && held.every(([src]) => src === "synthetic");
          const text = held.length > 0 && held.every(([src]) => TEXT_SOURCES.includes(src));
          const usable = sh.cached && !synthetic;
          return (
            <label key={sh.id} style={{ display: "grid", gridTemplateColumns: "20px 44px 1fr auto", gap: 8, alignItems: "center", padding: "6px 10px", borderTop: i ? "1px solid var(--line)" : 0, fontSize: 12.5, opacity: usable ? 1 : 0.55, cursor: usable ? "pointer" : "default" }}>
              <input type="checkbox" disabled={!usable} checked={usable && shards.includes(sh.id)} onChange={() => onToggle(sh.id)} />
              <span className="mono">{sh.id}</span>
              <span>
                {!sh.cached ? <span className="sub">not downloaded on this machine</span>
                  : held.map(([src, n], k) => (
                    <React.Fragment key={src}>{k ? " · " : ""}<span style={{ fontWeight: sources.includes(src) ? 600 : 400, color: sources.includes(src) ? "var(--ink)" : "var(--ink-3)" }}>{src} {n.toLocaleString()}</span></React.Fragment>
                  ))}
              </span>
              <span className="sub" style={{ fontSize: 11 }}>
                {!sh.cached ? "" : synthetic ? "synthetic — never drawn" : text ? "read from text by a model"
                  : held.some(([src]) => TEXT_SOURCES.includes(src)) ? "surveyed, and read from text" : "surveyed people"}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

