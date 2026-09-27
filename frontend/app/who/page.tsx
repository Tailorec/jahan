"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Callout } from "@/components/ui";
import { api, ApiError, useApi, whyNot } from "@/lib/api";
import { coverageLabel, coverageBand, COVERAGE_NOTE, shouldPoll, type CoverageInfo } from "@/lib/coverage";

interface CodebookHit {
  id: string;
  label: string;
  category: string;
  measures: string;
  kind: string;
  values: string[];
}
interface CodebookReply {
  attributes: CodebookHit[];
  total: number;
  mode: string;
  meaning_available: boolean;
  meaning_note: string;
}
interface Status { engine_version: string; endpoint_configured: boolean }

const PRESETS: { label: string; sources: string[] }[] = [
  { label: "All surveys", sources: ["stackoverflow", "gss", "prism", "real_human_survey"] },
  { label: "US public", sources: ["gss"] },
  { label: "Developers", sources: ["stackoverflow"] },
];

const TEXT_SOURCES = ["amazon", "wiki"];
const TEXT_LABEL = "read by a model from text, not surveyed";

interface DraftRow { id: string; label: string; category: string; measures: string; kind: string; role: string; required: boolean }
interface PoolCost { attribute: string; pool_without: number; removes: number; removes_by_source: Record<string, number>; emptied_sources: string[] }
interface PoolReply { state: string; sources_total?: number; sources_by_source?: Record<string, number>; pool?: number; pool_by_source?: Record<string, number>; costs?: PoolCost[] }

export default function WhoPage() {
  const [sources, setSources] = React.useState<string[]>(PRESETS[0].sources);
  const [studySize, setStudySize] = React.useState(200);
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<CodebookHit[] | null>(null);
  const [meaningNote, setMeaningNote] = React.useState<string | null>(null);
  const [corpusMissing, setCorpusMissing] = React.useState(false);
  const [rows, setRows] = React.useState<DraftRow[]>([]);
  const [coverage, setCoverage] = React.useState<CoverageInfo | null>(null);
  const [pool, setPool] = React.useState<PoolReply | null>(null);
  const { data: status } = useApi<Status>("/api/status");

  const requiredKey = JSON.stringify(rows.filter((r) => r.required).map((r) => r.id));
  const sourcesKey = JSON.stringify(sources);
  const askPool = React.useCallback(async () => {
    try {
      setPool(await api<PoolReply>("/api/pool", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ sources: JSON.parse(sourcesKey), required: JSON.parse(requiredKey) }),
      }));
    } catch {
      setPool(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourcesKey, requiredKey]);
  React.useEffect(() => { askPool(); }, [askPool]);

  const search = React.useCallback(async (q: string) => {
    if (!q.trim()) { setHits(null); return; }
    try {
      const d = await api<CodebookReply>("/api/codebook?query=" + encodeURIComponent(q) + "&limit=12");
      setHits(d.attributes);
      setMeaningNote(d.meaning_available ? null : d.meaning_note);
      setCorpusMissing(false);
    } catch (e) {
      setHits(null);
      setCorpusMissing(e instanceof ApiError && e.status === 409);
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

  const toggleSource = (name: string) =>
    setSources((s) => (s.includes(name) ? s.filter((x) => x !== name) : [...s, name]));

  const coverageOf = (id: string) => (coverage?.state === "ready" ? coverage.attributes?.[id] : undefined);

  function addAttr(h: CodebookHit) {
    if (rows.some((r) => r.id === h.id)) return;
    setRows((rs) => [...rs, { id: h.id, label: h.label, category: h.category, measures: h.measures, kind: h.kind, role: "Describes everyone", required: false }]);
  }

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Who you study</b></>}>
      <PageHead
        title="Who you study"
        sub="Describe the people, see who exists. Every count on this page is real — read from the corpus, never invented."
      />
      {corpusMissing && (
        <Callout icon="alert"><div><b>No corpus cached here.</b> Search and drafting need the corpus — author freely, then continue where it is present.</div></Callout>
      )}
      <div className="grid g2">
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Category</h2><span className="hint">reused or new — confirmed from your description</span></div>
            <div className="panel-body"><div className="sub" style={{ fontSize: 12.5 }}>No category confirmed yet. Describe who you want to study first.</div></div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Draw from</h2></div>
            <div className="panel-body" style={{ display: "grid", gap: 6 }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {PRESETS.map((p) => (
                  <button key={p.label} className="btn sm" onClick={() => setSources(p.sources)}>{p.label}</button>
                ))}
              </div>
              {["stackoverflow", "gss", "prism", "real_human_survey", ...TEXT_SOURCES].map((name) => (
                <label key={name} style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={sources.includes(name)} onChange={() => toggleSource(name)} />
                  <span className="mono">{name}</span>
                  {TEXT_SOURCES.includes(name) && <span className="sub" style={{ fontSize: 11 }}>{TEXT_LABEL}</span>}
                </label>
              ))}
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Study size</h2></div>
            <div className="panel-body">
              <label style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center" }}>
                <input className="input mono" style={{ width: 90 }} value={studySize} onChange={(e) => setStudySize(Number(e.target.value) || 0)} />
                personas <span className="sub">— sets each audience&apos;s quota</span>
              </label>
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Candidate pool</h2></div>
            <div className="panel-body">
              {pool?.state === "ready" && (
                <div style={{ display: "grid", gap: 6 }}>
                  <div style={{ fontSize: 22, fontWeight: 650 }}>{(pool.pool ?? 0).toLocaleString("en-US")}</div>
                  <div className="sub" style={{ fontSize: 12 }}>of {(pool.sources_total ?? 0).toLocaleString("en-US")} in your sources have every required answer</div>
                  <div className="mono sub" style={{ fontSize: 11 }}>
                    {Object.entries(pool.pool_by_source ?? {}).map(([name, n]) => `${name} ${n.toLocaleString("en-US")}`).join(" · ")}
                  </div>
                  {(pool.costs ?? []).map((c) => (
                    <div key={c.attribute} className="sub" style={{ fontSize: 12 }}>
                      Requiring <span className="mono">{c.attribute}</span> removes {c.removes.toLocaleString("en-US")}
                      {c.emptied_sources.length > 0 && <> — empties {c.emptied_sources.join(", ")}</>}
                    </div>
                  ))}
                </div>
              )}
              {pool?.state === "building" && <div className="help">Counting who can be drawn — the matrix is building once, in the background…</div>}
              {pool === null && <div className="sub" style={{ fontSize: 12.5 }}>No corpus cached here, so there is nobody to count yet.</div>}
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-body" style={{ display: "grid", gap: 8 }}>
              <button className="btn primary" disabled>Continue to study →</button>
              <div className="sub" style={{ fontSize: 12 }}>Confirm a category to continue.</div>
            </div>
          </div>
        </div>
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Who do you want to study?</h2></div>
            <div className="panel-body" style={{ display: "grid", gap: 8 }}>
              <div className="sub" style={{ fontSize: 12.5 }}>Say who you are testing, the groups, what makes someone belong, and what you want to know.</div>
              <input className="input" placeholder="e.g. parents of young kids and retirees in North America…" disabled />
              <div><button className="btn sm" disabled>Read it</button></div>
              <div className="sub" style={{ fontSize: 12 }}>Describing starts in a later phase — for now, author audiences by hand below. Every count on this page is real.</div>
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Audiences</h2><span className="hint">authored by hand until drafting lands</span></div>
            <div className="panel-body"><div className="empty"><b>No audiences yet.</b>Find attributes below and describe who belongs.</div></div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Ontology</h2><span className="hint">req · attribute · role · kind · ordered</span></div>
            <div className="panel-body">
              {rows.length === 0 && <div className="empty"><b>Nothing declared yet.</b>Add attributes from the search.</div>}
              {rows.map((r) => (
                <div key={r.id} style={{ borderTop: "1px solid var(--line)", padding: "8px 0", display: "grid", gap: 2 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <b>{r.label}</b>
                    <span className="mono sub" style={{ fontSize: 11 }}>{r.id}</span>
                    <span className="sub" style={{ fontSize: 11.5 }}>measures: {r.measures}</span>
                    <button className="btn quiet sm" style={{ marginLeft: "auto" }} onClick={() => setRows((xs) => xs.filter((x) => x.id !== r.id))}>✕</button>
                  </div>
                  <div className="sub" style={{ fontSize: 11.5 }}>{r.role} · {r.kind}</div>
                  <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center", marginTop: 4 }}>
                    <input type="checkbox" checked={r.required} onChange={() => setRows((xs) => xs.map((x) => (x.id === r.id ? { ...x, required: !x.required } : x)))} /> required for everyone
                  </label>
                </div>
              ))}
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Find more attributes</h2><span className="hint">search by words</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 8 }}>
              <input className="input mono" placeholder="search attributes — e.g. kids, money, wealthy" value={query} onChange={(e) => setQuery(e.target.value)} />
              {status && !status.endpoint_configured && (
                <div className="help">Search by meaning is unavailable without an endpoint — searching by words.</div>
              )}
              {meaningNote && <div className="help">{meaningNote}</div>}
              {(hits ?? []).map((h) => {
                const found = coverageOf(h.id);
                const band = coverageBand(found?.recorded);
                return (
                  <div key={h.id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <b>{h.label}</b>
                      <span className="mono sub" style={{ fontSize: 11 }}>{h.id}</span>
                      {rows.some((r) => r.id === h.id)
                        ? <span className="tag">declared</span>
                        : <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => addAttr(h)}>+ Add</button>}
                    </div>
                    <div className="sub" style={{ fontSize: 11.5, marginTop: 4 }}>{h.category} · measures: {h.measures} · {h.kind}</div>
                    <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>{h.values.join(" · ")}</div>
                    {found && (
                      <div style={{ marginTop: 6 }}>
                        <span className={`chip ${band === "most" ? "ok" : band === "few" ? "risk" : "plain"}`} data-coverage={band}>
                          <span className="dot" />{coverageLabel(found.recorded)}
                        </span>
                        {COVERAGE_NOTE[band] && <div className="sub" style={{ fontSize: 11.5, marginTop: 4 }}>{COVERAGE_NOTE[band]}</div>}
                      </div>
                    )}
                  </div>
                );
              })}
              {query && hits?.length === 0 && <div className="empty"><b>Nothing resembles that.</b>An attribute the corpus does not carry is refused — try a shorter search.</div>}
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
