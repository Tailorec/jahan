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
  domain?: string;
  measures: string;
  kind: string;
  values: string[];
  relevance?: number | null;
  present?: number;
  total?: number;
  share?: number;
  carry_by_source?: Record<string, number>;
  if_required?: { pool: number; by_source: Record<string, number>; lost: number; wiped_sources: string[] };
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

interface DraftRow { id: string; label: string; category: string; domain: string; measures: string; kind: string; role: string; required: boolean; locked?: boolean; values: string[] }
interface PoolCost { attribute: string; pool_without: number; removes: number; removes_by_source: Record<string, number>; emptied_sources: string[] }
interface PoolReply { state: string; sources_total?: number; sources_by_source?: Record<string, number>; pool?: number; pool_by_source?: Record<string, number>; costs?: PoolCost[] }
interface HeadCount { name: string; quota: number; head_count: number; by_source: Record<string, number>; dominant_source: string | null; filter_costs: Record<string, number>; empty_note: string | null; text_would_add: Record<string, number> }
interface PreviewReply { state: string; audiences?: HeadCount[]; assumptions?: { text: string; source: string }[] }
interface Audience { name: string; share: number | null; filters: Record<string, string[]>; descriptions: string[]; changes?: { attribute: string; values: string[]; before: number; after: number; accepted: boolean }[] }

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
      const s = JSON.parse(sourcesKey).join(",");
      const r = JSON.parse(requiredKey).join(",");
      const d = await api<CodebookReply>(`/api/codebook?query=${encodeURIComponent(q)}&limit=12&mode=meaning&sources=${encodeURIComponent(s)}&required=${encodeURIComponent(r)}`);
      setHits(d.attributes);
      setMeaningNote(d.meaning_available ? null : d.meaning_note);
      setCorpusMissing(false);
    } catch (e) {
      setHits(null);
      setCorpusMissing(e instanceof ApiError && e.status === 409);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourcesKey, requiredKey]);

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

  function addAttr(h: CodebookHit, required: boolean) {
    if (rows.some((r) => r.id === h.id)) return;
    setRows((rs) => [...rs, { id: h.id, label: h.label, category: h.category, domain: h.domain ?? "category_behaviour", measures: h.measures, kind: h.kind, role: required ? "Required for everyone" : "Describes everyone", required, values: h.values }]);
  }

  const [audiences, setAudiences] = React.useState<Audience[]>([]);
  const [preview, setPreview] = React.useState<PreviewReply | null>(null);

  interface ReadingGroup { name: string; share: number | null; traits: string[] }
  interface DescribeReply { reading: { product: string | null; groups: ReadingGroup[]; everyone: string[]; topics: string[] }; product: string | null; match: { id: string; version: string; products: string[] } | null; new_id: string; categories: { id: string; version: string; products: string[] }[] }
  const [description, setDescription] = React.useState("");
  const [described, setDescribed] = React.useState<DescribeReply | null>(null);
  const [describing, setDescribing] = React.useState(false);
  const [describeError, setDescribeError] = React.useState<string | null>(null);
  const [category, setCategory] = React.useState<{ mode: "reuse" | "new"; id: string } | null>(null);
  const [sameAs, setSameAs] = React.useState("");

  interface DraftUnsure { phrase: string; choices: { attribute: string; label: string; values: string[]; n_alone: number }[] }
  interface DraftAudience { name: string; share: number | null; filters: Record<string, string[]>; phrases: Record<string, string>; unsure: DraftUnsure[]; descriptions: string[] }
  interface DraftAttr { id: string; label: string; category: string; domain: string; measures: string; kind: string; values: string[]; required: boolean; locked: boolean; role: string; phrase: string | null }
  interface DraftQuestion { phrase: string; choices: { attribute: string; label: string; values: string[]; n_alone: number }[]; applies_to: string[] }
  interface DraftReply { state: string; audiences: DraftAudience[]; attributes: DraftAttr[]; questions: DraftQuestion[]; unmatched: { phrase: string; missing: string }[] }
  const [drafted, setDrafted] = React.useState<DraftReply | null>(null);
  const [drafting, setDrafting] = React.useState(false);
  const [draftError, setDraftError] = React.useState<string | null>(null);
  const [questions, setQuestions] = React.useState<DraftQuestion[]>([]);
  const [blockers, setBlockers] = React.useState<string[] | null>(null);

  interface ReadyReply { state: string; ontology: { category: string; version: string }; audiences: { name: string; share: number | null; attribute_filters: Record<string, string | string[]> }[]; assumptions: { text: string; source: string }[]; action: string; from_version: string | null }
  const [ready, setReady] = React.useState<ReadyReply | null>(null);
  const [continuing, setContinuing] = React.useState(false);
  const [continueError, setContinueError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  async function continueIt() {
    if (!category || continuing) return;
    setContinuing(true);
    setContinueError(null);
    try {
      setReady(await api<ReadyReply>("/api/who/launch", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          category,
          attributes: rows.map((r) => ({ id: r.id, domain: r.domain, required: r.required })),
          audiences,
          assumptions: preview?.assumptions ?? [],
        }),
      }));
      setSaved(false);
    } catch (e) {
      setContinueError(whyNot(e));
    }
    setContinuing(false);
  }

  async function saveOntology() {
    if (!ready) return;
    try {
      await api("/api/ontologies", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ ontology: ready.ontology }),
      });
      setSaved(true);
    } catch (e) {
      setContinueError(whyNot(e));
    }
  }

  function openLaunch() {
    if (!ready) return;
    try {
      localStorage.setItem("who-launch", JSON.stringify({
        audiences: ready.audiences, assumptions: ready.assumptions,
        sources: JSON.parse(sourcesKey), studySize,
        category: ready.ontology.category, ontologyVersion: ready.ontology.version,
      }));
    } catch { /* a full store is not a failed study */ }
    window.location.href = "/intake?from=who";
  }

  interface Turn { text: string; matched: string[]; missing: { phrase: string; missing: string }[] }
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [followup, setFollowup] = React.useState("");
  const [followingUp, setFollowingUp] = React.useState(false);

  async function sendFollowup() {
    if (!followup.trim() || followingUp) return;
    setFollowingUp(true);
    try {
      const d = await api<{ state: string; audiences: Audience[]; added: string[]; questions: DraftQuestion[]; unmatched: { phrase: string; missing: string }[]; fits: Record<string, unknown> }>("/api/draft/followup", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: followup, audiences, sources: JSON.parse(sourcesKey) }),
      });
      if (d.state === "ready") {
        const added = new Set(d.added ?? []);
        setAudiences(d.audiences.map((a) => ({
          name: a.name, share: added.has(a.name) ? null : a.share,
          filters: a.filters, descriptions: a.descriptions ?? [], changes: (a as Audience).changes ?? [],
        })));
        setQuestions((qs) => [...qs, ...(d.questions ?? [])]);
        setTurns((ts) => [...ts, {
          text: followup,
          matched: Object.entries(d.fits ?? {}).map(([phrase]) => phrase),
          missing: d.unmatched ?? [],
        }]);
        setFollowup("");
      }
    } catch {
      setTurns((ts) => [...ts, { text: followup, matched: [], missing: [{ phrase: followup, missing: "the follow-up could not be read" }] }]);
    }
    setFollowingUp(false);
  }

  async function fitIt(audiences: Audience[]) {
    try {
      const parsed = JSON.parse(draftKey);
      const d = await api<{ state: string; audiences: { name: string; share: number | null; filters: Record<string, string[]>; descriptions: string[]; changes: { attribute: string; values: string[]; before: number; after: number; accepted: boolean }[]; quota: number; head_count: number; below_quota: boolean }[] }>("/api/draft/fit", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ sources: parsed.s, required: parsed.r, study_size: parsed.n, audiences }),
      });
      if (d.state === "ready") {
        setAudiences(d.audiences.map((a) => ({ name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions, changes: a.changes })));
      }
    } catch {
      /* fitting is best-effort in the interface: the blockers still name what is short */
    }
  }

  async function draftIt() {
    if (!described || !category || drafting) return;
    setDrafting(true);
    setDraftError(null);
    try {
      const d = await api<DraftReply>("/api/draft", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: description, reading: described.reading, category, sources: JSON.parse(sourcesKey) }),
      });
      setDrafted(d);
      setQuestions(d.questions ?? []);
      const fresh = (d.audiences ?? []).map((a) => ({ name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions ?? [] }));
      setAudiences(fresh);
      setTurns((ts) => [...ts, {
        text: description,
        matched: fresh.flatMap((a, i) => Object.entries((d.audiences ?? [])[i]?.phrases ?? {}).map(([attr, phrase]) => `"${phrase}" → ${attr}`)),
        missing: d.unmatched ?? [],
      }]);
      fitIt(fresh);
      setRows((rs) => {
        const next = [...rs];
        for (const entry of d.attributes ?? []) {
          const at = next.findIndex((r) => r.id === entry.id);
          const row = { id: entry.id, label: entry.label, category: entry.category, domain: entry.domain ?? "category_behaviour", measures: entry.measures, kind: entry.kind, role: entry.required ? "Required for everyone" : entry.role === "matters" ? "Describes everyone" : `Defines audiences`, required: entry.required, locked: entry.locked, values: entry.values };
          if (at >= 0) next[at] = { ...next[at], ...row };
          else next.push(row);
        }
        return next;
      });
    } catch (e) {
      setDraftError(whyNot(e));
    }
    setDrafting(false);
  }

  function answerQuestion(qi: number, choice: { attribute: string; values: string[] } | null) {
    const q = questions[qi];
    if (choice) {
      setAudiences((as) => as.map((a) => (q.applies_to.includes(a.name)
        ? { ...a, filters: { ...a.filters, [choice.attribute]: choice.values } }
        : a)));
    }
    setQuestions((qs) => qs.filter((_, i) => i !== qi));
  }

  function acceptChange(ai: number, ci: number) {
    setAudiences((as) => as.map((a, i) => (i === ai
      ? { ...a, changes: (a.changes ?? []).map((c, j) => (j === ci ? { ...c, accepted: true } : c)) }
      : a)));
  }
  function undoChange(ai: number, ci: number) {
    setAudiences((as) => as.map((a, i) => {
      if (i !== ai) return a;
      const change = (a.changes ?? [])[ci];
      if (!change) return a;
      return {
        ...a,
        filters: { ...a.filters, [change.attribute]: change.values },
        descriptions: a.descriptions.filter((d) => d !== change.attribute),
        changes: (a.changes ?? []).filter((_, j) => j !== ci),
      };
    }));
  }

  const blockersKey = JSON.stringify({
    category,
    questions: questions.map((q) => ({ phrase: q.phrase, applies_to: q.applies_to })),
    changes: audiences.flatMap((a) => a.changes ?? []),
    audiences: audiences.map((a) => ({ name: a.name, share: a.share })),
    previews: (preview?.audiences ?? []).map((h) => ({ quota: h.quota, head_count: h.head_count })),
  });
  const askBlockers = React.useCallback(async () => {
    try {
      const d = await api<{ blockers: string[] }>("/api/who/blockers", {
        method: "POST", headers: { "content-type": "application/json" }, body: blockersKey,
      });
      setBlockers(d.blockers);
    } catch {
      setBlockers(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockersKey]);
  React.useEffect(() => { askBlockers(); }, [askBlockers]);

  async function readIt() {
    if (!description.trim() || describing) return;
    setDescribing(true);
    setDescribeError(null);
    try {
      setDescribed(await api<DescribeReply>("/api/describe", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: description }),
      }));
    } catch (e) {
      setDescribeError(whyNot(e));
    }
    setDescribing(false);
  }

  const draftKey = JSON.stringify({ s: JSON.parse(sourcesKey), r: JSON.parse(requiredKey), n: studySize, a: audiences });
  const askPreview = React.useCallback(async () => {
    if (audiences.length === 0) { setPreview(null); return; }
    try {
      const parsed = JSON.parse(draftKey);
      setPreview(await api<PreviewReply>("/api/audiences/preview", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ sources: parsed.s, required: parsed.r, study_size: parsed.n, audiences: parsed.a }),
      }));
    } catch {
      setPreview(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);
  React.useEffect(() => { askPreview(); }, [askPreview]);

  const shareTotal = audiences.reduce((t, a) => t + (a.share ?? 0), 0);

  interface PickerData { state: string; id: string; label: string; values: { value: string; n: number; by_source: Record<string, number> }[]; also_asks: { id: string; label: string; category: string; measures: string; kind: string; n: number; by_source: Record<string, number> }[] }
  const [pickerFor, setPickerFor] = React.useState<{ ai: number; attr: string } | null>(null);
  const [picker, setPicker] = React.useState<PickerData | null>(null);

  const pickerKey = pickerFor ? JSON.stringify({ attr: pickerFor.attr, s: JSON.parse(sourcesKey), r: JSON.parse(requiredKey) }) : null;
  const askPicker = React.useCallback(async () => {
    if (!pickerKey) { setPicker(null); return; }
    try {
      const parsed = JSON.parse(pickerKey);
      const q = `sources=${encodeURIComponent(parsed.s.join(","))}&required=${encodeURIComponent(parsed.r.join(","))}`;
      setPicker(await api<PickerData>(`/api/codebook/${encodeURIComponent(parsed.attr)}/values?${q}`));
    } catch {
      setPicker(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickerKey]);
  React.useEffect(() => { askPicker(); }, [askPicker]);

  function toggleValue(ai: number, attr: string, value: string) {
    setAudiences((as) => as.map((a, i) => {
      if (i !== ai) return a;
      const current = a.filters[attr] ?? [];
      const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
      if (next.length === 0) {
        const filters = { ...a.filters };
        delete filters[attr];
        return { ...a, filters };
      }
      return { ...a, filters: { ...a.filters, [attr]: next } };
    }));
  }
  function swapFilter(ai: number, from: string, to: { id: string }) {
    setPickerFor({ ai, attr: to.id });
    setAudiences((as) => as.map((a, i) => {
      if (i !== ai) return a;
      const current = a.filters[from] ?? [];
      const row = rows.find((r) => r.id === to.id);
      const vocab = row?.values ?? [];
      const kept = current.filter((v) => vocab.includes(v));
      const filters = { ...a.filters };
      delete filters[from];
      filters[to.id] = kept.length ? kept : vocab.slice(0, 1);
      const declared = rows.some((r) => r.id === to.id) ? rows : [...rows, { id: to.id, label: to.id, category: "", domain: "category_behaviour", measures: "", kind: "", role: "Defines audiences", required: false, values: vocab }];
      setRows(declared);
      return { ...a, filters };
    }));
  }

  function addAudience() {
    setAudiences((as) => [...as, { name: `Group ${as.length + 1}`, share: null, filters: {}, descriptions: [] }]);
  }
  function moveToDescription(ai: number, attr: string) {
    setAudiences((as) => as.map((a, i) => {
      if (i !== ai) return a;
      const filters = { ...a.filters };
      delete filters[attr];
      return { ...a, filters, descriptions: a.descriptions.includes(attr) ? a.descriptions : [...a.descriptions, attr] };
    }));
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
            <div className="panel-body">
              {category
                ? <div style={{ fontSize: 12.5 }}><span className="mono">{category.id}</span> · {category.mode === "reuse" ? "reused ontology" : "new category"}</div>
                : <div className="sub" style={{ fontSize: 12.5 }}>No category confirmed yet. Describe who you want to study first.</div>}
            </div>
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
                  {(JSON.parse(sourcesKey).includes("amazon") || JSON.parse(sourcesKey).includes("wiki")) && (
                    <div className="sub" style={{ fontSize: 11 }}>Includes people read by a model from text, not surveyed.</div>
                  )}
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
              {(blockers ?? []).length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
                  {(blockers ?? []).map((b, i) => <li key={i}>{b}</li>)}
                </ul>
              )}
              {(blockers ?? []).length === 0 && audiences.length > 0 && (
                <div className="sub" style={{ fontSize: 12.5 }}>Nothing stands in the way.</div>
              )}
              <button className="btn primary" disabled={(blockers ?? ["loading"]).length > 0 || continuing} onClick={continueIt}>{continuing ? "Checking…" : "Continue to study →"}</button>
              {continueError && <Callout icon="alert"><div><b>Cannot continue.</b> {continueError}</div></Callout>}
            </div>
          </div>
        </div>
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Who do you want to study?</h2></div>
            <div className="panel-body" style={{ display: "grid", gap: 8 }}>
              <div className="sub" style={{ fontSize: 12.5 }}>Say who you are testing, the groups, what makes someone belong, and what you want to know.</div>
              <input className="input" placeholder="e.g. parents of young kids and retirees in North America…" value={description} onChange={(e) => setDescription(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") readIt(); }} />
              <div><button className="btn sm" disabled={describing || !description.trim()} onClick={readIt}>{describing ? "Reading…" : "Read it"}</button></div>
              {describeError && <Callout icon="alert"><div><b>Could not read that.</b> {describeError}</div></Callout>}
              {status && !status.endpoint_configured && <div className="help">Without an endpoint, describing and drafting are unavailable — author audiences by hand below.</div>}
              <div className="sub" style={{ fontSize: 12 }}>Every count on this page is real.</div>
            </div>
          </div>
          {described && (
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel-head"><h2>I read this as a study of {described.product ?? "your product"}</h2></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                {described.reading.groups.map((g, i) => (
                  <div key={i} style={{ fontSize: 12.5 }}><b>{g.name}</b>{g.share !== null && <> ({Math.round(g.share * 100)}%)</>}: {g.traits.join("; ") || "—"}</div>
                ))}
                {described.reading.everyone.length > 0 && <div style={{ fontSize: 12.5 }}><b>Everyone</b>: {described.reading.everyone.join("; ")}</div>}
                {described.reading.topics.length > 0 && <div style={{ fontSize: 12.5 }}><b>You want to know</b>: {described.reading.topics.join("; ")}</div>}
                <div className="sub" style={{ fontSize: 12 }}>Something missing? Rephrase and read again — nothing is drafted before you confirm the category.</div>
                {described.match
                  ? <div style={{ fontSize: 12.5 }}>Same kind of product as <b className="mono">{described.match.id}</b>? <span className="sub">{(described.match.products ?? []).join(", ")}</span></div>
                  : <div style={{ fontSize: 12.5 }}>No existing category looks like the same kind of product. Start <b className="mono">{described.new_id}</b> as a new category?</div>}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {described.match && <button className="btn primary sm" onClick={() => setCategory({ mode: "reuse", id: described.match!.id })}>Yes — use its ontology</button>}
                  <button className="btn sm" onClick={() => setCategory({ mode: "new", id: described.new_id })}>Start a new category</button>
                  {described.categories.length > 0 && (
                    <select className="input" style={{ width: 220 }} value={sameAs} onChange={(e) => setSameAs(e.target.value)}>
                      <option value="">It&apos;s the same as…</option>
                      {described.categories.map((c) => <option key={c.id} value={c.id}>{c.id} @{c.version}</option>)}
                    </select>
                  )}
                  {sameAs && <button className="btn sm" onClick={() => { setCategory({ mode: "reuse", id: sameAs }); setSameAs(""); }}>Use {sameAs}</button>}
                  <button className="btn quiet sm" onClick={() => setDescribed(null)}>Rephrase</button>
                </div>
              </div>
            </div>
          )}
          {described && category && (
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel-head"><h2>Draft</h2><span className="hint">matched against the corpus, checked — you confirm</span></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                <div><button className="btn primary sm" disabled={drafting} onClick={draftIt}>{drafting ? "Drafting…" : "Draft audiences"}</button></div>
                {draftError && <Callout icon="alert"><div><b>Could not draft.</b> {draftError}</div></Callout>}
              </div>
            </div>
          )}
          {ready && (
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel-head"><h2>Ready for a study</h2><span className="hint">checked by the engine&apos;s own types</span></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                <div style={{ fontSize: 12.5 }}>
                  {ready.action === "reused" && <>Reuses <b className="mono">{ready.ontology.category}@{ready.ontology.version}</b> as it is.</>}
                  {ready.action === "new_version" && <>Publishes <b className="mono">{ready.ontology.category}@{ready.ontology.version}</b> — a new patch version adding what you declared, conditioning set unchanged (from {ready.from_version}).</>}
                  {ready.action === "new_category" && <>Starts <b className="mono">{ready.ontology.category}@1.0.0</b> as a new category.</>}
                </div>
                {(ready.assumptions ?? []).length > 0 && (
                  <div style={{ display: "grid", gap: 4 }}>
                    <div className="sub" style={{ fontSize: 12 }}>Assumptions written to the brief:</div>
                    {ready.assumptions.map((a, i) => <div key={i} className="sub" style={{ fontSize: 12.5 }}>assumed — {a.text}</div>)}
                  </div>
                )}
                <div className="sub" style={{ fontSize: 12 }}>Audiences: {(ready.audiences ?? []).map((a) => a.name).join(", ")}</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <a className="btn sm" href={`data:application/json,${encodeURIComponent(JSON.stringify(ready.ontology, null, 2))}`} download={`${ready.ontology.category}-${ready.ontology.version}.json`}>Ontology ↓</a>
                  <a className="btn sm" href={`data:application/json,${encodeURIComponent(JSON.stringify(ready.audiences, null, 2))}`} download="audiences.json">Audiences ↓</a>
                  {!saved
                    ? <button className="btn primary sm" onClick={saveOntology}>Save ontology</button>
                    : <span className="chip ok"><span className="dot" />saved {ready.ontology.category}@{ready.ontology.version}</span>}
                  <button className="btn primary sm" disabled={!saved && ready.action !== "reused"} onClick={openLaunch}>Open launch form →</button>
                  <button className="btn quiet sm" onClick={() => setReady(null)}>Back to editing</button>
                </div>
                {!saved && ready.action !== "reused" && <div className="help">Save the new version first — past studies keep resolving to what they ran on, so versions are never overwritten.</div>}
              </div>
            </div>
          )}
          {turns.length > 0 && (
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel-head"><h2>Conversation</h2><span className="hint">how each message was matched</span></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                {turns.map((t, i) => (
                  <div key={i} style={{ fontSize: 12.5 }}>
                    <div><b>You:</b> {t.text}</div>
                    {t.matched.length > 0 && <div className="sub" style={{ marginTop: 2 }}>Matched: {t.matched.join("; ")}</div>}
                    {t.missing.map((u, j) => (
                      <div key={j} className="sub" style={{ marginTop: 2 }}>Could not find <b>&quot;{u.phrase}&quot;</b> — {u.missing}</div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Audiences</h2><span className="hint">{shareTotal > 0 ? `${Math.round(shareTotal * 100)}% of 100%` : "authored by hand until drafting lands"}</span></div>
            <div className="panel-body" style={{ display: "grid", gap: 10 }}>
              {audiences.length === 0 && <div className="empty"><b>No audiences yet.</b>Find attributes below and describe who belongs.</div>}
              {audiences.map((a, ai) => {
                const head = preview?.audiences?.[ai];
                return (
                  <div key={ai} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input className="input" style={{ width: 160 }} value={a.name} onChange={(e) => setAudiences((as) => as.map((x, i) => (i === ai ? { ...x, name: e.target.value } : x)))} />
                      <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
                        <input className="input mono" style={{ width: 60 }} value={a.share === null ? "" : Math.round(a.share * 100)} placeholder="%" onChange={(e) => setAudiences((as) => as.map((x, i) => (i === ai ? { ...x, share: e.target.value === "" ? null : Number(e.target.value) / 100 } : x)))} /> share %
                      </label>
                      <button className="btn quiet sm" style={{ marginLeft: "auto" }} onClick={() => setAudiences((as) => as.filter((_, i) => i !== ai))}>✕</button>
                    </div>
                    {a.share === null && <div className="sub" style={{ fontSize: 12, marginTop: 4 }}>This group still needs its share.</div>}
                    {(a.changes ?? []).length > 0 && <div><span className="tag">changed from what you asked</span></div>}
                    {(a.changes ?? []).map((c, ci) => (
                      <div key={ci} className="sub" style={{ fontSize: 12, marginTop: 4 }}>
                        {c.attribute} moved to a description: {c.before.toLocaleString("en-US")} → {c.after.toLocaleString("en-US")} people.
                        {!c.accepted && <><button className="btn sm" style={{ marginLeft: 6 }} onClick={() => acceptChange(ai, ci)}>Accept</button><button className="btn quiet sm" style={{ marginLeft: 4 }} onClick={() => undoChange(ai, ci)}>Undo</button></>}
                      </div>
                    ))}
                    {head && (
                      <div className="sub" style={{ fontSize: 12.5, marginTop: 6 }}>
                        {head.head_count.toLocaleString("en-US")} people — needs {head.quota.toLocaleString("en-US")}
                        <span className="mono" style={{ fontSize: 11, marginLeft: 8 }}>
                          {Object.entries(head.by_source).map(([s, n]) => `${s} ${n.toLocaleString("en-US")}`).join(" · ")}
                        </span>
                      </div>
                    )}
                    {preview?.state === "building" && <div className="help">Counting…</div>}
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                      {Object.entries(a.filters).map(([attr, values]) => {
                        const row = rows.find((r) => r.id === attr);
                        const open = pickerFor?.ai === ai && pickerFor?.attr === attr;
                        return (
                          <span key={attr}>
                            <button className="tag" onClick={() => setPickerFor(open ? null : { ai, attr })}>
                              <span className="mono">{attr}</span> = {values.join(" / ")}
                              <span className="sub" style={{ fontSize: 11 }}> · measures: {row?.measures ?? "—"}</span>
                            </button>
                            <button className="btn quiet sm" style={{ marginLeft: 4 }} onClick={() => setAudiences((as) => as.map((x, i) => (i === ai ? { ...x, filters: Object.fromEntries(Object.entries(x.filters).filter(([k]) => k !== attr)) } : x)))}>✕</button>
                          </span>
                        );
                      })}
                      {rows.filter((r) => !a.filters[r.id]).length > 0 && (
                        <select className="input" style={{ width: 200 }} defaultValue="" onChange={(e) => {
                          const row = rows.find((r) => r.id === e.target.value);
                          if (row && row.values.length) setAudiences((as) => as.map((x, i) => (i === ai ? { ...x, filters: { ...x.filters, [row.id]: [row.values[0]] } } : x)));
                          e.target.value = "";
                        }}>
                          <option value="" disabled>+ filter</option>
                          {rows.filter((r) => !a.filters[r.id]).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                        </select>
                      )}
                    </div>
                    {questions.map((q, qi) => q.applies_to.includes(a.name) && (
                      <div key={qi} style={{ border: "1px dashed var(--line)", borderRadius: "var(--r-md)", padding: 10, marginTop: 6 }}>
                        <div style={{ fontSize: 12.5 }}>I wasn&apos;t sure what you meant by <b>&quot;{q.phrase}&quot;</b>:</div>
                        {q.choices.map((c, ci) => (
                          <div key={ci} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, padding: "2px 0" }}>
                            <span><b>{c.label}</b> <span className="mono sub" style={{ fontSize: 11 }}>{c.attribute} = {(c.values ?? []).join(" / ")}</span></span>
                            <span className="mono sub" style={{ fontSize: 11 }}>{(c.n_alone ?? 0).toLocaleString("en-US")} people</span>
                            <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => answerQuestion(qi, c)}>Use this</button>
                          </div>
                        ))}
                        <div><button className="btn quiet sm" onClick={() => answerQuestion(qi, null)}>Neither — leave it out</button></div>
                      </div>
                    ))}
                    {pickerFor?.ai === ai && picker && picker.id === pickerFor.attr && (
                      <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10, marginTop: 6 }}>
                        <div className="sub" style={{ fontSize: 12, marginBottom: 6 }}>Tick values — nothing here is typed.</div>
                        {(picker.values ?? []).map((v) => (
                          <label key={v.value} style={{ fontSize: 12.5, display: "flex", gap: 6, alignItems: "center", padding: "2px 0" }}>
                            <input type="checkbox" checked={(a.filters[picker.id] ?? []).includes(v.value)} onChange={() => toggleValue(ai, picker.id, v.value)} />
                            {v.value}
                            <span className="mono sub" style={{ fontSize: 11, marginLeft: "auto" }}>
                              {v.n.toLocaleString("en-US")} · {Object.entries(v.by_source).map(([s, n]) => `${s} ${n.toLocaleString("en-US")}`).join(" · ")}
                            </span>
                          </label>
                        ))}
                        {(picker.also_asks ?? []).length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <div className="sub" style={{ fontSize: 12, marginBottom: 4 }}>The corpus also asks this as</div>
                            {(picker.also_asks ?? []).map((alt) => (
                              <div key={alt.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, padding: "2px 0" }}>
                                <span><b>{alt.label}</b> <span className="mono sub" style={{ fontSize: 11 }}>{alt.id}</span></span>
                                <span className="mono sub" style={{ fontSize: 11 }}>{alt.n.toLocaleString("en-US")} answered</span>
                                <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => swapFilter(ai, picker.id, alt)}>Swap</button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {a.descriptions.length > 0 && <div className="sub" style={{ fontSize: 12, marginTop: 4 }}>Describes (excludes nobody): {a.descriptions.join(", ")}</div>}
                    {head?.dominant_source && <div className="sub" style={{ fontSize: 12, marginTop: 4 }}>Drawn mostly from {head.dominant_source} — a difference from other audiences may be a difference between surveys.</div>}
                    {head && Object.entries(head.filter_costs).map(([attr, without]) => (
                      head.head_count > 0 && without >= head.head_count * 2 && (
                        <div key={attr} className="sub" style={{ fontSize: 12, marginTop: 4 }}>
                          Removing {attr} would grow {head.head_count.toLocaleString("en-US")} → {without.toLocaleString("en-US")}.
                          <button className="btn sm" style={{ marginLeft: 6 }} onClick={() => moveToDescription(ai, attr)}>Use as a description instead</button>
                        </div>
                      )
                    ))}
                    {head && head.head_count < head.quota && Object.keys(head.text_would_add ?? {}).length > 0 && (
                      <div className="sub" style={{ fontSize: 12, marginTop: 4 }}>
                        Surveyed people can&apos;t fill this. {Object.entries(head.text_would_add).map(([s, n]) => `${s} would add ${n.toLocaleString("en-US")}`).join(" and ")} — their answers were read by a model from text, not given by them. Tick them under <i>Draw from</i> to use them; that is recorded in the brief&apos;s assumptions.
                      </div>
                    )}
                    {head?.empty_note && <div className="sub" style={{ fontSize: 12, marginTop: 4 }}>{head.empty_note}</div>}
                  </div>
                );
              })}
              <div><button className="btn sm" onClick={addAudience}>+ Add audience</button></div>
            </div>
          </div>
          {(preview?.assumptions ?? []).length > 0 && (
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel-head"><h2>Assumptions written to the brief</h2></div>
              <div className="panel-body" style={{ display: "grid", gap: 6 }}>
                {(preview?.assumptions ?? []).map((a, i) => (
                  <div key={i} className="sub" style={{ fontSize: 12.5 }}>assumed — {a.text}</div>
                ))}
              </div>
            </div>
          )}
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
                    {r.locked && <span className="tag">category — locked</span>}
                    {!r.locked && <button className="btn quiet sm" style={{ marginLeft: "auto" }} onClick={() => setRows((xs) => xs.filter((x) => x.id !== r.id))}>✕</button>}
                  </div>
                  <div className="sub" style={{ fontSize: 11.5 }}>{r.role} · {r.kind}</div>
                  {!r.locked && (
                    <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center", marginTop: 4 }}>
                      <input type="checkbox" checked={r.required} onChange={() => setRows((xs) => xs.map((x) => (x.id === r.id ? { ...x, required: !x.required } : x)))} /> required for everyone
                    </label>
                  )}
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
                        : <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                          <button className="btn sm" onClick={() => addAttr(h, false)}>+ Describe</button>
                          <button className="btn sm" onClick={() => addAttr(h, true)}>+ Require</button>
                        </span>}
                    </div>
                    <div className="sub" style={{ fontSize: 11.5, marginTop: 4 }}>{h.category} · measures: {h.measures} · {h.kind}</div>
                    {(h.relevance !== undefined && h.relevance !== null) && <div className="sub" style={{ fontSize: 11.5 }}>match {h.relevance.toFixed(2)}</div>}
                    {(h.present !== undefined && h.total !== undefined) && (
                      <div className="mono sub" style={{ fontSize: 11, marginTop: 2 }}>
                        answered by {h.present.toLocaleString("en-US")} of {h.total.toLocaleString("en-US")} · {Object.entries(h.carry_by_source ?? {}).map(([s, n]) => `${s} ${n.toLocaleString("en-US")}`).join(" · ")}
                      </div>
                    )}
                    {h.if_required && (
                      <div className="sub" style={{ fontSize: 11.5 }}>requiring keeps {(h.if_required.pool ?? 0).toLocaleString("en-US")} in the pool{(h.if_required.wiped_sources ?? []).length > 0 && <> — empties {(h.if_required.wiped_sources ?? []).join(", ")}</>}</div>
                    )}
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
      {category && (
        <div style={{ position: "sticky", bottom: 0, padding: "10px 0 4px", background: "var(--bg)" }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              placeholder="Add a group, or tell me more — e.g. “add students”, “all of them in North America”"
              value={followup}
              onChange={(e) => setFollowup(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") sendFollowup(); }}
              style={{ flex: 1 }}
            />
            <button className="btn primary sm" disabled={followingUp || !followup.trim()} onClick={sendFollowup}>{followingUp ? "…" : "Send"}</button>
          </div>
        </div>
      )}
    </Shell>
  );
}
