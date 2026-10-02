"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { PageHead, Chip, Callout, TrustLine, ICONS, Section, Tip } from "@/components/ui";
import { CommunityIntent, IntentOverWaves } from "@/components/charts";
import { api, useApi, useRunId, whyNot } from "@/lib/api";
import { versionName } from "@/lib/worlds";
import {
  type Finding,
  type OutcomeDigest,
  type RunSummary,
  type Scenario,
  type ScenarioSummary,
  type StudyReport,
} from "@/lib/engine";

interface Detail {
  summary: RunSummary | null;
  digest: { digests: OutcomeDigest[]; summaries: Record<string, ScenarioSummary> } | null;
  report: StudyReport | null;
}

/* The validated categorical order the intent chart uses: one colour per version, in launch order. */
const SERIES = ["#be7200", "#0087a0", "#c0504d", "#9c63c2", "#2f8a3e"];
const CHANNEL_ICON: Record<string, keyof typeof ICONS> = { social_feed: "feed", forum: "forum", wom: "wom" };
const CHANNEL_NAME: Record<string, string> = { social_feed: "X-like feed", forum: "Reddit-like forum", wom: "word of mouth" };
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);

interface Version { sc: Scenario; index: number; color: string; worlds: OutcomeDigest[]; values: number[]; spread: ScenarioSummary | null }

/* The atlas: every version of a run side by side, leading with the decision — which version leads, and whether
   it leads by more than chance moves a result between seeds. Every number is the engine's; the page compares. */
export default function AtlasPage() {
  const runId = useRunId();
  const [poll, setPoll] = React.useState(0);
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}?t=${poll}` : null, { keep: true });
  const { data: live } = useApi<{ worlds: { world_id: string; digest: OutcomeDigest | null }[] }>(runId ? `/api/runs/${runId}/live?t=${poll}` : null, { keep: true });
  const s = data?.summary ?? null;
  const report = data?.report ?? null;
  const running = !!s && (s.live || s.status === "running");
  React.useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setPoll((p) => p + 1), 8000);
    return () => clearInterval(timer);
  }, [running]);

  // A finished world's final digest; a world still running shows its digest as of its last closed tick.
  const finals = data?.digest?.digests ?? [];
  const digests = [...finals, ...(live?.worlds ?? []).flatMap((w) => (w.digest && !finals.some((f) => f.world_id === w.world_id) ? [w.digest] : []))];
  const summaries = data?.digest?.summaries ?? {};
  const versions: Version[] = (s?.scenarios ?? []).map((sc, index) => {
    const worlds = digests.filter((d) => d.scenario_hash === sc.scenario_hash).sort((a, b) => a.seed - b.seed);
    return {
      sc, index, color: SERIES[index % SERIES.length], worlds,
      values: worlds.flatMap((w) => (w.adoption != null ? [w.adoption] : [])),
      spread: sc.scenario_hash ? summaries[sc.scenario_hash] ?? null : null,
    };
  });
  const ranked = [...versions].filter((v) => v.values.length).sort((a, b) => Math.max(...b.values) - Math.max(...a.values));
  const rankingFindings = (report?.findings ?? []).filter((f) => f.kind === "ranking");
  const riskFindings = (report?.findings ?? []).filter((f) => f.kind === "risk");
  const many = (s?.world_ids.length ?? 0) > 1 || versions.length > 1;

  const rename = async (sc: Scenario, label: string) => {
    if (!runId || !sc.scenario_hash) return;
    await api(`/api/runs/${runId}/labels`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ scenario_hash: sc.scenario_hash, label }) });
    setPoll((p) => p + 1);
  };

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Scenario atlas</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Scenario atlas"
        sub={<>Which version wins, and by more than chance? <Tip>A run compares versions of a study — another price, another wording, other channels — each run under every replicate seed over the same people. A seed changes only what is random, so the spread between a version&apos;s seeds is how far chance alone moves its result. One version leads only when its worst seed beats the next version&apos;s best.</Tip></>}
        actions={s && <>
          <span className="chip plain">{ICONS.layers} {versions.length} version{versions.length === 1 ? "" : "s"}</span>
          <span className="chip plain">{ICONS.shuffle} {s.seeds.length} seed{s.seeds.length === 1 ? "" : "s"}</span>
          {running && <span className="chip warn"><span className="dot" />{digests.length} of {s.world_ids.length || versions.length * s.seeds.length} worlds measured</span>}
        </>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}

      {s && !many && (
        <div className="atlas-alone">
          <span className="sec-icon">{ICONS.layers}</span>
          <div>
            <b>This run has one world, so there is nothing to compare.</b>
            <p className="sub">The atlas compares versions of a study — prices, wordings, channel mixes — each under several seeds. Its one world is on the run page.</p>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <Link className="btn sm" href={`/run?run=${runId}`}>{ICONS.network} Open the run</Link>
            <Link className="btn sm btn-primary" href="/intake">{ICONS.plus} Launch versions</Link>
          </div>
        </div>
      )}

      {s && many && (
        <div style={{ display: "grid", gap: 16 }}>
          <Verdict ranked={ranked} seeds={s.seeds.length} />

          <Section icon="target" title="Adoption by version" tip="Top-two-box purchase intent at each world's last survey wave. A dot per seed; the line between them is how far chance moved the result. Versions are ordered by their best seed. Click a name to rename it — names change no result.">
            <RangeChart versions={versions} seeds={s.seeds} onRename={rename} runId={runId} />
          </Section>

          <Section icon="survey" title="Intent over waves, by version" tip="Each world's share-weighted top-two box at every survey wave: one colour per version, a solid line for its first seed and dashed for the others.">
            <WavesByVersion versions={versions} seeds={s.seeds} />
          </Section>

          <Section icon="table" title="Worlds" tip="Every version under every seed. Cells whose worlds ran at different degradation rungs are marked rather than silently compared; an unmeasured quantity shows its reason where the number would be. Click a world to watch it.">
            <WorldGrid versions={versions} seeds={s.seeds} runId={runId} />
          </Section>

          {rankingFindings.length > 0 && (
            <Section icon="layers" title="Ranking findings" tip="Findings authored by extraction from the versions' replicates — never generated — each carrying the spread that says whether the ordering survives, and the real-world test that would disprove it.">
              <div style={{ display: "grid", gap: 10 }}>{rankingFindings.map((f) => <FindingCard key={f.finding_id} f={f} versions={versions} />)}</div>
            </Section>
          )}
          {riskFindings.length > 0 && (
            <Section icon="alert" title="Risk findings" tip="Authored from recorded anomalies — each with its evidence and the real-world test that would disprove it.">
              <div style={{ display: "grid", gap: 10 }}>{riskFindings.map((f) => <FindingCard key={f.finding_id} f={f} versions={versions} />)}</div>
            </Section>
          )}

          <details className="fold atlas-fold">
            <summary>{ICONS.survey} Intent over waves: audiences, world by world</summary>
            <div style={{ display: "grid", gap: 16, marginTop: 10 }}>
              {versions.flatMap((v) => v.worlds.map((d) => (
                <div key={d.world_id}>
                  <div className="row" style={{ gap: 8, marginBottom: 6 }}><span className="swatch" style={{ background: v.color }} /><b>{versionName(v.sc)}</b><span className="chip plain mono">seed {s.seeds.indexOf(d.seed) + 1}</span></div>
                  {(d.waves ?? []).length > 0 ? <IntentOverWaves waves={d.waves!} /> : <p className="sub" style={{ fontSize: 12 }}>unmeasured: {d.unmeasured_reason ?? "no intent measured"}</p>}
                </div>
              )))}
            </div>
          </details>
          <details className="fold atlas-fold">
            <summary>{ICONS.fork} Communities: where intent ended <Tip>Groups that formed in the social network, separately presented from audiences: each community&apos;s answers at the last wave.</Tip></summary>
            <div style={{ display: "grid", gap: 16, marginTop: 10 }}>
              {versions.flatMap((v) => v.worlds.map((d) => (
                <div key={d.world_id}>
                  <div className="row" style={{ gap: 8, marginBottom: 6 }}><span className="swatch" style={{ background: v.color }} /><b>{versionName(v.sc)}</b><span className="chip plain mono">seed {s.seeds.indexOf(d.seed) + 1}</span></div>
                  <CommunityIntent d={d} />
                </div>
              )))}
            </div>
          </details>
        </div>
      )}
    </Shell>
  );
}

/* The decision, said first: whether the best version's worst seed beats the next version's best. A comparison of
   the engine's own numbers — nothing is averaged or tested here. */
function Verdict({ ranked, seeds }: { ranked: Version[]; seeds: number }) {
  if (ranked.length < 2) {
    return <Callout icon="info"><div>{ranked.length === 0 ? "No version has a measured adoption yet." : "Only one version is measured so far."}</div></Callout>;
  }
  const [best, next] = ranked;
  const clear = Math.min(...best.values) > Math.max(...next.values);
  const oneSeed = seeds < 2;
  return (
    <div className={`verdict ${clear && !oneSeed ? "lead" : "tie"}`}>
      <span className="sec-icon">{clear && !oneSeed ? ICONS.check : ICONS.scale}</span>
      <div>
        {oneSeed
          ? <><b>{versionName(best.sc)} measures highest, at {pct(Math.max(...best.values))}.</b> With one seed there is no spread to say whether that beats chance — run two or more.</>
          : clear
            ? <><b>{versionName(best.sc)} leads beyond chance.</b> Its worst seed ({pct(Math.min(...best.values))}) beats {versionName(next.sc)}&apos;s best ({pct(Math.max(...next.values))}).</>
            : <><b>Too close to call.</b> {versionName(best.sc)} and {versionName(next.sc)} overlap across seeds ({pct(Math.min(...best.values))}–{pct(Math.max(...best.values))} against {pct(Math.min(...next.values))}–{pct(Math.max(...next.values))}): chance alone moves a result that far.</>}
      </div>
    </div>
  );
}

/* One row per version: a dot per seed on a shared, zoomed axis, the range between them, and what the version
   changes. Ordered as launched, so a version keeps its colour and place. */
function RangeChart({ versions, seeds, onRename, runId }: { versions: Version[]; seeds: number[]; onRename: (sc: Scenario, label: string) => Promise<void>; runId: string | null }) {
  const all = versions.flatMap((v) => v.values);
  if (!all.length) return <p className="sub">No world has a measured adoption yet.</p>;
  const lo = Math.max(0, Math.floor((Math.min(...all) - 0.02) * 50) / 50);
  const hi = Math.min(1, Math.ceil((Math.max(...all) + 0.02) * 50) / 50);
  const at = (v: number) => `${((v - lo) / Math.max(0.0001, hi - lo)) * 100}%`;
  const base = versions[0]?.sc;
  return (
    <div className="ranges">
      <div className="ranges-row ranges-head sub"><span /><div className="ranges-axis"><span>{pct(lo, 0)}</span><span>{pct(hi, 0)}</span></div><span /></div>
      {versions.map((v) => (
        <div key={v.sc.scenario_hash ?? v.index} className="ranges-row">
          <div className="ranges-name">
            <Name sc={v.sc} color={v.color} onRename={onRename} />
            <Differences sc={v.sc} base={base} />
          </div>
          <div className="ranges-track">
            {v.values.length > 1 && <span className="ranges-span" style={{ left: at(Math.min(...v.values)), width: `calc(${at(Math.max(...v.values))} - ${at(Math.min(...v.values))})`, background: v.color }} />}
            {v.worlds.map((w) => w.adoption != null && (
              <Link key={w.world_id} href={`/run?run=${runId}&world=${w.world_id}`} className="ranges-dot" style={{ left: at(w.adoption), background: v.color }}
                title={`${versionName(v.sc)} · seed ${seeds.indexOf(w.seed) + 1}: ${pct(w.adoption)} — open this world`} />
            ))}
            {!v.values.length && <span className="sub ranges-none">{v.worlds[0]?.unmeasured_reason ? `unmeasured: ${v.worlds[0].unmeasured_reason}` : "not measured yet"}</span>}
          </div>
          <div className="ranges-val">
            {v.values.length ? <><b>{pct(Math.max(...v.values))}</b>{v.values.length > 1 && <span className="sub">from {pct(Math.min(...v.values))}</span>}</> : <span className="sub">—</span>}
            {v.spread?.rung_mixed && <span className="chip tier-explo" style={{ fontSize: 10 }}>different degradation rungs</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/* A version's name, renamed in place: presentation only, outside every identity (ADR 0052). */
function Name({ sc, color, onRename }: { sc: Scenario; color: string; onRename: (sc: Scenario, label: string) => Promise<void> }) {
  const [editing, setEditing] = React.useState(false);
  const [text, setText] = React.useState(sc.label ?? "");
  const [problem, setProblem] = React.useState<string | null>(null);
  const save = async () => {
    if (!text.trim()) return setEditing(false);
    try { await onRename(sc, text.trim()); setEditing(false); setProblem(null); } catch (e) { setProblem(whyNot(e)); }
  };
  if (editing) {
    return (
      <span className="row" style={{ gap: 6 }}>
        <span className="swatch" style={{ background: color }} />
        <input className="input" autoFocus value={text} maxLength={60} placeholder={versionName(sc)} aria-label="Version name"
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }} onBlur={save} style={{ padding: "2px 6px", fontSize: 13 }} />
        {problem && <span className="sub" style={{ color: "var(--risk)" }}>{problem}</span>}
      </span>
    );
  }
  return (
    <button type="button" className="version-name" onClick={() => { setText(sc.label ?? ""); setEditing(true); }} title="Rename this version">
      <span className="swatch" style={{ background: color }} />{versionName(sc)} <span className="edit">{ICONS.sliders}</span>
    </button>
  );
}

/* What a version changes from the first: only the differences, so the reader sees what is being tested. */
function Differences({ sc, base }: { sc: Scenario; base: Scenario | undefined }) {
  const chips: React.ReactNode[] = [<span key="price" className="chip plain">{ICONS.dollar} {sc.price.amount} {sc.price.currency}</span>];
  const chans = [...(sc.channels ?? [])].sort().join(",");
  if (!base || chans !== [...(base.channels ?? [])].sort().join(",") || sc === base) {
    chips.push((sc.channels ?? []).length === 0
      ? <span key="ch" className="chip plain">{ICONS.survey} concept test</span>
      : <span key="ch" className="chip plain">{(sc.channels ?? []).map((c) => <React.Fragment key={c}>{ICONS[CHANNEL_ICON[c] ?? "radio"]}</React.Fragment>)} {(sc.channels ?? []).map((c) => CHANNEL_NAME[c] ?? c).join(" + ")}</span>);
  }
  if (!base || sc === base || sc.horizon_ticks !== base.horizon_ticks) chips.push(<span key="h" className="chip plain">{ICONS.clock} {sc.horizon_ticks} {sc.tick_unit}s</span>);
  if (base && sc !== base && sc.survey_every !== base.survey_every) chips.push(<span key="s" className="chip plain">{ICONS.survey} survey every {sc.survey_every}</span>);
  if (base && sc !== base && sc.variant.description !== base.variant.description) chips.push(<span key="d" className="chip plain" title={sc.variant.description}>{ICONS.tag} own wording</span>);
  return <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>{chips}</div>;
}

/* Every world's whole adoption over its survey waves: one colour per version, solid for its first seed. */
function WavesByVersion({ versions, seeds }: { versions: Version[]; seeds: number[] }) {
  const lines = versions.flatMap((v) => v.worlds.map((w) => ({ v, w, pts: (w.waves ?? []).filter((x) => x.adoption != null).map((x) => [x.tick, x.adoption!] as [number, number]) })));
  const values = lines.flatMap((l) => l.pts.map(([, y]) => y));
  // Drawn at the width it is shown at, so its text keeps its real size on any screen.
  const box = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(720);
  React.useEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => setWidth(Math.max(300, Math.round(el.clientWidth)));
    fit();
    const watch = new ResizeObserver(fit);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  if (!values.length) return <p className="sub">No wave answered yet.</p>;
  const ticks = [...new Set(lines.flatMap((l) => l.pts.map(([t]) => t)))].sort((a, b) => a - b);
  const W = width, H = 220, L = 44, R = 16, T = 12, B = 28;
  const lo = Math.max(0, Math.floor((Math.min(...values) - 0.03) * 20) / 20), hi = Math.min(1, Math.ceil((Math.max(...values) + 0.03) * 20) / 20);
  const x = (t: number) => L + (ticks.length > 1 ? ((t - ticks[0]) / (ticks[ticks.length - 1] - ticks[0])) * (W - L - R) : (W - L - R) / 2);
  const y = (v: number) => T + (1 - (v - lo) / Math.max(0.01, hi - lo)) * (H - T - B);
  const grid = Array.from({ length: Math.round((hi - lo) / 0.05) + 1 }, (_, k) => lo + k * 0.05);
  return (
    <div ref={box} style={{ minWidth: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block" }} role="img" aria-label="Adoption over survey waves, by version and seed">
        {grid.map((g) => <g key={g}><line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="var(--line)" /><text x={L - 8} y={y(g) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)">{Math.round(g * 100)}%</text></g>)}
        {ticks.map((t) => <text key={t} x={x(t)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--ink-3)">t{t}</text>)}
        {lines.map(({ v, w, pts }) => {
          const k = seeds.indexOf(w.seed);
          return (
            <g key={w.world_id}>
              <path d={pts.map(([t, a], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(a).toFixed(1)}`).join(" ")} fill="none" stroke={v.color} strokeWidth="2" strokeDasharray={k > 0 ? "5 4" : undefined} />
              {pts.map(([t, a]) => <circle key={t} cx={x(t)} cy={y(a)} r="3.5" fill={v.color} stroke="var(--bg)" strokeWidth="1.5"><title>{`${versionName(v.sc)} · seed ${k + 1} · t${t}: ${pct(a)}`}</title></circle>)}
            </g>
          );
        })}
      </svg>
      <div className="row" style={{ gap: 14, flexWrap: "wrap", fontSize: 12 }}>
        {versions.map((v) => <span key={v.index} className="row" style={{ gap: 5 }}><span className="swatch" style={{ background: v.color }} />{versionName(v.sc)}</span>)}
        {seeds.length > 1 && <span className="sub">solid: seed 1 · dashed: other seeds</span>}
      </div>
    </div>
  );
}

/* Version by seed: adoption in each world, tinted by level, with what the engine marks about it. */
function WorldGrid({ versions, seeds, runId }: { versions: Version[]; seeds: number[]; runId: string | null }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl atlas nowrap">
        <thead><tr><th>Version</th>{seeds.map((seed, k) => <th key={seed} className="num">seed {k + 1} <span className="mono sub">({seed})</span></th>)}<th className="num">Spread <Tip>Replicate spread: how far adoption moved between this version&apos;s seeds — the engine&apos;s own estimate of chance.</Tip></th></tr></thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.index}>
              <td><span className="row" style={{ gap: 6 }}><span className="swatch" style={{ background: v.color }} /><b>{versionName(v.sc)}</b></span></td>
              {seeds.map((seed) => {
                const d = v.worlds.find((w) => w.seed === seed);
                if (!d) return <td key={seed} className="num"><span className="sub">not yet</span></td>;
                return (
                  <td key={seed} className="num">
                    <Link href={`/run?run=${runId}&world=${d.world_id}`} className="atlas-cell" style={{ background: d.adoption != null ? `color-mix(in srgb, ${v.color} ${Math.round(d.adoption * 45)}%, var(--bg))` : "var(--surface-2)" }}>
                      {d.adoption != null ? <span className="big">{pct(d.adoption)}</span> : <span className="sub" style={{ fontStyle: "italic", fontSize: 11 }}>unmeasured: {d.unmeasured_reason ?? "unmeasured"}</span>}
                      <span className="mono sub" style={{ fontSize: 11 }}>{d.polarization != null ? <>pol {d.polarization.toFixed(3)}</> : <>pol — <Tip>{d.polarization_reason ?? "Polarization was not measured."}</Tip></>}</span>
                      {(d.rungs ?? []).length > 0 && <span className="chip tier-explo" style={{ fontSize: 10 }}>degraded rung ({d.rungs.join(", ")})</span>}
                    </Link>
                  </td>
                );
              })}
              <td className="num mono">{v.spread?.adoption_spread != null ? `±${(v.spread.adoption_spread * 100).toFixed(1)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* One finding: what it says, how sure, the versions it orders by name, and the test that would prove it wrong. */
function FindingCard({ f, versions }: { f: Finding; versions: Version[] }) {
  const named = (hash: string) => { const v = versions.find((x) => x.sc.scenario_hash?.startsWith(hash) || x.sc.scenario_hash === hash); return v ? versionName(v.sc) : hash.slice(0, 8); };
  return (
    <div className="item">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <b className="mono">{f.finding_id}</b>
        <Chip className={f.kind === "risk" ? "risk" : "tier-pros"}>{f.confidence} confidence</Chip>
        {f.ranked_scenarios && f.ranked_scenarios.length > 0 && <span className="sub">ordered: {f.ranked_scenarios.map(named).join(" > ")}</span>}
      </div>
      <p style={{ fontWeight: 500 }}>{f.statement}</p>
      <p className="sub" style={{ fontSize: 12 }}><b>Disconfirming test:</b> {f.disconfirming_test}</p>
    </div>
  );
}
