"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Callout } from "@/components/ui";
import { api, ApiError, useApi, whyNot } from "@/lib/api";
import type { CategoryOntology, PersonaFieldDomain } from "@/lib/engine";
import { coverageLabel, coverageBand, COVERAGE_NOTE, shouldPoll, type CoverageInfo } from "@/lib/coverage";

interface CodebookHit { id: string; values: string[] }
interface DraftAttr { id: string; domain: PersonaFieldDomain }

const DOMAINS: PersonaFieldDomain[] = [
  "demographic", "psychographic", "category_behaviour", "economic", "decision_rule", "media",
];

function bump(version: string): string {
  const parts = version.split(".").map(Number);
  if (parts.length !== 3 || parts.some((p) => !Number.isInteger(p))) return `${version}.1`;
  return `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
}

export default function OntologyPage() {
  const [category, setCategory] = React.useState("beverage_protein_persona1m");
  const [version, setVersion] = React.useState("1.0.0");
  const [attrs, setAttrs] = React.useState<DraftAttr[]>([]);
  const [conditioning, setConditioning] = React.useState<string[]>([]);
  const [scales, setScales] = React.useState<Record<string, string[]>>({});
  const [anchorSet, setAnchorSet] = React.useState("purchase-intent-v1");
  const [completable, setCompletable] = React.useState<string[]>(["economic", "decision_rule", "media"]);
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<CodebookHit[] | null>(null);
  const [corpusMissing, setCorpusMissing] = React.useState(false);
  const [check, setCheck] = React.useState<{ valid?: boolean; error?: string } | null>(null);
  const [checking, setChecking] = React.useState(false);
  const [saved, setSaved] = React.useState<{ category: string; version: string } | null>(null);
  const [coverage, setCoverage] = React.useState<CoverageInfo | null>(null);

  const search = React.useCallback(async (q: string) => {
    if (!q.trim()) { setHits(null); return; }
    try {
      const d = await api<{ attributes: CodebookHit[] }>("/api/codebook?query=" + encodeURIComponent(q) + "&limit=12");
      setHits(d.attributes);
      setCorpusMissing(false);
    } catch (e) {
      setHits(null);
      // Only an absent corpus means "author freely"; anything else is the engine saying why it could not answer.
      const absent = e instanceof ApiError && e.status === 409;
      setCorpusMissing(absent);
      if (!absent) setCheck({ valid: false, error: whyNot(e) });
    }
  }, []);

  React.useEffect(() => {
    const t = setTimeout(() => search(query), 250);
    return () => clearTimeout(t);
  }, [query, search]);

  const askCoverage = React.useCallback(async (retry = false) => {
    try {
      setCoverage(await api<CoverageInfo>("/api/corpus/coverage" + (retry ? "?retry=true" : "")));
    } catch (e) {
      setCoverage({ available: false, state: "failed", detail: whyNot(e) });
    }
  }, []);

  React.useEffect(() => { askCoverage(); }, [askCoverage]);
  React.useEffect(() => {
    if (!shouldPoll(coverage) || coverage === null) return;
    const t = setTimeout(() => askCoverage(), 3000);
    return () => clearTimeout(t);
  }, [coverage, askCoverage]);

  /* What the engine counted for one attribute, or nothing where it has not counted yet. */
  const coverageOf = (id: string) => coverage?.state === "ready" ? coverage.attributes?.[id] : undefined;
  const coverageLine = (id: string) => {
    const found = coverageOf(id);
    if (!found) return null;
    const band = coverageBand(found.recorded);
    return (
      <div style={{ marginTop: 6 }}>
        <span className={`chip ${band === "most" ? "ok" : band === "few" ? "risk" : "plain"}`} data-coverage={band}>
          <span className="dot" />{coverageLabel(found.recorded)}
        </span>
        {COVERAGE_NOTE[band] && <div className="sub" style={{ fontSize: 11.5, marginTop: 4 }}>{COVERAGE_NOTE[band]}</div>}
        <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>
          {Object.entries(found.by_source).map(([name, c]) => `${name} ${c.share === null ? "—" : `${(c.share * 100).toFixed(0)}%`}`).join(" · ")}
        </div>
      </div>
    );
  };

  const vocabOf = (id: string): string[] => hits?.find((h) => h.id === id)?.values ?? [];

  function addAttr(id: string) {
    if (attrs.some((a) => a.id === id)) return;
    setAttrs((as) => [...as, { id, domain: "category_behaviour" }]);
  }

  function draft(): Record<string, unknown> {
    const relevance = [...conditioning.filter((c) => attrs.some((a) => a.id === c)),
      ...attrs.map((a) => a.id).filter((id) => !conditioning.includes(id))];
    return {
      category, version,
      attribute_domains: Object.fromEntries(attrs.map((a) => [a.id, a.domain])),
      conditioning_set: conditioning.filter((c) => attrs.some((a) => a.id === c)),
      relevance_order: relevance,
      completion_policy: { completable_domains: completable },
      ordinal_scales: Object.entries(scales)
        .filter(([attr, labels]) => labels.length >= 2 && attrs.some((a) => a.id === attr))
        .map(([attribute, labels]) => ({
          attribute,
          bands: labels.map((label, i) => ({ label, midpoint: i })),
        })),
      anchor_sets: { purchase_intent: anchorSet },
    };
  }

  async function validate() {
    setChecking(true);
    setCheck(null);
    try {
      const d = await api<{ valid: boolean; detail?: string }>("/api/ontologies/validate", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ ontology: draft() }),
      });
      setCheck({ valid: d.valid });
    } catch (e) {
      setCheck({ valid: false, error: whyNot(e) });
    }
    setChecking(false);
  }

  async function save() {
    setChecking(true);
    try {
      const d = await api<{ category: string; version: string }>("/api/ontologies", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ ontology: draft() }),
      });
      setSaved(d);
      setCheck({ valid: true });
    } catch (e) {
      setCheck({ valid: false, error: whyNot(e) });
    }
    setChecking(false);
  }

  async function loadExisting() {
    try {
      const o = await api<CategoryOntology>(`/api/ontologies?category=${encodeURIComponent(category)}&version=${encodeURIComponent(version)}`);
      setAttrs(Object.entries(o.attribute_domains).map(([id, domain]) => ({ id, domain })));
      setConditioning([...o.conditioning_set]);
      setScales(Object.fromEntries(o.ordinal_scales.map((s) => [s.attribute, s.bands.map((b) => b.label)])));
      setCompletable([...(o.completion_policy?.completable_domains ?? [])]);
      setVersion(bump(o.version));
      setSaved(null);
    } catch (e) {
      setCheck({ valid: false, error: whyNot(e) });
    }
  }

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Ontology builder</b></>}>
      <PageHead
        title="Ontology builder"
        sub="What can be studied is bounded by the corpus's own attributes — not by which files exist. Every name is checked against the codebook as it is typed."
        actions={saved ? <span className="chip ok"><span className="dot" />saved {saved.category}@{saved.version}</span> : undefined}
      />
      {corpusMissing && (
        <Callout icon="alert"><div><b>No corpus cached here.</b> Draft freely — attributes, scales and versions assemble locally — but no draft can be pinned until it validates where the corpus is present.</div></Callout>
      )}
      <div className="grid g2">
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Codebook search</h2><span className="hint">1,290 attributes with declared value sets</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 8 }}>
              <input className="input mono" placeholder="search attributes — e.g. exercise, diet, age" value={query} onChange={(e) => setQuery(e.target.value)} />
              {coverage?.state === "building" && <div className="help">Counting how populated each attribute is, once, across the cached shards…</div>}
              {coverage?.state === "failed" && (
                <Callout icon="alert"><div><b>Coverage could not be counted.</b> {coverage.detail}
                  <div><button className="btn sm" style={{ marginTop: 6 }} onClick={() => askCoverage(true)}>Count again</button></div></div></Callout>
              )}
              {(hits ?? []).map((h) => (
                <div key={h.id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <b className="mono">{h.id}</b>
                    {attrs.some((a) => a.id === h.id)
                      ? <span className="tag">in draft</span>
                      : <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => addAttr(h.id)}>+ Add</button>}
                  </div>
                  <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>{h.values.join(" · ")}</div>
                  {coverageLine(h.id)}
                </div>
              ))}
              {query && hits?.length === 0 && <div className="empty"><b>Nothing resembles that.</b>An attribute the corpus does not carry is refused — try a shorter search.</div>}
            </div>
          </div>
        </div>
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Draft</h2><span className="hint">assembles locally — pinning needs the corpus</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              <div className="grid g2">
                <div className="field" style={{ margin: 0 }}><label>Category</label><input className="input mono" value={category} onChange={(e) => setCategory(e.target.value)} /></div>
                <div className="field" style={{ margin: 0 }}><label>New version</label><input className="input mono" value={version} onChange={(e) => setVersion(e.target.value)} /></div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn sm" onClick={loadExisting}>Load existing to edit</button>
                <span className="sub" style={{ fontSize: 12, alignSelf: "center" }}>editing prefills a bumped version — files are never overwritten</span>
              </div>
              {attrs.map((a) => (
                <div key={a.id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <b className="mono">{a.id}</b>
                    <select className="input" style={{ width: 170 }} value={a.domain} onChange={(e) => setAttrs((xs) => xs.map((x) => (x.id === a.id ? { ...x, domain: e.target.value as DraftAttr["domain"] } : x)))}>
                      {DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
                      <input type="checkbox" checked={conditioning.includes(a.id)} onChange={() => setConditioning((c) => toggle(c, a.id))} /> conditioning
                    </label>
                    <button className="btn quiet sm" style={{ marginLeft: "auto" }} onClick={() => { setAttrs((xs) => xs.filter((x) => x.id !== a.id)); setConditioning((c) => c.filter((x) => x !== a.id)); }}>✕</button>
                  </div>
                  {coverageLine(a.id)}
                  {vocabOf(a.id).length > 0 && (
                    <div style={{ marginTop: 6 }}>
                      <div className="sub" style={{ fontSize: 11.5, marginBottom: 4 }}>ordinal scale — codebook labels in codebook order:</div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {vocabOf(a.id).map((v) => (
                          <button key={v} className={`tag${(scales[a.id] ?? []).includes(v) ? " sel" : ""}`}
                            style={(scales[a.id] ?? []).includes(v) ? { borderColor: "var(--primary)" } : undefined}
                            onClick={() => setScales((s) => ({ ...s, [a.id]: toggle(s[a.id] ?? [], v) }))}>{v}</button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {attrs.length === 0 && <div className="empty"><b>Empty draft.</b>Add attributes from the codebook search.</div>}
              <div className="field" style={{ margin: 0 }}><label>Anchor set — purchase_intent</label><input className="input mono" value={anchorSet} onChange={(e) => setAnchorSet(e.target.value)} /></div>
              <div>
                <div className="sub" style={{ fontSize: 12, marginBottom: 4 }}>Completable domains — economics, decision rules, media yes; demographics, psychographics never:</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {DOMAINS.map((d) => (
                    <button key={d} className="tag" style={completable.includes(d) ? { borderColor: "var(--primary)" } : undefined} onClick={() => setCompletable((c) => toggle(c, d))}>{d}</button>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn" disabled={checking} onClick={validate}>{checking ? "Checking…" : "Validate draft"}</button>
                <button className="btn primary" disabled={checking} onClick={save}>{checking ? "Saving…" : "Save new version"}</button>
              </div>
              {check?.valid && <Callout icon="info"><div><b>Valid.</b> The corpus backs every name — this draft can become a version.</div></Callout>}
              {check?.valid === false && <Callout icon="alert"><div><b>Refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{check.error}</pre></div></Callout>}
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>The conditioning set</h2></div>
            <div className="panel-body"><p className="sub" style={{ fontSize: 12.5 }}>The field that decides whether personas differ from one another at all: conditioned responses gave fifty-seven different answers where unconditioned ones collapsed to one. Leaving an attribute out of it costs the study its population — filters cannot use what conditioning never carried, and widening can never trade it for coverage.</p></div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
