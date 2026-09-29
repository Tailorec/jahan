"use client";

import Link from "next/link";
import React from "react";
import { dump } from "js-yaml";
import Shell from "@/components/shell";
import { useSessionState } from "@/lib/session";
import { api, ApiError, useApi, whyNot } from "@/lib/api";
import { DOMAIN_WORDS, type AudienceSet } from "@/lib/engine";
import { SOURCE_COLORS as COLORS, SOURCE_NAMES as NAMES, SURVEYS, TEXT_SOURCES } from "@/lib/sources";
import "./who.css";

/* Who you study — the mockup's page (mockups/ontology/index.html) on the engine's own routes. Every count
   here is the engine's: this page lays them out and keeps what the person chose, nothing more. */

const PRESETS = [
  { label: "All surveys", sources: SURVEYS },
  { label: "US public", sources: ["gss"] },
  { label: "Developers", sources: ["stackoverflow"] },
];
const EXAMPLES = [
  "A children's education savings app. Three groups: parents of young kids (40%), people early in their career (30%) and retirees (30%), all in North America. I care about how careful they are with money and how much they trust technology.",
  "An AI code-review tool. Software developers who use AI coding assistants every day, compared with developers who never use them. I want to know how much they trust AI output.",
  "A premium meal-kit subscription. Busy parents who work full time, compared with retirees who cook every day. I want to know how price-sensitive they are.",
];

interface Status { endpoint_configured: boolean }
interface Corpus { people: Record<string, number>; answered: Record<string, number>; attributes: number; text_sources: string[] }
interface Pool { state: string; sources_total?: number; pool?: number; pool_by_source?: Record<string, number>; costs?: { attribute: string; removes: number; emptied_sources: string[] }[]; corpus?: Corpus }
interface Entry { id: string; label: string; category: string; domain: string; measures: string; values: string[]; ordered?: boolean; required?: boolean; locked?: boolean; role?: string; phrase?: string | null }
interface Row extends Entry { required: boolean; locked: boolean; role: string; ordered: boolean; guessed: boolean }
interface Option { id: string; label: string; carried?: number }
interface Change { attribute: string; values: string[]; before: number; after: number; accepted: boolean }
interface Audience { name: string; share: number | null; filters: Record<string, string[]>; descriptions: string[]; changes: Change[]; options: Record<string, Option[]> }
interface Choice { attribute: string; label: string; values: string[]; n_alone: number; entry?: Entry; options?: Option[] }
interface Question { phrase: string; choices: Choice[]; applies_to: string[] }
interface Head { name: string; quota: number; head_count: number; by_source: Record<string, number>; dominant_source: string | null; filter_costs: Record<string, number>; empty_note: string | null; text_would_add: Record<string, number> }
interface Preview { state: string; audiences?: Head[]; assumptions?: { text: string; source: string }[] }
interface Reading { product: string | null; groups: { name: string; share: number | null; traits: string[] }[]; everyone: string[]; topics: string[] }
interface Category { id: string; version: string; products: string[] }
interface Described { reading: Reading; product: string | null; match: Category | null; new_id: string; categories: Category[] }
interface Chosen { mode: "reuse" | "new"; id: string; version: string | null }
interface Matched { phrase: string; attribute?: string; values?: string[]; unsure?: boolean; describes?: boolean }
interface Turn { text: string; phase: "reading" | "confirm" | "drafting" | "done" | "error"; described?: Described; error?: string; added?: number; matched?: Matched[]; missing?: { phrase: string; missing: string }[]; ms?: number }
interface Values { state: string; id: string; label: string; values: { value: string; n: number; by_source: Record<string, number> }[]; also_asks: (Entry & { n: number })[] }
interface Picker { ai: number; attr: string; pending: string[] | null; data: Values | null; declare?: Entry; replaces?: string }
interface Hit extends Entry { present?: number; share?: number; carry_by_source?: Record<string, number>; if_required?: { pool: number; lost: Record<string, number> | number; wiped_sources: string[] } }
interface Ready { ontology: { category: string; version: string } & Record<string, unknown>; audiences: { name: string; share: number | null; attribute_filters: Record<string, string | string[]> }[]; assumptions: { text: string; source: string }[]; action: "reused" | "new_version" | "new_category"; from_version: string | null }

// A category is named in lower case, digits and underscores — the form its folder and every study pin take.
const categoryId = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
const fmt = (n: number | undefined) => (n ?? 0).toLocaleString("en-US");
const pct = (x: number) => (x === 0 ? "0%" : x < 0.01 ? `${(x * 100).toFixed(2)}%` : `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`);
const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const rowOf = (e: Entry): Row => ({ ...e, required: !!e.required, locked: !!e.locked, role: e.role ?? "added", ordered: !!e.ordered, guessed: !!e.ordered && !e.locked });
const feels = (measures?: string) => !!measures && measures.startsWith("how people feel");

function SourceBar({ bySource }: { bySource: Record<string, number> }) {
  const entries = Object.entries(bySource).sort((a, b) => b[1] - a[1]);
  const sum = entries.reduce((t, [, n]) => t + n, 0) || 1;
  return (
    <>
      <div className="bar">{entries.map(([s, n]) => <span key={s} style={{ width: `${(n / sum) * 100}%`, background: COLORS[s] }} />)}</div>
      <div className="legend">{entries.slice(0, 4).map(([s, n]) => <span key={s}><span className="swatch" style={{ background: COLORS[s] }} />{s} {pct(n / sum)}</span>)}</div>
    </>
  );
}

function Measures({ measures }: { measures?: string }) {
  if (!measures) return null;
  return <span className={`m${feels(measures) ? " feel" : ""}`}>measures: {measures}</span>;
}

export default function WhoPage() {
  const { data: status } = useApi<Status>("/api/status");
  const [sources, setSources] = useSessionState<string[]>("who:sources", SURVEYS);
  const [studySize, setStudySize] = useSessionState("who:studySize", 200);
  const [pool, setPool] = React.useState<Pool | null>(null);
  const [corpusMissing, setCorpusMissing] = React.useState(false);

  const [text, setText] = useSessionState("who:text", "");
  const [turns, setTurns] = useSessionState<Turn[]>("who:turns", [], (saved) => saved.map((t) => (
    // A reload ends a request in flight: say so, rather than spin for ever.
    t.phase === "reading" || t.phase === "drafting" ? { ...t, phase: "error" as const, error: "Interrupted by a reload — send it again." } : t)));
  const [category, setCategory] = useSessionState<Chosen | null>("who:category", null);
  const [rows, setRows] = useSessionState<Row[]>("who:rows", []);
  const [audiences, setAudiences] = useSessionState<Audience[]>("who:audiences", []);
  const [questions, setQuestions] = useSessionState<Question[]>("who:questions", []);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [blockers, setBlockers] = React.useState<string[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [followup, setFollowup] = useSessionState("who:followup", "");
  const [byHand, setByHand] = useSessionState<{ categories: Category[]; newId: string } | null>("who:byHand", null);

  const [picker, setPicker] = React.useState<Picker | null>(null);
  const [addingTo, setAddingTo] = React.useState<number | null>(null);
  const [searchOpen, setSearchOpen] = useSessionState("who:searchOpen", false);
  const [query, setQuery] = useSessionState("who:query", "");
  const [hits, setHits] = React.useState<Hit[] | null>(null);
  const [searchNote, setSearchNote] = React.useState<string | null>(null);

  const [ready, setReady] = useSessionState<Ready | null>("who:ready", null);
  const [setName, setSetName] = useSessionState("who:setName", "");
  const [newName, setNewName] = useSessionState("who:newName", "");
  const [categoryName, setCategoryName] = useSessionState("who:categoryName", "");
  const [ontologySaved, setOntologySaved] = useSessionState("who:ontologySaved", false);
  const [savedSet, setSavedSet] = useSessionState<AudienceSet | null>("who:savedSet", null);
  const { data: savedSets } = useApi<{ audience_sets: AudienceSet[] }>("/api/audience-sets");
  const [continueError, setContinueError] = React.useState<string | null>(null);

  const reused = category?.mode === "reuse";
  const required = rows.filter((r) => r.required).map((r) => r.id);
  const row = (id: string) => rows.find((r) => r.id === id);
  const label = (id: string) => row(id)?.label ?? id;
  const heads = preview?.audiences ?? [];
  const noEndpoint = status !== null && !status.endpoint_configured;

  // ---------------------------------------------------------------- the engine's counts
  const poolKey = JSON.stringify({ sources, required });
  React.useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = () => post<Pool>("/api/pool", JSON.parse(poolKey)).then((p) => {
      if (!live) return;
      setPool(p);
      setCorpusMissing(false);
      if (p.state === "building") timer = setTimeout(ask, 3000);
    }).catch((e) => { if (live) { setPool(null); setCorpusMissing(e instanceof ApiError && e.status === 409); } });
    ask();
    return () => { live = false; clearTimeout(timer); };
  }, [poolKey]);

  const previewKey = JSON.stringify({ sources, required, study_size: studySize, audiences: audiences.map((a) => ({ name: a.name, share: a.share, filters: a.filters })) });
  React.useEffect(() => {
    const body = JSON.parse(previewKey);
    if (!body.audiences.length) { setPreview(null); return; }
    let live = true;
    post<Preview>("/api/audiences/preview", body).then((p) => { if (live) setPreview(p); }).catch(() => { if (live) setPreview(null); });
    return () => { live = false; };
  }, [previewKey]);

  const blockersKey = JSON.stringify({
    category,
    questions: questions.map((q) => ({ phrase: q.phrase, applies_to: q.applies_to })),
    changes: audiences.flatMap((a) => a.changes),
    audiences: audiences.map((a) => ({ name: a.name, share: a.share })),
    previews: heads.map((h) => ({ quota: h.quota, head_count: h.head_count })),
  });
  React.useEffect(() => {
    let live = true;
    api<{ blockers: string[] }>("/api/who/blockers", { method: "POST", headers: { "content-type": "application/json" }, body: blockersKey })
      .then((d) => { if (live) setBlockers(d.blockers); }).catch(() => { if (live) setBlockers(null); });
    return () => { live = false; };
  }, [blockersKey]);

  // ---------------------------------------------------------------- find more attributes
  React.useEffect(() => {
    if (!searchOpen || !query.trim()) { setHits(null); return; }
    let live = true;
    const t = setTimeout(() => {
      const q = new URLSearchParams({ query, limit: "8", mode: "meaning", sources: sources.join(","), required: required.join(",") });
      api<{ attributes: Hit[]; mode: string; meaning_note: string }>(`/api/codebook?${q}`)
        .then((d) => { if (live) { setHits(d.attributes); setSearchNote(d.meaning_note || null); } })
        .catch((e) => { if (live) { setHits([]); setSearchNote(whyNot(e)); } });
    }, 280);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchOpen, query, poolKey]);

  // ---------------------------------------------------------------- keeping the draft
  function declare(entries: Entry[]) {
    setRows((rs) => {
      const next = [...rs];
      for (const e of entries) if (e && !next.some((r) => r.id === e.id)) next.push(rowOf({ ...e, required: reused ? false : e.required }));
      // The conditioning set leads the order, as the file will hold it.
      return [...next.filter((r) => r.required), ...next.filter((r) => !r.required)];
    });
  }

  async function fit(list: Audience[], requiredNow: string[]) {
    try {
      const d = await post<{ state: string; audiences: { name: string; filters: Record<string, string[]>; descriptions: string[]; changes: Change[] }[] }>("/api/draft/fit", {
        sources, required: requiredNow, study_size: studySize, audiences: list.map((a) => ({ name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions })),
      });
      if (d.state !== "ready") return;
      // Fitting only ever adds changes: what the person already accepted stays accepted.
      setAudiences(list.map((a, i) => (d.audiences[i] ? { ...a, filters: d.audiences[i].filters, descriptions: d.audiences[i].descriptions, changes: [...a.changes, ...d.audiences[i].changes] } : a)));
    } catch { /* best effort: Continue still names what is short */ }
  }

  function patchTurn(i: number, patch: Partial<Turn>) {
    setTurns((ts) => ts.map((t, k) => (k === i ? { ...t, ...patch } : t)));
  }

  async function readIt(value: string) {
    const said = value.trim();
    if (!said || busy) return;
    setBusy(true);
    setTurns([{ text: said, phase: "reading" }]);
    try {
      const described = await post<Described>("/api/describe", { text: said });
      setNewName(described.new_id);
      patchTurn(0, { phase: "confirm", described });
    } catch (e) {
      patchTurn(0, { phase: "error", error: whyNot(e) });
    }
    setBusy(false);
  }

  async function chooseCategory(chosen: Chosen, fromText: boolean, loaded?: AudienceSet) {
    const first = turns[0];
    setCategory(chosen);
    setBusy(true);
    if (fromText) patchTurn(0, { phase: "drafting" });
    const started = Date.now();
    try {
      const reading = fromText ? first.described!.reading : { product: null, groups: [], everyone: [], topics: [] };
      const d = await post<{ state: string; audiences: (Omit<Audience, "changes" | "options"> & { phrases: Record<string, string>; options: Record<string, Option[]> })[]; attributes: Entry[]; questions: Question[]; unmatched: { phrase: string; missing: string }[] }>(
        "/api/draft", { text: fromText ? first.text : "", reading, category: chosen, sources },
      );
      if (d.state !== "ready") throw new Error("the persona matrix is still building — try again in a minute");
      const drafted = d.attributes.map(rowOf);
      const ordered = [...drafted.filter((r) => r.required), ...drafted.filter((r) => !r.required)];
      setRows(ordered);
      const list: Audience[] = loaded
        ? loaded.audiences.map((a) => ({
          name: a.name, share: a.share, descriptions: [], changes: [], options: {},
          filters: Object.fromEntries(Object.entries(a.attribute_filters).map(([k, v]) => [k, Array.isArray(v) ? v : [String(v)]])),
        }))
        : d.audiences.map((a) => ({ name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions ?? [], changes: [], options: a.options ?? {} }));
      setAudiences(list);
      setQuestions(d.questions);
      if (fromText) {
        const matched: Matched[] = [];
        for (const a of d.audiences) for (const [attribute, phrase] of Object.entries(a.phrases ?? {})) {
          if (!matched.some((m) => m.phrase === phrase)) matched.push({ phrase, attribute, values: a.filters[attribute] });
        }
        for (const q of d.questions) matched.push({ phrase: q.phrase, unsure: true });
        for (const e of d.attributes) if (e.role === "matters" && e.phrase) matched.push({ phrase: e.phrase, attribute: e.id, describes: true });
        patchTurn(0, { phase: "done", added: list.length, matched, missing: d.unmatched, ms: Date.now() - started });
      }
      if (list.length && !loaded) await fit(list, ordered.filter((r) => r.required).map((r) => r.id));
    } catch (e) {
      setCategory(null);
      if (fromText) patchTurn(0, { phase: "confirm", error: whyNot(e) });
      else setContinueError(whyNot(e));
    }
    setBusy(false);
  }

  async function sendFollowup() {
    const said = followup.trim();
    if (!said || busy) return;
    setBusy(true);
    setFollowup("");
    const at = turns.length;
    setTurns((ts) => [...ts, { text: said, phase: "drafting" }]);
    const started = Date.now();
    try {
      const d = await post<{ state: string; audiences: Audience[]; added: string[]; questions: Question[]; unmatched: { phrase: string; missing: string }[]; fits: Record<string, { attribute?: string; unsure?: boolean }>; attributes: Entry[] }>(
        "/api/draft/followup", { text: said, sources, audiences: audiences.map((a) => ({ name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions })) },
      );
      if (d.state !== "ready") throw new Error("the persona matrix is still building — try again in a minute");
      declare(d.attributes);
      const before = new Map(audiences.map((a) => [a.name, a]));
      const list: Audience[] = d.audiences.map((a) => ({
        name: a.name, share: a.share, filters: a.filters, descriptions: a.descriptions ?? [],
        changes: before.get(a.name)?.changes ?? [], options: before.get(a.name)?.options ?? {},
      }));
      setAudiences(list);
      setQuestions((qs) => [...qs, ...d.questions]);
      const matched: Matched[] = Object.entries(d.fits).map(([phrase, f]) => (f.unsure ? { phrase, unsure: true } : { phrase, attribute: f.attribute, values: list.find((a) => f.attribute && a.filters[f.attribute])?.filters[f.attribute!] }));
      patchTurn(at, { phase: "done", added: d.added.length, matched, missing: d.unmatched, ms: Date.now() - started });
      await fit(list, required);
    } catch (e) {
      patchTurn(at, { phase: "error", error: whyNot(e) });
    }
    setBusy(false);
  }

  function startByHand() {
    api<{ categories: Category[] }>("/api/categories")
      .then((d) => setByHand({ categories: d.categories, newId: "" }))
      .catch((e) => setContinueError(whyNot(e)));
  }

  function startOver() {
    if (!window.confirm("Start over? This clears the category, audiences and ontology.")) return;
    setTurns([]); setCategory(null); setRows([]); setAudiences([]); setQuestions([]); setPicker(null);
    setReady(null); setSavedSet(null); setOntologySaved(false); setByHand(null); setSearchOpen(false); setQuery(""); setContinueError(null);
  }

  // ---------------------------------------------------------------- editing audiences
  const updateAudience = (ai: number, change: (a: Audience) => Audience) => setAudiences((as) => as.map((a, i) => (i === ai ? change(a) : a)));

  function rename(ai: number, raw: string) {
    const old = audiences[ai].name;
    let name = raw.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "audience";
    while (audiences.some((a, i) => i !== ai && a.name === name)) name = `${name}_2`;
    updateAudience(ai, (a) => ({ ...a, name }));
    // A question asked of this audience is still asked of it under its new name.
    setQuestions((qs) => qs.map((q) => ({ ...q, applies_to: q.applies_to.map((n) => (n === old ? name : n)) })));
  }

  function dropAudience(ai: number) {
    const gone = audiences[ai].name;
    setAudiences((as) => as.filter((_, i) => i !== ai));
    setQuestions((qs) => qs.map((q) => ({ ...q, applies_to: q.applies_to.filter((n) => n !== gone) })).filter((q) => q.applies_to.length));
    setPicker(null);
  }

  function addAudience() {
    let name = "audience";
    for (let k = 2; audiences.some((a) => a.name === name); k++) name = `audience_${k}`;
    setAudiences((as) => [...as, { name, share: null, filters: {}, descriptions: [], changes: [], options: {} }]);
  }

  function answer(qi: number, choice: Choice | null) {
    const q = questions[qi];
    if (choice) {
      if (choice.entry) declare([choice.entry]);
      setAudiences((as) => as.map((a) => (q.applies_to.includes(a.name)
        ? { ...a, filters: { ...a.filters, [choice.attribute]: choice.values }, options: { ...a.options, [choice.attribute]: choice.options ?? [] } }
        : a)));
    }
    setQuestions((qs) => qs.filter((_, i) => i !== qi));
  }

  function acceptChange(ai: number, ci: number) {
    updateAudience(ai, (a) => ({ ...a, changes: a.changes.map((c, k) => (k === ci ? { ...c, accepted: true } : c)) }));
  }
  function undoChange(ai: number, ci: number) {
    updateAudience(ai, (a) => {
      const c = a.changes[ci];
      return { ...a, filters: { ...a.filters, [c.attribute]: c.values }, descriptions: a.descriptions.filter((d) => d !== c.attribute), changes: a.changes.filter((_, k) => k !== ci) };
    });
  }
  function describeInstead(ai: number, attr: string, head: Head) {
    updateAudience(ai, (a) => {
      const filters = { ...a.filters };
      delete filters[attr];
      return {
        ...a, filters, descriptions: a.descriptions.includes(attr) ? a.descriptions : [...a.descriptions, attr],
        changes: [...a.changes, { attribute: attr, values: a.filters[attr], before: head.head_count, after: head.filter_costs[attr], accepted: true }],
      };
    });
  }

  async function openPicker(ai: number, attr: string, declareIt?: Entry, replaces?: string) {
    setAddingTo(null);
    setPicker({ ai, attr, pending: null, data: null, declare: declareIt, replaces });
    try {
      const q = new URLSearchParams({ sources: sources.join(","), required: required.join(",") });
      const data = await api<Values>(`/api/codebook/${encodeURIComponent(attr)}/values?${q}`);
      setPicker((p) => (p && p.attr === attr ? { ...p, data } : p));
    } catch (e) {
      setPicker(null);
      setContinueError(whyNot(e));
    }
  }

  function applyPicker() {
    if (!picker) return;
    const { ai, attr, pending, declare: entry, replaces } = picker;
    if (pending && pending.length) {
      if (entry) declare([entry]);
      updateAudience(ai, (a) => {
        const filters = { ...a.filters };
        if (replaces) delete filters[replaces];
        return { ...a, filters: { ...filters, [attr]: pending } };
      });
    } else if (pending) {
      updateAudience(ai, (a) => { const filters = { ...a.filters }; delete filters[attr]; return { ...a, filters }; });
    }
    setPicker(null);
  }

  function toggleValue(value: string) {
    setPicker((p) => {
      if (!p || !p.data) return p;
      const current = new Set(p.pending ?? audiences[p.ai].filters[p.attr] ?? []);
      if (current.has(value)) current.delete(value); else current.add(value);
      return { ...p, pending: p.data.values.map((v) => v.value).filter((v) => current.has(v)) };
    });
  }

  // ---------------------------------------------------------------- the ontology table
  const updateRow = (id: string, patch: Partial<Row>) => setRows((rs) => {
    const next = rs.map((r) => (r.id === id ? { ...r, ...patch } : r));
    return [...next.filter((r) => r.required), ...next.filter((r) => !r.required)];
  });
  const usedBy = (id: string) => audiences.filter((a) => a.filters[id]).map((a) => a.name);
  function removeRow(r: Row) {
    const users = usedBy(r.id);
    if (users.length && !window.confirm(`${r.label} defines ${users.join(", ")}. Removing it removes that filter too. Continue?`)) return;
    setAudiences((as) => as.map((a) => {
      const filters = { ...a.filters };
      delete filters[r.id];
      return { ...a, filters, descriptions: a.descriptions.filter((d) => d !== r.id) };
    }));
    setRows((rs) => rs.filter((x) => x.id !== r.id));
  }

  // ---------------------------------------------------------------- continue
  // `renamed` continues under another name for a new category: every check runs again under it.
  async function continueIt(renamed?: Chosen) {
    const chosen = renamed ?? category;
    if (!chosen) return;
    setContinueError(null);
    try {
      const planned = await post<Ready>("/api/who/launch", {
        category: chosen,
        attributes: rows.map((r) => ({ id: r.id, domain: r.domain, required: r.required, ordered: r.ordered })),
        audiences: audiences.map((a) => ({ name: a.name, share: a.share, filters: a.filters })),
        assumptions: preview?.assumptions ?? [],
      });
      if (renamed) setCategory(renamed);
      setReady(planned);
      setCategoryName(planned.ontology.category);
      setSavedSet(null);
      setOntologySaved(false);
      setSetName(audiences.map((a) => a.name).join(" · "));
    } catch (e) {
      setContinueError(whyNot(e));
    }
  }

  // One save for what this page finishes with: the ontology version when it is new, then the audience set drafted against it.
  async function saveSet() {
    if (!ready) return;
    setContinueError(null);
    try {
      if (ready.action !== "reused" && !ontologySaved) {
        await post("/api/ontologies", { ontology: ready.ontology });
        setOntologySaved(true);
      }
      setSavedSet(await post<AudienceSet>("/api/audience-sets", {
        category: ready.ontology.category, ontology_version: ready.ontology.version,
        name: setName.trim() || ready.audiences.map((a) => a.name).join(" · "),
        description: turns[0]?.text ?? "", audiences: ready.audiences, assumptions: ready.assumptions,
        sources, study_size: studySize,
      }));
    } catch (e) {
      setContinueError(whyNot(e));
    }
  }

  function openLaunch() {
    if (savedSet) window.location.href = `/intake?set=${encodeURIComponent(savedSet.category)}/${encodeURIComponent(savedSet.id)}`;
  }

  // A saved set opens for editing against its category's ontology; saving the edit saves another set.
  async function openSet(ref: string) {
    try {
      const saved = await api<AudienceSet>(`/api/audience-sets/${ref.split("/").map(encodeURIComponent).join("/")}`);
      setSources(saved.sources);
      setStudySize(saved.study_size);
      await chooseCategory({ mode: "reuse", id: saved.category, version: saved.ontology_version }, false, saved);
    } catch (e) {
      setContinueError(whyNot(e));
    }
  }
  React.useEffect(() => {
    const ref = new URLSearchParams(window.location.search).get("set");
    if (!ref) return;
    // Opened once: a reload keeps the edits made since, rather than opening the saved set again.
    window.history.replaceState(null, "", "/who");
    openSet(ref);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------- sidebar
  const corpus = pool?.corpus;
  const shown = corpus ? Object.keys(corpus.people).sort((a, b) => corpus.people[b] - corpus.people[a]) : [...SURVEYS, ...TEXT_SOURCES];
  const stillBlocked = blockers ?? ["counting"];
  const sidebar = (
    <aside className="who-side">
      {category && (
        <div>
          <h3>Category</h3>
          <div className="catchip">{category.id}{category.version ? ` ${category.version}` : ""}</div>
          <div className="muted">{reused ? "reused — its required set is the category's, and stays as it is" : "new — requires the cross-survey core"}</div>
        </div>
      )}
      <div>
        <h3>Draw from</h3>
        <div className="presets">{PRESETS.map((p) => <button key={p.label} onClick={() => setSources(p.sources)}>{p.label}</button>)}</div>
        {shown.map((s) => (
          <label key={s} className="src">
            <input type="checkbox" checked={sources.includes(s)} onChange={() => setSources((xs) => (xs.includes(s) ? xs.filter((x) => x !== s) : [...xs, s]))} />
            <span>
              <span className="swatch" style={{ background: COLORS[s] }} />{NAMES[s] ?? s}
              <small>
                {corpus ? <>{fmt(corpus.people[s])} people · answered {fmt(corpus.answered[s])} of {fmt(corpus.attributes)} questions</> : null}
                {TEXT_SOURCES.includes(s) && <>{corpus ? " · " : ""}<b className="text-src">read by a model from text, not surveyed</b></>}
              </small>
            </span>
          </label>
        ))}
      </div>
      <div>
        <h3>Study size</h3>
        <label className="size">
          <input className="input mono" value={studySize} onChange={(e) => { const v = parseInt(e.target.value, 10); setStudySize(v > 0 ? v : 1); }} /> personas <span className="muted">— sets each audience&apos;s quota</span>
        </label>
      </div>
      <div>
        <h3>Candidate pool</h3>
        {pool?.state === "ready" && (
          <>
            <div className="big">{fmt(pool.pool)}</div>
            <div className="muted">{required.length ? <>of {fmt(pool.sources_total)} in your sources have every required answer</> : "everyone in your sources"}</div>
            {pool.pool ? <SourceBar bySource={pool.pool_by_source ?? {}} /> : <div className="note risk">Nobody has every required answer.</div>}
            <div style={{ marginTop: 8 }}>
              {(pool.costs ?? []).filter((c) => c.removes > 0).sort((a, b) => b.removes - a.removes).map((c) => (
                <div key={c.attribute} className="cost">
                  Requiring <b>{label(c.attribute)}</b> removes {fmt(c.removes)}
                  {c.emptied_sources.length > 0 && <> — <span style={{ color: "var(--risk)" }}>all of {c.emptied_sources.join(", ")}</span></>}
                </div>
              ))}
            </div>
          </>
        )}
        {pool?.state === "building" && <div className="muted"><span className="spin" />Counting who can be drawn — the matrix builds once, in the background…</div>}
        {corpusMissing && <div className="muted">No corpus cached here, so there is nobody to count yet.</div>}
      </div>
      <div className="continue">
        {turns.length + audiences.length > 0 && (
          <ul className="blockers">{[...(busy ? ["wait for the draft"] : []), ...(blockers ?? [])].map((b) => <li key={b}>{b}</li>)}</ul>
        )}
        <button className="btn primary" disabled={stillBlocked.length > 0 || busy || !!ready} onClick={() => continueIt()}>Continue to study →</button>
        {continueError && <div className="note risk">{continueError}</div>}
        {(turns.length > 0 || category) && <button className="btn quiet sm" style={{ width: "100%", justifyContent: "center", marginTop: 6 }} onClick={startOver}>Start over</button>}
      </div>
    </aside>
  );

  // ---------------------------------------------------------------- main column
  function turnView(t: Turn, i: number) {
    const bubble = <div className="bubble">{t.text}</div>;
    if (t.phase === "reading") return <div key={i} className="turn">{bubble}<div className="reply"><span className="spin" />Reading it and looking for its category…</div></div>;
    if (t.phase === "drafting") return <div key={i} className="turn">{bubble}<div className="reply"><span className="spin" />Finding the attributes and counting who exists…</div></div>;
    if (t.phase === "error") return <div key={i} className="turn">{bubble}<div className="reply" style={{ color: "var(--risk)" }}>{t.error}</div></div>;
    if (t.phase === "confirm" && t.described) return <div key={i} className="turn">{bubble}{confirmCard(t.described, t.error)}</div>;
    return (
      <div key={i} className="turn">{bubble}
        <div className="reply">
          {!!t.added && <div>Added <b>{t.added} audience{t.added > 1 ? "s" : ""}</b>.</div>}
          {(t.matched ?? []).length > 0 && (
            <div style={{ marginTop: 4 }}>How I matched your words:
              <ul>{(t.matched ?? []).map((m) => (
                <li key={m.phrase}>“{m.phrase}” → {m.unsure
                  ? <><b>not sure</b> — asked in the audience</>
                  : <><b>{label(m.attribute!)}</b>{m.values ? <>: {m.values.join(" / ")}</> : m.describes ? " (describes, excludes no one)" : ""} <span className="muted">(measures {row(m.attribute!)?.measures ?? "—"})</span></>}</li>
              ))}</ul>
            </div>
          )}
          {(t.missing ?? []).length > 0 && (
            <div style={{ marginTop: 4, color: "var(--risk)" }}>Could not find:
              <ul>{(t.missing ?? []).map((m) => <li key={m.phrase}>“{m.phrase}” — {m.missing}</li>)}</ul>
            </div>
          )}
          {t.ms !== undefined && <div className="muted" style={{ marginTop: 4 }}>{(t.ms / 1000).toFixed(1)} s · each phrase matched twice, with and without the rest of your description; where the two disagreed, you&apos;re asked</div>}
        </div>
      </div>
    );
  }

  function confirmCard(u: Described, error?: string) {
    const others = u.categories.filter((c) => !u.match || c.id !== u.match.id);
    const r = u.reading;
    return (
      <div className="card confirm" style={{ marginTop: 10 }}>
        <div style={{ fontSize: 14 }}>I read this as a study of <b>{u.product || "an unnamed product"}</b>, with:</div>
        <div className="reply" style={{ border: 0, padding: 0 }}>
          <ul>{r.groups.map((g) => <li key={g.name}><b>{g.name}</b>{g.share ? ` (${Math.round(g.share * 100)}%)` : ""}: {g.traits.join(", ") || <i>no traits</i>}</li>)}</ul>
          {r.everyone.length > 0 && <div>Everyone: {r.everyone.join(", ")}</div>}
          {r.topics.length > 0 && <div>You want to know (describes, excludes no one): {r.topics.join(", ")}</div>}
        </div>
        <div className="muted" style={{ marginTop: 6 }}>If something you meant is missing here, rephrase before going on — nothing has been drafted yet.</div>
        <div style={{ marginTop: 12, fontSize: 13.5 }}>
          {u.match
            ? <>Is it the same kind of product as <b className="catchip">{u.match.id}</b>{u.match.products.length ? ` (${u.match.products.join(", ")})` : ""}? Studies in one category share its ontology, so their results can be compared.</>
            : <>It doesn&apos;t look like any existing category{u.categories.length ? ` (${u.categories.map((c) => c.id).join(", ")})` : ""}.</>}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {u.match && <button className="btn primary" disabled={busy} onClick={() => chooseCategory({ mode: "reuse", id: u.match!.id, version: u.match!.version }, true)}>Yes — use its ontology ({u.match.version})</button>}
          <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
            <input className="input mono" aria-label="New category name" style={{ width: 210, fontSize: 12.5 }} value={newName} placeholder={u.new_id}
              onChange={(e) => setNewName(e.target.value)} />
            <button className={`btn${u.match ? "" : " primary"}`} disabled={busy || !categoryId(newName || u.new_id)}
              onClick={() => chooseCategory({ mode: "new", id: categoryId(newName || u.new_id), version: null }, true)}>Start a new category</button>
          </span>
          {others.length > 0 && (
            <select className="input" style={{ width: "auto", fontSize: 12.5 }} value="" disabled={busy} onChange={(e) => { const c = others.find((o) => o.id === e.target.value); if (c) chooseCategory({ mode: "reuse", id: c.id, version: c.version }, true); }}>
              <option value="">It&apos;s the same as…</option>
              {others.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
            </select>
          )}
          <button className="btn quiet" onClick={() => { setText(turns[0].text); setTurns([]); }}>Rephrase</button>
        </div>
        {u.categories.some((c) => c.id === categoryId(newName)) && (
          <div className="note warn">A category named <span className="catchip">{categoryId(newName)}</span> already exists: starting it here reuses that one. Choose another name for a new category.</div>
        )}
        {error && <div className="note risk">{error}</div>}
      </div>
    );
  }

  function heroView() {
    const people = corpus ? Object.values(corpus.people).reduce((t, n) => t + n, 0) : null;
    return (
      <div className="hero">
        <h1>Who do you want to study?</h1>
        <p>Describe them the way you&apos;d brief a researcher: what you&apos;re testing, one group or several, what makes someone belong, and what you want to know about them.</p>
        <div className="composer">
          <textarea rows={3} value={text} autoFocus disabled={noEndpoint} placeholder="e.g. A children's savings app. Parents of young kids in North America, compared with retirees…"
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); readIt(text); } }} />
          <button className="btn primary" disabled={busy || noEndpoint || !text.trim()} onClick={() => readIt(text)}>Read it</button>
        </div>
        {noEndpoint
          ? <div className="note plain" style={{ marginTop: 14 }}>Reading a description needs a language-model endpoint, and none is configured — search is by words and nothing is drafted. <button className="btn sm" onClick={startByHand}>Author audiences by hand</button></div>
          : <div className="examples">{EXAMPLES.map((e) => <button key={e} onClick={() => setText(e)}>{e}</button>)}</div>}
        {(savedSets?.audience_sets ?? []).length > 0 && (
          <div style={{ marginTop: 18 }}>
            <div className="muted" style={{ marginBottom: 6 }}>Or open a saved audience set to change it:</div>
            <div className="examples" style={{ marginTop: 0 }}>
              {(savedSets?.audience_sets ?? []).slice(0, 5).map((set) => (
                <button key={set.id} disabled={busy} onClick={() => openSet(`${set.category}/${set.id}`)}>
                  <b>{set.name}</b> <span className="muted">· {set.category} {set.ontology_version} · {set.created_at.slice(0, 10)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {corpusMissing && <div className="note risk" style={{ marginTop: 14 }}>No corpus cached here, so there is nobody to count: author freely, then continue where the corpus is present.</div>}
        <div className="fineprint">{corpus && people !== null ? <>Matched against {fmt(corpus.attributes)} attributes answered by {fmt(people)} people. </> : null}Every count you see is real; nothing is guessed.</div>
      </div>
    );
  }

  function byHandView() {
    const pick = byHand!;
    return (
      <div className="hero">
        <h1>Which category is it?</h1>
        <p>Studies in one category share its ontology, so their results can be compared. Reuse one, or start a new category that requires the cross-survey core.</p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {pick.categories.map((c) => <button key={c.id} className="btn" disabled={busy} onClick={() => chooseCategory({ mode: "reuse", id: c.id, version: c.version }, false)}><span className="catchip">{c.id}</span> {c.version}</button>)}
        </div>
        <div className="composer" style={{ marginTop: 14 }}>
          <input className="input mono" style={{ flex: 1, border: 0 }} placeholder="new_category_id" value={pick.newId} onChange={(e) => setByHand({ ...pick, newId: e.target.value.toLowerCase().replace(/[^a-z0-9_]+/g, "_") })} />
          <button className="btn primary" disabled={busy || !pick.newId.replace(/_/g, "")} onClick={() => chooseCategory({ mode: "new", id: pick.newId.replace(/^_+|_+$/g, ""), version: null }, false)}>Start a new category</button>
        </div>
        <button className="btn quiet sm" style={{ marginTop: 10, alignSelf: "flex-start" }} onClick={() => setByHand(null)}>← Back</button>
      </div>
    );
  }

  function pickerView(a: Audience) {
    const p = picker!;
    if (!p.data) return <div className="picker"><span className="spin" />counting who holds each answer…</div>;
    const current = new Set(p.pending ?? a.filters[p.attr] ?? []);
    const max = Math.max(1, ...p.data.values.map((v) => v.n));
    return (
      <div className="picker">
        <div className="muted" style={{ marginBottom: 6 }}>{p.data.label} — who holds each answer, among the candidate pool. Tick values; nothing here is typed.</div>
        <table className="vt"><tbody>{p.data.values.map((v) => (
          <tr key={v.value}>
            <td style={{ width: 24 }}><input type="checkbox" checked={current.has(v.value)} onChange={() => toggleValue(v.value)} /></td>
            <td>{v.value}</td>
            <td><div className="mini">{Object.entries(v.by_source).map(([s, n]) => <span key={s} style={{ width: `${(n / max) * 100}%`, background: COLORS[s] }} />)}</div></td>
            <td className="n">{fmt(v.n)}</td>
          </tr>
        ))}</tbody></table>
        {p.data.also_asks.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div className="muted">The corpus also asks this as — choose one to use instead:</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
              {p.data.also_asks.slice(0, 5).map((o) => (
                <button key={o.id} className="btn sm" onClick={() => openPicker(p.ai, o.id, o, p.replaces ?? p.attr)}>
                  {o.label} <span className="muted">· {fmt(o.n)} answered · {o.measures}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button className="btn primary sm" onClick={applyPicker}>Apply</button>
          {a.filters[p.attr] && <button className="btn sm danger" onClick={() => { updateAudience(p.ai, (x) => { const filters = { ...x.filters }; delete filters[p.attr]; return { ...x, filters }; }); setPicker(null); }}>Remove filter</button>}
          <button className="btn quiet sm" onClick={() => setPicker(null)}>Cancel</button>
        </div>
      </div>
    );
  }

  function audienceView(a: Audience, ai: number) {
    const h = heads[ai];
    const n = h?.head_count ?? 0;
    const q = h?.quota ?? Math.ceil(studySize * (a.share ?? 1 / Math.max(1, audiences.length)));
    const asked = questions.map((x, qi) => ({ x, qi })).filter(({ x }) => x.applies_to.includes(a.name));
    const shrinkers = h ? Object.entries(h.filter_costs).filter(([, without]) => n > 0 && without > n * 3).sort((x, y) => y[1] - x[1]) : [];
    const adds = h ? Object.entries(h.text_would_add).filter(([, k]) => k > 0) : [];
    const total = h ? Object.values(h.by_source).reduce((t, k) => t + k, 0) : 0;
    const dominant = h?.dominant_source;
    return (
      <div key={ai} className="card">
        <div className="aud-head">
          <input className="name" size={Math.max(12, a.name.length + 2)} defaultValue={a.name} key={a.name} onBlur={(e) => { if (e.target.value !== a.name) rename(ai, e.target.value); }} />
          <span className="share">
            <input className={`input mono${a.share === null ? " missing" : ""}`} key={`${a.name}-${a.share}`} defaultValue={a.share !== null ? Math.round(a.share * 1000) / 10 : ""} placeholder="?"
              onBlur={(e) => { const v = parseFloat(e.target.value); updateAudience(ai, (x) => ({ ...x, share: Number.isNaN(v) ? null : v / 100 })); }} />%
          </span>
          {a.changes.length > 0 && <span className="badge">changed from what you asked</span>}
          <div className="count">
            <div className="n">{h ? fmt(n) : "—"}</div>
            <div className="muted">{asked.length ? "match so far — not counting the question below" : "people match"} · needs {fmt(q)}</div>
          </div>
          <button className="btn quiet sm" title="remove audience" onClick={() => dropAudience(ai)}>✕</button>
        </div>
        <div className="filters">
          {Object.entries(a.filters).map(([id, values]) => (
            <button key={id} className={`fchip${picker?.ai === ai && picker.attr === id ? " open" : ""}`} onClick={() => (picker?.ai === ai && picker.attr === id ? setPicker(null) : openPicker(ai, id))}>
              <span>{label(id)}: <span className="v">{values.join(" / ")}</span></span><Measures measures={row(id)?.measures} />
            </button>
          ))}
          {addingTo === ai
            ? (
              <select className="input" style={{ fontSize: 12, width: "auto" }} autoFocus defaultValue="" onBlur={() => setAddingTo(null)} onChange={(e) => {
                if (e.target.value === "__search") { setAddingTo(null); setSearchOpen(true); return; }
                if (e.target.value) openPicker(ai, e.target.value);
              }}>
                <option value="">choose an attribute…</option>
                {rows.filter((r) => !a.filters[r.id]).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                <option value="__search">search for another…</option>
              </select>
            )
            : <button className="addf" onClick={() => setAddingTo(ai)}>+ filter</button>}
        </div>
        {picker?.ai === ai && pickerView(a)}
        {asked.map(({ x, qi }) => (
          <div key={x.phrase} className="ask"><b>I wasn&apos;t sure what you meant by “{x.phrase}”.</b> Which is it?
            <div className="choices">
              {x.choices.map((c) => (
                <button key={c.attribute} className="btn sm" onClick={() => answer(qi, c)}>
                  <span>{c.label}: <b>{c.values.join(" / ")}</b></span>
                  <small>{fmt(c.n_alone)} people{c.entry ? ` · measures ${c.entry.measures}` : ""}</small>
                </button>
              ))}
              <button className="btn sm quiet" onClick={() => answer(qi, null)}>Neither — leave it out</button>
            </div>
          </div>
        ))}
        {n > 0 && h && <SourceBar bySource={h.by_source} />}
        {h && n === 0 && Object.keys(a.filters).length > 0 && <div className="note risk">Nobody matches all of these together{h.empty_note ? `: ${h.empty_note}` : "."}</div>}
        {h && n > 0 && n < q && <div className="note risk">Only {fmt(n)} people — this audience needs {fmt(q)} at a study of {fmt(studySize)}.</div>}
        {h && n < q && adds.length > 0 && (
          <div className="note plain">Surveyed people can&apos;t fill this. {adds.map(([s, k], i) => <React.Fragment key={s}>{i ? " and " : ""}{NAMES[s] ?? s} would add <b>{fmt(k)}</b></React.Fragment>)} — their answers were read by a model from text, not given by them. Tick them under <i>Draw from</i> to use them; that is recorded in the brief&apos;s assumptions.</div>
        )}
        {h && shrinkers.map(([id, without]) => (
          <div key={id} className="note warn"><b>{label(id)}</b> is what shrinks this audience: {fmt(without)} without it, {fmt(n)} with it.
            <button className="btn sm" onClick={() => describeInstead(ai, id, h)}>Use as a description instead</button></div>
        ))}
        {dominant && sources.length > 1 && total > 0 && <div className="note plain">{pct((h!.by_source[dominant] ?? 0) / total)} of these people are from the {NAMES[dominant] ?? dominant}.</div>}
        {a.changes.map((c, ci) => (
          <div key={`${c.attribute}-${ci}`} className={`note ${c.accepted ? "plain" : "warn"}`}>
            {c.accepted ? "Accepted: " : "To fit the data, I kept "}<b>{label(c.attribute)}: {c.values.join(" / ")}</b> as a description, not a filter — as a filter it left {fmt(c.before)} people, not the {fmt(q)} needed.
            {!c.accepted && <button className="btn sm primary" onClick={() => acceptChange(ai, ci)}>Accept</button>}
            <button className="btn sm quiet" onClick={() => undoChange(ai, ci)}>Undo — use as a filter</button>
          </div>
        ))}
        {a.descriptions.filter((d) => !a.changes.some((c) => c.attribute === d)).length > 0 && (
          <div className="muted" style={{ marginTop: 8 }}>Describes (excludes no one): {a.descriptions.filter((d) => !a.changes.some((c) => c.attribute === d)).map(label).join(", ")}</div>
        )}
      </div>
    );
  }

  function ontologyView() {
    if (!rows.length) return <div className="note plain">Nothing declared yet — find attributes below.</div>;
    return (
      <>
        <div className="onto">
          <div className="orow headrow"><span title="required for everyone">req</span><span>Attribute</span><span>Role</span><span>Kind</span><span>Ordered</span><span /></div>
          {rows.map((r) => {
            const users = usedBy(r.id);
            const origin = r.role === "category" ? "the category's" : r.role === "core" ? "cross-survey core" : "";
            const own = reused && r.locked;
            return (
              <div key={r.id} className="orow">
                <input type="checkbox" checked={r.required} disabled={reused} onChange={(e) => updateRow(r.id, { required: e.target.checked })}
                  title={reused ? "The required set belongs to the category. Changing it is a separate new-version action, not part of a study." : "Required: a persona must have answered it to be drawn at all"} />
                <div><div>{r.label}</div><div className="id">{r.id} · measures {r.measures}{r.phrase ? ` · from “${r.phrase}”` : ""}</div></div>
                <div>{r.required
                  ? <><span className="role req">Required for everyone</span>{origin && <div className="muted" style={{ fontSize: 11 }}>{origin}</div>}</>
                  : users.length ? <span className="role">Defines {users.join(", ")}</span> : <span className="role">Describes everyone</span>}</div>
                <select value={r.domain} disabled={own} onChange={(e) => updateRow(r.id, { domain: e.target.value })} title="Kind — 'Who they are' and 'How they think' are never filled in by a model when missing">
                  {DOMAIN_WORDS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
                </select>
                <label className="muted" title={r.guessed ? "guessed from its values — check" : ""}>
                  <input type="checkbox" checked={r.ordered} disabled={own} onChange={(e) => updateRow(r.id, { ordered: e.target.checked, guessed: false })} /> {r.guessed ? "yes?" : ""}
                </label>
                <button className="btn quiet sm" disabled={own} onClick={() => removeRow(r)}>✕</button>
              </div>
            );
          })}
        </div>
        <div className="muted" style={{ marginTop: 6 }}>
          {reused
            ? "This category's own attributes are locked: studies reuse its ontology as it is, and anything you add makes a new version of it. Changing what it requires is a separate decision about the category, not about this study. "
            : <>A new category requires only the <b>cross-survey core</b> — what every survey asked most people — so no survey is shut out of later studies. Require more only if every future study of this category needs it; the sidebar shows what each requirement costs. </>}
          <b>Describes</b>: shown to the model when a persona has it, never used to exclude anyone.
        </div>
      </>
    );
  }

  function searchView() {
    return (
      <div className="card search" style={{ marginBottom: 10 }}>
        <input className="input" autoFocus placeholder="Search by meaning — e.g. kids, health, politics, owns a car" value={query} onChange={(e) => setQuery(e.target.value)} />
        {searchNote && <div className="muted" style={{ marginTop: 6 }}>{searchNote}</div>}
        {(hits ?? []).map((h) => {
          const f = h.if_required;
          const lost = f ? (typeof f.lost === "number" ? f.lost : Object.values(f.lost).reduce((t, k) => t + k, 0)) : 0;
          return (
            <div key={h.id} className="result">
              <div>
                <h4>{h.label} <span className="muted mono" style={{ fontSize: 11, fontWeight: 400 }}>{h.id} · measures {h.measures}</span></h4>
                <div className="muted">
                  {h.share !== undefined && <>{pct(h.share)} have answered it ({fmt(h.present)}) · </>}
                  {Object.entries(h.carry_by_source ?? {}).filter(([s]) => sources.includes(s)).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([s, k], i) => (
                    <React.Fragment key={s}>{i ? " · " : ""}<span className="swatch" style={{ background: COLORS[s] }} />{s} {fmt(k)}</React.Fragment>
                  ))}
                </div>
                <div className="muted mono" style={{ fontSize: 11 }}>{h.values.join(" · ")}</div>
                {!reused && f && <div className={`impact ${f.wiped_sources.length || !h.present ? "bad" : "muted"}`}>If required: {fmt(f.pool + lost)} → {fmt(f.pool)}{f.wiped_sources.length ? ` — removes everyone from ${f.wiped_sources.join(", ")}` : ""}</div>}
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "start" }}>
                {row(h.id) ? <span className="chip plain">added</span> : <>
                  <button className="btn sm" onClick={() => declare([{ ...h, role: "added", required: false }])}>+ Describe</button>
                  {!reused && <button className="btn sm" onClick={() => declare([{ ...h, role: "added", required: true }])}>+ Require</button>}
                </>}
              </div>
            </div>
          );
        })}
        {query && hits?.length === 0 && <div className="muted" style={{ paddingTop: 8 }}>Nothing close — the corpus carries no attribute like that; try fewer words.</div>}
      </div>
    );
  }

  function readyView(d: Ready) {
    const onto = JSON.stringify(d.ontology, null, 2);
    const brief = dump({ ontology_version: d.ontology.version, audiences: d.audiences, ...(d.assumptions.length ? { assumptions: d.assumptions } : {}) });
    const download = (content: string, type: string) => `data:${type},${encodeURIComponent(content)}`;
    return (
      <>
        <div className="head"><h1>Ready for a study</h1></div>
        <div className="note ok">The engine accepts all of it: the ontology passes its schema and codebook checks, every audience is one a brief can carry, and every assumption is one the ledger records. Save it as an audience set — these audiences, their assumptions, your sources and a study of {fmt(studySize)}, with the ontology they were drafted against — and New study starts from it.</div>
        <div className="note plain">
          {d.action === "reused" && <>Reuses <b className="catchip">{d.ontology.category} {d.ontology.version}</b> exactly as it is — no new version.</>}
          {d.action === "new_version" && <>A new version of <b className="catchip">{d.ontology.category}</b>: {d.from_version} → <b>{d.ontology.version}</b>, adding the attributes this study declares. Its required set is unchanged.</>}
          {d.action === "new_category" && <>A new category, <b className="catchip">{d.ontology.category} {d.ontology.version}</b>, requiring the cross-survey core.</>}
        </div>
        {d.assumptions.length > 0 && (
          <div className="note warn"><b>Written to the brief&apos;s assumptions</b> and stated in every report:
            <ul style={{ margin: "4px 0 0 16px" }}>{d.assumptions.map((a) => <li key={a.text}>{a.text}</li>)}</ul></div>
        )}
        <div className="grid g2" style={{ gap: 14, marginTop: 14 }}>
          <div><div className="sect"><h2>Ontology</h2><div className="tools">{d.action !== "reused" && <a className="btn sm" href={download(`${onto}\n`, "application/json")} download={`${d.ontology.category}-${d.ontology.version}.json`}>Download</a>}</div></div><pre className="out">{onto}</pre></div>
          <div><div className="sect"><h2>For the brief</h2><div className="tools"><a className="btn sm" href={download(brief, "text/yaml")} download="brief-audiences.yaml">Download</a></div></div><pre className="out">{brief}</pre></div>
        </div>
        {d.action === "new_category" && !savedSet && (
          <div className="field" style={{ marginTop: 14, maxWidth: 520 }}>
            <label>Name this category</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input className="input mono" value={categoryName} onChange={(e) => setCategoryName(e.target.value)} />
              <button className="btn" disabled={!categoryId(categoryName) || categoryId(categoryName) === d.ontology.category}
                onClick={() => continueIt({ mode: "new", id: categoryId(categoryName), version: null })}>Rename</button>
            </div>
            <div className="help">Studies of the same kind of product share a category, so its name should say what that kind is — {categoryId(categoryName) && categoryId(categoryName) !== categoryName ? <>saved as <span className="mono">{categoryId(categoryName)}</span></> : "lower case, digits and underscores"}.</div>
          </div>
        )}
        {continueError && <div className="note risk">{continueError}</div>}
        <div className="field" style={{ marginTop: 14, maxWidth: 520 }}>
          <label>Name this audience set</label>
          <input className="input" value={setName} disabled={!!savedSet} onChange={(e) => setSetName(e.target.value)} />
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {savedSet
            ? <span className="chip ok"><span className="dot" />saved “{savedSet.name}” · {savedSet.category} {savedSet.ontology_version}</span>
            : <button className="btn primary" onClick={saveSet}>Save audience set{d.action !== "reused" ? ` and ontology ${d.ontology.version}` : ""}</button>}
          <button className="btn primary" disabled={!savedSet} onClick={openLaunch}>Open launch form →</button>
          <button className="btn" onClick={() => { setReady(null); setContinueError(null); }}>← Back to editing</button>
        </div>
        {!savedSet && <div className="muted" style={{ marginTop: 6 }}>New study starts from a saved audience set. Saved sets and ontology versions are never overwritten: editing saves another, so past studies keep resolving to what they ran on.</div>}
      </>
    );
  }

  const shareSum = audiences.every((a) => a.share !== null) ? audiences.reduce((t, a) => t + (a.share ?? 0), 0) : null;
  const matching = heads.reduce((t, h) => t + h.head_count, 0);
  const splits = (preview?.assumptions ?? []).filter((a) => a.text.startsWith("differences between"));

  let main: React.ReactNode;
  if (ready) main = readyView(ready);
  else if (!category && byHand && !turns.length) main = byHandView();
  else if (!turns.length && !category) main = heroView();
  else if (!category) main = <section>{turns.map(turnView)}</section>;
  else {
    main = (
      <>
        <div className="head">
          <h1>{audiences.length} audience{audiences.length === 1 ? "" : "s"}</h1>
          <span className="muted">{fmt(matching)} matching people · ontology <span className="catchip">{category.id}</span>{reused ? " (reused)" : " (new)"}</span>
        </div>
        {splits.length > 0 && (
          <div className="note warn" style={{ marginBottom: 14 }}>Your audiences come mostly from different surveys, so a difference between them may be a difference between the surveys. <b>This will be recorded in the brief&apos;s assumptions</b> and stated in every report:
            <ul style={{ margin: "4px 0 0 16px" }}>{splits.map((a) => <li key={a.text}>{a.text}</li>)}</ul></div>
        )}
        <section>
          <div className="sect"><h2>Audiences</h2>
            <span className="muted">shares: {shareSum === null ? <b style={{ color: "var(--risk)" }}>not all set</b> : <><b style={{ color: Math.abs(shareSum - 1) > 0.005 ? "var(--risk)" : "inherit" }}>{Math.round(shareSum * 100)}%</b> of 100%</>} · study of {fmt(studySize)}</span>
            <div className="tools"><button className="btn sm" onClick={addAudience}>+ Add audience</button></div>
          </div>
          {audiences.length ? audiences.map(audienceView) : <div className="note plain">No audiences yet — {noEndpoint ? "add one and give it filters." : "describe one below."}</div>}
        </section>
        <section>
          <div className="sect"><h2>Ontology</h2><span className="muted">what every persona in this category is described by</span>
            <div className="tools"><button className="btn sm" onClick={() => setSearchOpen((o) => !o)}>{searchOpen ? "Close search" : "Find more attributes"}</button></div></div>
          {searchOpen && searchView()}
          {ontologyView()}
        </section>
        {turns.length > 0 && <section><div className="sect"><h2>Conversation</h2></div>{turns.map(turnView)}</section>}
        {!noEndpoint && (
          <div className="dock">
            <div className="composer">
              <textarea rows={1} value={followup} disabled={busy} placeholder="Add a group, or tell me more — e.g. “add students (20%)”, “all of them in North America”, “I also care about their health”"
                onChange={(e) => setFollowup(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFollowup(); } }} />
              <button className="btn primary sm" disabled={busy || !followup.trim()} onClick={sendFollowup}>Send</button>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Who you study</b></>}>
      <div className="who">
        {sidebar}
        <div className="who-main">{main}</div>
      </div>
    </Shell>
  );
}
