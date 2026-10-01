"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { useSessionState } from "@/lib/session";
import { PageHead, Callout, ICONS, Tip, Section, Field } from "@/components/ui";
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

  const ready = mistakes.length === 0 && !realNeedsEndpoint;
  const replicates = seeds.split(",").filter((x) => x.trim()).length || 1;
  const channelLabel = channels.length ? channels.map((c) => CHANNEL_CARD[c].title).join(" + ") : "concept test";

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>New study</b></>}>
      <PageHead
        title="New study"
        sub={<>Product, people, channels — then run. <Tip>Author a <b>brief</b> — the product, its claims, price, competitors, target market — against a pinned <b>category ontology</b>. Claims carry a <b>claim source</b> — asserted, public (needs evidence), or assumed — and the assumption ledger travels into every report.</Tip></>}
        actions={endpoint && (
          <span className={`chip ${endpoint.endpoint_configured ? "ok" : "risk"}`} title="The server's environment configures the endpoint — never the browser">
            <span className="dot" />{endpoint.endpoint_configured ? "endpoint configured" : "no endpoint — studies cannot run"}
          </span>
        )}
      />
      <div className="grid g-32">
        <div>
          <Section step={1} icon="package" title="Product" done={!!form.product.name && !!form.product.description}
            tip="What every persona is shown: the product, its price, the claims it makes and what it competes with.">
            <div className="grid g2">
              <Field icon="package" label="Name"><input className="input" value={form.product.name} placeholder="NestEgg Kids" onChange={(e) => setProduct({ name: e.target.value })} /></Field>
              <Field icon="dollar" label="Price" tip="What the product costs, in the currency beside it. Competitors are priced the same way.">
                <div className="row">
                  <input className="input mono" value={form.price} placeholder="5" onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))} />
                  <input className="input mono" style={{ width: 80 }} aria-label="currency" value={form.currency} onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value.toUpperCase() }))} />
                </div>
              </Field>
            </div>
            <Field icon="bulb" label="Concept" tip={<>Shown to personas verbatim. {onto && <>Conditioning set: <span className="mono">{onto.conditioning_set.join(", ")}</span></>}</>}>
              <textarea className="input" rows={2} value={form.product.description} placeholder="One or two sentences a persona reads" onChange={(e) => setProduct({ description: e.target.value })} />
            </Field>
            <Field icon="target" label="Target market"><input className="input" value={form.target} onChange={(e) => setForm((f) => ({ ...f, target: e.target.value }))} /></Field>
            <Field icon="tag" label={`Claims · ${form.claims.length}`}
              tip={<>A <b>claim</b> is one assertion about the product — the atomic unit of stimulus: posts, feed cards and findings all reference it. Numbered C1, C2…; a <b>public_source</b> claim needs an evidence URL.</>}>
              <div style={{ display: "grid", gap: 6 }}>
                {form.claims.map((c, i) => (
                  <div key={i} className="item">
                    <div className="row">
                      <span className="tag">C{i + 1}</span>
                      <input className="input" value={c.text} style={{ flex: 1 }} placeholder="What the product does for someone" onChange={(e) => setClaim(i, { text: e.target.value })} />
                      <select className="input" style={{ width: 130 }} aria-label="claim source" value={c.source} onChange={(e) => setClaim(i, { source: e.target.value as ClaimSource })}>
                        <option value="user_asserted">user_asserted</option>
                        <option value="public_source">public_source</option>
                        <option value="assumed">assumed</option>
                      </select>
                      <button className="icon-btn" aria-label={`remove claim C${i + 1}`} onClick={() => setForm((f) => ({ ...f, claims: f.claims.filter((_, j) => j !== i) }))}>{ICONS.x}</button>
                    </div>
                    {c.source === "public_source" && (
                      <>
                        <input className="input mono" placeholder="evidence_url — required for public_source" value={c.evidence_url} onChange={(e) => setClaim(i, { evidence_url: e.target.value })} />
                        {c.evidence_url && (
                          <div className="row">
                            <input className="input mono" placeholder="sidecar content_hash (64 hex)" value={evidence[c.evidence_url]?.content_hash ?? ""} style={{ flex: 1 }}
                              onChange={(e) => setEvidence((ev) => ({ ...ev, [c.evidence_url]: { content_hash: e.target.value, fetched_at: ev[c.evidence_url]?.fetched_at ?? new Date().toISOString() } }))} />
                            <span className="tag">{evidence[c.evidence_url]?.content_hash ? "sidecar ✓" : "sidecar missing — intake will refuse"}</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
                <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, claims: [...f.claims, { text: "", source: "assumed", evidence_url: "" }] }))}>{ICONS.plus} Claim</button>
              </div>
            </Field>
            <Field icon="scale" label={`Competitors · ${form.competitors.length}`} tip="What the population weighs the product against: a name, a price and what it claims, one claim per line.">
              <div style={{ display: "grid", gap: 6 }}>
                {form.competitors.map((c, i) => (
                  <div key={i} className="item">
                    <div className="row">
                      <input className="input" placeholder="name" value={c.name} style={{ flex: 1 }} onChange={(e) => setCompetitor(i, { name: e.target.value })} />
                      <input className="input mono" placeholder="price" style={{ width: 80 }} value={c.price} onChange={(e) => setCompetitor(i, { price: e.target.value })} />
                      <input className="input mono" placeholder={form.currency || "USD"} aria-label="competitor currency" style={{ width: 64 }} value={c.currency} onChange={(e) => setCompetitor(i, { currency: e.target.value.toUpperCase() })} />
                      <button className="icon-btn" aria-label={`remove competitor ${c.name || i + 1}`} onClick={() => setForm((f) => ({ ...f, competitors: f.competitors.filter((_, j) => j !== i) }))}>{ICONS.x}</button>
                    </div>
                    <textarea className="input" rows={2} placeholder="what it claims — one per line" value={c.claims} onChange={(e) => setCompetitor(i, { claims: e.target.value })} />
                  </div>
                ))}
                <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, competitors: [...f.competitors, { name: "", price: "", currency: "", claims: "" }] }))}>{ICONS.plus} Competitor</button>
              </div>
            </Field>
          </Section>

          <Section step={2} icon="users" title="Audience" done={form.audiences.length > 0}
            tip={<>Audiences are named slices of the target market — authored in Who you study, where filters are picked from value lists with live counts, never typed. Choosing a set brings its audiences, its category ontology and its assumptions together.</>}>
            <Field icon="users" label="Audience set">
              <div className="row">
                <select className="input" aria-label="Audience set" value={chosenSet} style={{ flex: 1 }} onChange={(e) => {
                  const picked = sets?.audience_sets.find((x) => `${x.category}/${x.id}` === e.target.value);
                  if (picked) applySet(picked);
                }}>
                  <option value="" disabled>{sets?.audience_sets.length ? "choose one…" : "none saved yet"}</option>
                  {(sets?.audience_sets ?? []).map((x) => (
                    <option key={`${x.category}/${x.id}`} value={`${x.category}/${x.id}`}>{x.name} — {x.category} {x.ontology_version} · {x.created_at.slice(0, 10)}</option>
                  ))}
                </select>
                <Link className="btn sm" href={chosenSet ? `/who?set=${chosenSet}` : "/who"}>{chosenSet ? "Edit" : "Create"} {ICONS.ext}</Link>
              </div>
              {form.product.category && <div className="help mono">{form.product.category} @ {form.ontologyVersion}</div>}
            </Field>
            {form.audiences.length === 0
              ? <div className="empty" style={{ padding: 20 }}><b>No audience set chosen.</b>The study cannot start without one.</div>
              : (
                <div style={{ display: "grid", gap: 6, marginBottom: 12 }}>
                  {form.audiences.map((a, i) => (
                    <div key={i} className="item" title={Object.entries(a.filters).map(([k, f]) => `${k} ${f.kind === "exactly" ? `= ${f.value}` : f.kind === "one_of" ? `in (${f.values.join(", ")})` : `from ${f.first} to ${f.last}`}`).join(" · ") || "no filters"}>
                      <div className="row">
                        <span className="sec-icon" style={{ width: 24, height: 24, background: `var(--seg${(i % 5) + 1})`, color: "#fff" }}>{ICONS.users}</span>
                        <b className="mono" style={{ flex: 1 }}>{a.name}</b>
                        <span className="chip plain mono">{a.share === "" ? "—" : `${Math.round(Number(a.share) * 100)}%`}</span>
                      </div>
                      <div className="mono sub" style={{ fontSize: 11 }}>
                        {Object.entries(a.filters).map(([k, f]) => `${k} ${f.kind === "exactly" ? `= ${f.value}` : f.kind === "one_of" ? `in (${f.values.join(", ")})` : `from ${f.first} to ${f.last}`}`).join(" · ") || "no filters"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            <details className="fold">
              <summary>{ICONS.info} Assumptions · {form.assumptions.length}<Tip>An <b>assumption</b> is taken as true without evidence — recorded and surfaced in every report, never resolved away. Each keeps the source it was stated with.</Tip></summary>
              <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                {form.assumptions.map((a, i) => (
                  <div key={i} className="row">
                    <input className="input" style={{ flex: 1 }} value={a.text} onChange={(e) => setAssumption(i, { text: e.target.value })} />
                    <select className="input" style={{ width: 130 }} aria-label="assumption source" value={a.source} onChange={(e) => setAssumption(i, { source: e.target.value as ClaimSource })}>
                      <option value="user_asserted">user_asserted</option>
                      <option value="assumed">assumed</option>
                    </select>
                    <button className="icon-btn" aria-label="remove assumption" onClick={() => setForm((f) => ({ ...f, assumptions: f.assumptions.filter((_, j) => j !== i) }))}>{ICONS.x}</button>
                  </div>
                ))}
                <button className="btn sm" style={{ justifySelf: "start" }} onClick={() => setForm((f) => ({ ...f, assumptions: [...f.assumptions, { text: "", source: "assumed" }] }))}>{ICONS.plus} Assumption</button>
              </div>
            </details>
          </Section>

          <Section step={3} icon="database" title="Population" done={!!gate?.gate?.overall && !!gate.manifest}
            tip="Who is drawn from the persona corpus, and how many. Run the gate first: it draws the population and checks it against the corpus before anything is spent.">
            <div className="grid g2">
              <Field icon="users" label="Personas" tip="How many personas the study draws. Time and cost grow with it; the gate's checks grow more reliable."><input className="input mono" value={n} onChange={(e) => setN(e.target.value)} /></Field>
              <Field icon="shuffle" label="Population seed" tip="Which persona draw. A draw the gate refuses is a draw refused — re-draw with another seed and say you did."><input className="input mono" value={populationSeed} onChange={(e) => setPopulationSeed(e.target.value)} /></Field>
            </div>
            <Field icon="users" label="Sources" tip="Which surveys the personas come from. Synthetic rows are left out on purpose: a persona may not have synthesized demographics, so a draw that reaches them is refused after it is built. Which sources dominate a draw decides who your personas really are — the gate report shows the mix.">
              <div className="row" style={{ flexWrap: "wrap" }}>
                {(corpus?.measured_sources ?? []).map((src) => (
                  <label key={src} className={`pick${sources.includes(src) ? " on" : ""}`}>
                    <input type="checkbox" checked={sources.includes(src)} onChange={() => toggle(sources, setSources, src)} />
                    {sources.includes(src) && ICONS.check}{src}{corpus?.sources[src] ? <span className="n">{corpus.sources[src].toLocaleString()}</span> : null}
                  </label>
                ))}
              </div>
            </Field>
            <details className="fold" style={{ marginBottom: 12 }}>
              <summary>{ICONS.database} Shards · {shards.length ? shards.join(", ") : "none"}<Tip>The corpus files the draw reads. They follow your sources unless you pick them by hand; fewer shards draw faster and use less memory.</Tip></summary>
              <div style={{ marginTop: 8 }}>
                {!corpus?.available
                  ? <div className="help"><b>No corpus is cached where the server runs.</b> A study draws real personas; fetch the release first.</div>
                  : <ShardPicker corpus={corpus} shards={shards} sources={sources}
                      onToggle={(id) => { setShardsByHand(true); toggle(shards, setShards, id); }}
                      onFollowSources={() => { setShardsByHand(false); setShards(shardsFor(corpus, sources)); }} />}
              </div>
            </details>
            <div className="row">
              <button className="btn" disabled={gating || realNeedsEndpoint || mistakes.length > 0} onClick={runGate}>{ICONS.shield}{gating ? "Gating…" : "Run gate"}</button>
              <Tip>coreset-gate draws the population from your real corpus and checks its distributions — a few model calls at most. A failing draw exits 2 with its gate report: a doomed study costs nothing, and a failed gate stays readable on the population page.</Tip>
              {gate?.gate && <span className={`chip ${gate.gate.overall ? "ok" : "risk"}`}><span className="dot" />{gate.gate.overall ? "passed" : "failed"}</span>}
              {gate?.manifest && <span className="chip plain mono">{gate.manifest.persona_ids.length} personas</span>}
              {gate?.run_id && <Link className="btn sm quiet" href={`/population?run=${gate.run_id}`}>Report {ICONS.arrow}</Link>}
            </div>
            {gate && (
              gate.gate ? (
                <>
                  <details className="fold" style={{ marginTop: 10 }}>
                    <summary>{ICONS.shield} {gate.gate.results.filter((r) => r.passed).length}/{gate.gate.results.length} checks passed · evidence {gate.gate.evidence}</summary>
                    <table className="tbl" style={{ marginTop: 6 }}><tbody>
                      {gate.gate.results.map((r, i) => (
                        <tr key={i}><td className="mono sub">{r.kind} · {r.attribute ?? r.kind}</td>
                          <td className="num">{r.p_value != null ? `p ${r.p_value.toFixed(3)}` : r.ks_similarity != null ? `KS ${r.ks_similarity.toFixed(2)}` : "—"}</td>
                          <td>{r.passed ? <span className="chip ok"><span className="dot" />pass</span> : <span className="chip risk"><span className="dot" />fail</span>}</td></tr>
                      ))}
                    </tbody></table>
                    {gate.manifest && <p className="sub mono" style={{ color: "var(--ink-3)" }}>synthesized {(gate.manifest.synthesized_share * 100).toFixed(1)}% · run {gate.run_id}</p>}
                  </details>
                  {gate.gate.overall && !gate.manifest && (
                    <Callout icon="alert" style={{ marginTop: 10 }}><div><b>Every check passed, but the population was not built.</b>
                      <pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{gate.refusal ?? "No reason was given."}</pre></div></Callout>
                  )}
                </>
              ) : (
                <Callout icon="alert" style={{ marginTop: 10 }}><div><b>The gate could not draw this population (exit {gate.code}).</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{gate.refusal}</pre></div></Callout>
              )
            )}
          </Section>

          <Section step={4} icon="radio" title="Spread & survey" done
            tip="Channels — what spreads information between personas, in any combination; none is the concept test. Survey waves are when every persona answers the purchase-intent question.">
            <div className="lbl">{ICONS.radio} Channels — what spreads information <Tip>{channels.length === 0 ? "Concept test — every persona sees the concept alone." : channels.map((c) => CHANNEL_GUIDE[c].use).join(" ")}</Tip></div>
            <div className="chan-grid" style={{ marginBottom: 6 }}>
              {CHANNELS.map((c) => (
                <label key={c} className={`chan${channels.includes(c) ? " on" : ""}`} title={CHANNEL_GUIDE[c].use}>
                  <input type="checkbox" checked={channels.includes(c)} onChange={() => toggle(channels, setChannels, c)} aria-label={c} />
                  <span className="ci">{ICONS[CHANNEL_CARD[c].icon]}</span>
                  <b>{CHANNEL_CARD[c].title}</b>
                  <small>{CHANNEL_GUIDE[c].summary}</small>
                  <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)" }}>{c}</span>
                  {channels.includes(c) && <span className="tick">{ICONS.check}</span>}
                </label>
              ))}
            </div>
            <div className="help" style={{ marginBottom: 14, minHeight: 18 }}>{channels.length === 0 && "Concept test — every persona sees the concept alone."}</div>
            {feedTicked && (
              <Field icon="cpu" label="Feed ranking model" tip="The feed ranks like X — posts from ties and follows first, then interest × recency — with TwHIN-BERT, served on this machine beside the gateway.">
                <div className="row">
                  <input className="input mono" style={{ flex: 1 }} value={recsysEmbedModel} onChange={(e) => setRecsysEmbedModel(e.target.value)} />
                  <span className={`status-dot ${recsysCheck === null ? "wait" : recsysCheck.reachable ? "ok" : "no"}`}>{recsysCheck === null ? "checking…" : recsysCheck.reachable ? "It answers." : "not answering"}</span>
                </div>
                {recsysCheck && !recsysCheck.reachable && <div className="help" style={{ color: "var(--risk)" }}>It does not answer: {recsysCheck.detail}</div>}
              </Field>
            )}
            <div className="grid g2">
              <Field icon="survey" label="Survey every k ticks" tip="How often every persona answers the purchase-intent question, apart from anything it does on a channel. Tick 0 and the last tick always have a wave. Each answer is one chat call and one embedding; the budget never thins a wave — a study pauses before one it cannot afford.">
                <input className="input mono" value={surveyEvery} onChange={(e) => setSurveyEvery(e.target.value)} />
              </Field>
              {wordOfMouthAlone && (
                <Field icon="wom" label="Launch reach" tip="The share of personas who hear first-hand at launch, chosen at random — without them nobody has anything to pass on.">
                  <input className="input mono" value={launchReach} onChange={(e) => setLaunchReach(e.target.value)} />
                </Field>
              )}
            </div>
            {wavePlan && (
              <div className="row" style={{ flexWrap: "wrap" }}>
                <span className="wave-pills">{wavePlan.ticks.map((t) => <span key={t}>tick {t}</span>)}</span>
                <span className="sub mono" style={{ fontSize: 12 }}>{wavePlan.answers.toLocaleString()} answers</span>
              </div>
            )}
          </Section>

          <Section step={5} icon="sliders" title="Models & run" done={!!model.trim() && !!embedModel.trim()}
            tip="The models every call is pinned to, how long the study runs, how many replicates and what it may spend. The endpoint and its key are the server's environment; this form never asks for either.">
            <div className="grid g2">
              <Field icon="cpu" label="Chat model" tip="Pinned: recorded, hashed and fixed for the whole run."><input className="input mono" value={model} placeholder="amazon.nova-micro-v1:0" onChange={(e) => setModel(e.target.value)} /></Field>
              <Field icon="cpu" label="Embedding model" tip="Pins are study inputs — recorded, hashed, and fixed for the whole run. It scores purchase intent, so it must match the anchor version's check."><input className="input mono" value={embedModel} placeholder="amazon.titan-embed-text-v2:0" onChange={(e) => setEmbedModel(e.target.value)} /></Field>
            </div>
            <div className="grid g2">
              <Field icon="clock" label="Horizon" tip="How many ticks the world runs, and what one tick stands for.">
                <div className="row">
                  <input className="input mono" style={{ width: 80 }} value={horizon} onChange={(e) => setHorizon(e.target.value)} aria-label="Horizon (ticks)" />
                  <select className="input" value={tickUnit} onChange={(e) => setTickUnit(e.target.value)} aria-label="Tick unit">
                    <option value="hour">hours</option><option value="day">days</option><option value="week">weeks</option>
                  </select>
                </div>
              </Field>
              <Field icon="dollar" label="Budget (USD)" tip="The most the study may spend. As spend nears it, the study thins channel activity, and pauses before a survey wave it cannot afford."><input className="input mono" value={budget} onChange={(e) => setBudget(e.target.value)} /></Field>
            </div>
            <div className="grid g2">
              <Field icon="shuffle" label="Replicate seeds" tip="Comma-separated. More than one is what says whether an ordering survives — and each one is a full run of time and cost."><input className="input mono" value={seeds} onChange={(e) => setSeeds(e.target.value)} /></Field>
              <Field icon="survey" label="Anchor version" tip="The frozen scale that turns an answer into purchase intent. Only a version that passed its check against your embedding model scores anything.">
                {anchors && anchors.anchors.length > 0
                  ? <select className="input mono" value={anchorVersion} onChange={(e) => setAnchorVersion(e.target.value)}>
                      {anchors.anchors.map((a) => {
                        const value = `${a.construct}=${a.version}`;
                        return <option key={value} value={value}>{a.passed ? "✓" : "✗"} {value}</option>;
                      })}
                    </select>
                  : <input className="input mono" value={anchorVersion} onChange={(e) => setAnchorVersion(e.target.value)} />}
              </Field>
            </div>
            {chosenAnchor && !chosenAnchor.passed && <Callout icon="alert" style={{ marginBottom: 12 }}><div><b>This version did not pass its check, so nothing will be scored against it.</b> {chosenAnchor.detail}</div></Callout>}
            {chosenAnchor?.passed && chosenAnchor.unchanged_since_check === false && <Callout icon="alert" style={{ marginBottom: 12 }}><div><b>This file changed after its check passed:</b> a changed statement is a new version, so it will not be pinned.</div></Callout>}
            {anchorMismatch && <Callout icon="alert" style={{ marginBottom: 12 }}><div><b>It was checked against {chosenAnchor?.embed_model_id}, not {embedModel.trim()}.</b> A check is evidence about one embedding model, so it will not score with another.</div></Callout>}
            <details className="fold">
              <summary>{ICONS.dollar} Prices &amp; validation <span className="sub" style={{ fontWeight: 400 }}>optional</span><Tip>Prices are what let the budget ladder measure spend. Without them a cost the gateway does not quote stays unknown, and a run where nothing is priced stops rather than spend blind.</Tip></summary>
              <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                <div className="lbl">What the models cost (USD per million tokens)</div>
                <div className="grid g2">
                  <input className="input mono" value={priceChatIn} placeholder="chat in · 0.035" aria-label="chat input price" onChange={(e) => setPriceChatIn(e.target.value)} />
                  <input className="input mono" value={priceChatOut} placeholder="chat out · 0.14" aria-label="chat output price" onChange={(e) => setPriceChatOut(e.target.value)} />
                </div>
                <input className="input mono" value={priceEmbedIn} placeholder="embedding in · 0.02" aria-label="embedding input price" onChange={(e) => setPriceEmbedIn(e.target.value)} />
                <div className="lbl" style={{ marginTop: 6 }}>Recommended real-world validation <Tip>Printed last in the report: what a reader should do to check this against real people.</Tip></div>
                <input className="input" value={validation} placeholder="e.g. Interview twenty parents before building anything." onChange={(e) => setValidation(e.target.value)} />
              </div>
            </details>
          </Section>
        </div>

        <div>
          <div className="glance">
            <div className="panel">
              <div className="panel-head"><div className="sec-head"><span className="sec-icon">{ICONS.play}</span><h2>Launch study</h2></div>
                <Tip>Runs as a subprocess under the same id a resume reuses, and writes the same artefacts the command line does — on the server&apos;s endpoint, with the models named here.</Tip></div>
              <div className="panel-body" style={{ display: "grid", gap: 12 }}>
                <div className="glance-grid">
                  <div><div className="k">{ICONS.users} Personas</div><div className="v">{n || "—"}</div></div>
                  <div><div className="k">{ICONS.radio} Channels</div><div className="v" style={{ fontSize: 13 }}>{channelLabel}</div></div>
                  <div><div className="k">{ICONS.clock} Horizon</div><div className="v">{horizon} {tickUnit}{horizon === "1" ? "" : "s"}</div></div>
                  <div><div className="k">{ICONS.survey} Answers</div><div className="v">{wavePlan ? wavePlan.answers.toLocaleString() : "—"}</div></div>
                  <div><div className="k">{ICONS.shuffle} Replicates</div><div className="v">{replicates}</div></div>
                  <div><div className="k">{ICONS.dollar} Budget</div><div className="v">${budget || "—"}</div></div>
                </div>
                <ul className="checks" aria-label="Before this can start">
                  {realNeedsEndpoint && <li className="no">{ICONS.x}<span>No endpoint is configured where the server runs — set SIMCORE_INFERENCE_BASE_URL (and its key) in its environment, then restart it. A key is never typed into a browser.</span></li>}
                  {mistakes.map((m) => <li key={m} className="no">{ICONS.x}<span>{m}</span></li>)}
                  {ready && <li className="ok">{ICONS.check}<span>Ready to run.</span></li>}
                </ul>
                <button className="btn primary" disabled={launching || !ready} onClick={launchStudy} style={{ justifyContent: "center" }}>{ICONS.play}{launching ? "Launching…" : "Run study"}</button>
                {launched?.run_id && <Link className="btn sm" href={`/run?run=${launched.run_id}`}>Watch {launched.run_id} {ICONS.arrow}</Link>}
                {launched?.error && <Callout icon="alert"><div><b>Launch refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{launched.error}</pre></div></Callout>}
              </div>
            </div>

            <div className="panel">
              <div className="panel-body" style={{ display: "grid", gap: 10 }}>
                <details className="fold">
                  <summary>{ICONS.shield} Brief check{ledger && <span className="chip ok" style={{ marginLeft: 6 }}><span className="dot" />valid</span>}{ledgerError && <span className="chip risk" style={{ marginLeft: 6 }}><span className="dot" />refused</span>}
                    <Tip>The engine&apos;s own contracts, checked before a run can start, and the Assumption ledger — stated, assumed and unstated — that travels into every report.</Tip></summary>
                  <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                    <button className="btn sm" style={{ justifySelf: "start" }} disabled={checkingBrief} onClick={checkBrief}>{ICONS.shield}{checkingBrief ? "Checking…" : "Validate brief"}</button>
                    {ledger && (
                      <>
                        <div className="mono sub" style={{ fontSize: 11.5 }}>{ledger.product} · {ledger.category}@{ledger.ontology_version} · claims {ledger.claims.join(", ")} · audiences {ledger.audiences.join(", ") || "—"}</div>
                        <div className="sub" style={{ fontSize: 12 }}>Assumption ledger</div>
                        {ledger.assumption_ledger.map((a, i) => (
                          <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                            <span className={`chip ${a.source === "assumed" ? "assump" : "plain"}`}><span className="dot" />{a.source.replace("_", " ")}</span>
                            <span style={{ fontSize: 12.5 }}>{a.text}</span>
                          </div>
                        ))}
                      </>
                    )}
                    {ledgerError && <Callout icon="alert"><div><b>The brief is refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{ledgerError}</pre></div></Callout>}
                  </div>
                </details>
                <details className="fold">
                  <summary>{ICONS.code} Brief YAML<Tip>Exactly what intake reads — the form above, written out.</Tip></summary>
                  <pre className="mono" style={{ fontSize: 11, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 12, maxHeight: 360, overflow: "auto", whiteSpace: "pre-wrap", marginTop: 8 }}>{briefYaml}</pre>
                </details>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}

/* Each channel as a card: an icon and a short name over the one-line summary. */
const CHANNEL_CARD: Record<ChannelName, { title: string; icon: keyof typeof ICONS }> = {
  social_feed: { title: "Social feed (X-like)", icon: "feed" },
  forum: { title: "Forum (Reddit-like)", icon: "forum" },
  wom: { title: "Word of mouth (person to person)", icon: "wom" },
};

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

