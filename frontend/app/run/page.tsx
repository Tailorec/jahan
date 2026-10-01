"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { PageHead, Chip, Callout, ICONS, TrustLine, Tip, Kpi, Section } from "@/components/ui";
import { useSessionState } from "@/lib/session";
import WorldGraph from "./world";
import ActivityStream from "./activity";
import Numbers from "./numbers";
import { CHANNEL_COLOR, useClock, useTicks, type Clock } from "./replay";
import { useApi, useRunId, api, whyNot } from "@/lib/api";
import { worldForCell } from "@/lib/worlds";
import { FORCE_WARNING, movedInputRefusal } from "@/lib/resume";
import type { OutcomeDigest, RunSummary, ScenarioSummary } from "@/lib/engine";

interface Detail {
  summary: RunSummary | null;
  digest: { digests: OutcomeDigest[]; summaries: Record<string, ScenarioSummary> } | null;
  pins: Record<string, unknown> | null;
  trace: { max_tick: Record<string, number>; event_counts: Record<string, Record<string, number>> } | null;
  report: { trust: { level: string } } | null;
}

/* A run's pins are a table of roles to models — and also the roles it leaves unpinned (`safety: null`)
   and the fallbacks it names (`fallbacks: {}`), which have no model of their own. Only a role that
   is pinned to a model is listed. */
function pinned(pins: Record<string, unknown> | null | undefined): string {
  const named = Object.entries(pins ?? {}).flatMap(([role, pin]) => {
    const id = pin && typeof pin === "object" ? (pin as { model_id?: unknown }).model_id : undefined;
    return typeof id === "string" ? [`${role}: ${id}`] : [];
  });
  return named.length ? named.join(" · ") : "—";
}

export default function RunPage() {
  const runId = useRunId();
  const [poll, setPoll] = React.useState(0);
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}?t=${poll}` : null);
  const [world, setWorld] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<"cancel" | "resume" | null>(null);
  const [refusal, setRefusal] = React.useState<string | null>(null);
  const s = data?.summary ?? null;
  const digests = data?.digest?.digests ?? [];
  const summaries = data?.digest?.summaries ?? {};
  const active = digests.find((d) => d.world_id === world) ?? digests[0] ?? null;
  const watching = !!s && (s.live || s.status === "running");
  const [tab, setTab] = useSessionState<string>("run:tab", "world");
  const { data: live } = useApi<{ worlds: { world_id: string; tick_closed: number; digest: OutcomeDigest | null; reason?: string }[] }>(runId ? `/api/runs/${runId}/live?t=${poll}` : null);
  // The world on show: the one picked, else the first the run names.
  const shownWorld = world ?? active?.world_id ?? (s ? worldForCell(digests, s.seeds[0], { worldIds: s.world_ids, scenarios: s.scenarios.length, seeds: s.seeds.length }) : null) ?? null;
  const lastClosed = (() => {
    const p = (s?.progress ?? []).find((x) => x.world_id === shownWorld)?.last_closed_tick;
    const o = (s?.outcomes ?? []).find((x) => x.world_id === shownWorld)?.last_closed_tick;
    return p ?? o ?? data?.trace?.max_tick[shownWorld ?? ""] ?? null;
  })();
  const { acts, posts, failed } = useTicks(runId, shownWorld, lastClosed);
  const clock = useClock(lastClosed);
  const channels = new Set((s?.scenarios ?? []).flatMap((sc) => sc.channels ?? []));
  const liveWorld = (live?.worlds ?? []).find((x) => x.world_id === shownWorld) ?? null;
  const finalDigest = digests.find((d) => d.world_id === shownWorld) ?? null;

  // Progress is polled while the run is going; a tick takes tens of seconds
  // and streaming buys nothing.
  React.useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => setPoll((p) => p + 1), 5000);
    return () => clearInterval(timer);
  }, [watching, runId]);

  async function cancel() {
    if (!runId || busy) return;
    setBusy("cancel");
    setRefusal(null);
    try {
      await api(`/api/runs/${runId}`, { method: "DELETE" });
      setPoll((p) => p + 1);
    } catch (e) {
      setRefusal(whyNot(e));
    } finally {
      setBusy(null);
    }
  }

  async function resume(force = false) {
    if (!runId || busy) return;
    if (force && !window.confirm(FORCE_WARNING)) return;
    setBusy("resume");
    setRefusal(null);
    try {
      await api(`/api/runs/${runId}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(force ? { action: "resume", force: true } : { action: "resume" }),
      });
      setPoll((p) => p + 1);
    } catch (e) {
      // The engine says why — the run is already going, the inputs moved, it was never started here.
      setRefusal(whyNot(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Run</b></>}>
      <RunBar runId={runId} />
      <PageHead
        title="Run — worlds over the population"
        sub={s ? <>One run over many worlds — scenarios × seeds sharing one budget. Status <b>{s.status}</b> · engine <span className="mono">{s.engine_version}</span> · config <span className="mono">{s.config_hash?.slice(0, 12)}…</span><br /><span className="mono" style={{ fontSize: 12 }}>{pinned(data?.pins)}</span></>
          : "A sweep is one run over many worlds sharing one budget."}
        actions={s && <><span className={`chip ${s.status === "completed" ? "ok" : "plain"}`}><span className="dot" />{s.live ? "running" : s.status}</span><span className="chip plain mono">${s.recorded_cost.toFixed(2)}{s.budget ? ` / $${s.budget.max_cost.toFixed(2)}` : ""}</span>{s.fake && <span className="chip tier-explo" title="No key, no corpus, no network">fake study</span>}</>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading run…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {refusal && <Callout icon="alert"><div><b>Refused.</b><pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{refusal}</pre></div></Callout>}
      {s && !watching && s.launch_error && (
        <Callout icon="alert"><div><b>This study stopped before it finished.</b> The last thing it said:
          <pre className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 6 }}>{s.launch_error}</pre></div></Callout>
      )}
      {s && (
        <>
          <div className="tabs" role="tablist">
            {TABS.map(([id, label, icon, channel]) => {
              const off = channel != null && !channels.has(channel as never);
              return (
                <button key={id} className={`tab tab-icon${tab === id ? " active" : ""}`} role="tab" aria-selected={tab === id} disabled={off}
                  title={off ? "This study did not tick this channel" : undefined} onClick={() => setTab(id)}
                  style={channel ? { color: tab === id ? CHANNEL_COLOR[channel] : undefined } : undefined}>
                  {ICONS[icon]}{label}
                </button>
              );
            })}
            {s.world_ids.length > 1 && (
              <select className="input mono" aria-label="World" value={shownWorld ?? ""} onChange={(e) => { setWorld(e.target.value); clock.setTick(0); }} style={{ marginLeft: "auto", maxWidth: 200 }}>
                {s.world_ids.map((id) => <option key={id} value={id}>world {id.slice(0, 12)}</option>)}
              </select>
            )}
          </div>
          {failed && <Callout icon="alert"><div>The record could not be read: {failed}</div></Callout>}
          {["world", "feed", "forum", "wom"].includes(tab) && <ClockBar clock={clock} watching={watching} loaded={Object.keys(acts).length} />}
          {tab === "world" && runId && (
            s.has_gate_report || s.world_ids.length ? <WorldGraph runId={runId} acts={acts} clock={clock} live={watching} />
              : <div className="empty"><b>No world yet.</b>The population is still being drawn.</div>
          )}
          {tab === "feed" && runId && <ActivityStream channel="social_feed" acts={acts} posts={posts} clock={clock} runId={runId} />}
          {tab === "forum" && runId && <ActivityStream channel="forum" acts={acts} posts={posts} clock={clock} runId={runId} />}
          {tab === "wom" && runId && <ActivityStream channel="wom" acts={acts} posts={posts} clock={clock} runId={runId} />}
          {tab === "numbers" && (
            finalDigest ? <Numbers d={finalDigest} asOf="Final: the digest the report is built on." />
              : liveWorld?.digest ? <Numbers d={liveWorld.digest} asOf={`Live: as of tick ${liveWorld.tick_closed}, the last the engine closed. Recomputed by the engine after every tick.`} />
              : <div className="empty"><b>No numbers yet.</b>{liveWorld?.reason ?? "They appear when the first tick closes."}</div>
          )}
        </>
      )}
      {s && tab === "details" && (
        <div style={{ display: "grid", gap: 16 }}>
          {(watching || (s.progress ?? []).length > 0 || (s.status !== "completed" && !s.has_report && !s.has_gate_report)) && (
            <Section icon="play" title={watching ? "Running — live progress" : "Stopped — live progress"}
              tip="Status, recorded cost and ticks closed, published by the study as it works. A world counts a tick only once all of it is recorded."
              tools={<>
                {watching && <button className="btn sm" onClick={cancel} disabled={busy !== null}>{ICONS.x}{busy === "cancel" ? "Cancelling…" : "Cancel run"}</button>}
                {!watching && s.status !== "completed" && <button className="btn sm" onClick={() => resume()} disabled={busy !== null}>{ICONS.play}{busy === "resume" ? "Resuming…" : "Resume run"}</button>}
                {!watching && s.status !== "completed" && movedInputRefusal(s.launch_error) && <button className="btn sm" onClick={() => resume(true)} disabled={busy !== null}>Force resume…</button>}
              </>}>
              {!(s.progress ?? []).length && <div className="empty"><b>Starting.</b>The registry write comes after the population is built.</div>}
              <div style={{ display: "grid", gap: 10 }}>
                {(s.progress ?? []).map((p) => {
                  // Progress does not name its scenario; the longest horizon bounds every world's.
                  const horizon = Math.max(1, (p.last_closed_tick ?? 0) + 1, ...s.scenarios.map((x) => x.horizon_ticks));
                  const done = p.last_closed_tick == null ? 0 : p.last_closed_tick + 1;
                  return (
                    <div key={p.world_id} className="item">
                      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                        <b className="mono">world {p.world_id.slice(0, 12)}</b>
                        <span className="sub" style={{ fontSize: 12 }}>Last closed tick <b className="mono">{p.last_closed_tick ?? "—"}</b> of {horizon - 1}</span>
                        <span className="sub" style={{ fontSize: 12 }}>Turns landed <b className="mono">{p.turns ?? "—"}</b></span>
                        <span className="sub" style={{ fontSize: 12, marginLeft: "auto" }}>Rung in force <b className="mono">{(p.rungs ?? []).length ? p.rungs!.join(", ") : "full fidelity"}</b></span>
                      </div>
                      <div className="tickbar" aria-label={`${done} of ${horizon} ticks closed`}>
                        {Array.from({ length: horizon }, (_, t) => (
                          <span key={t} className={t < done ? "on" : ""} title={`tick ${t}${(p.waves_answered ?? []).includes(t) ? " · survey wave answered" : ""}`}>
                            {(p.waves_answered ?? []).includes(t) && <i />}
                          </span>
                        ))}
                      </div>
                      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                        {Object.entries(p.turns_by_channel ?? {}).map(([c, k]) => (
                          <span key={c} className="chip plain" style={{ borderColor: CHANNEL_COLOR[c] }}>{ICONS[CHANNEL_ICON[c] ?? "radio"]} {c === "survey_room" ? "survey" : CHANNEL_LABEL[c] ?? c} · {k}</span>
                        ))}
                        <span className="sub" style={{ fontSize: 12 }}>{(p.waves_answered ?? []).length ? `waves answered at ticks ${p.waves_answered!.join(", ")}` : "no wave answered yet"}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          <div className="kpis">
            <Kpi icon="layers" label="Worlds" tip="One world per scenario and replicate seed; they share one budget." value={String(s.world_ids.length)} note={`${s.scenarios.length} scenario${s.scenarios.length === 1 ? "" : "s"} × ${s.seeds.length} seed${s.seeds.length === 1 ? "" : "s"}`} />
            <Kpi icon="dollar" label="Spend" tip="Derived from the calls the run was billed for, never kept as a separate tally." value={`$${s.recorded_cost.toFixed(3)}`}
              note={s.budget ? `of $${s.budget.max_cost.toFixed(2)} budget` : "no budget set"} />
            <Kpi icon="clock" label="Discarded ticks" tip="Ticks interrupted before they closed: their spend is unknown but not zero, and nothing they did is in the record." value={String(s.discarded_ticks)} tone={s.discarded_ticks ? "warn" : undefined} note={s.discarded_ticks ? "spend unknown, not zero" : "every tick recorded whole"} />
            <Kpi icon="shuffle" label="Seeds" tip="Replicate seeds. World ids are derived from scenario, seed and population — never chosen." value={s.seeds.join(", ") || "—"} />
          </div>
          {s.budget && (
            <div className="budget" title={`$${s.recorded_cost.toFixed(3)} of $${s.budget.max_cost.toFixed(2)}`}>
              <span style={{ width: `${Math.min(100, (s.recorded_cost / Math.max(1e-9, s.budget.max_cost)) * 100)}%` }} />
            </div>
          )}

          <Section icon="cpu" title="Models" tip="The model every role was pinned to, fixed for the whole run. A call answered by any other model is a pin failure, never a silent substitute. Roles pinned to nothing are not listed.">
            <div className="pin-grid">
              {Object.entries(data?.pins ?? {}).flatMap(([role, pin]) => {
                const id = pin && typeof pin === "object" ? (pin as { model_id?: unknown }).model_id : undefined;
                return typeof id === "string" ? [(
                  <div key={role} className="pin">
                    <span className="sec-icon">{ICONS[ROLE_ICON[role] ?? "cpu"]}</span>
                    <div style={{ minWidth: 0 }}>
                      <b>{ROLE_NAME[role] ?? role}</b> <span className="mono sub" style={{ fontSize: 11 }}>{role}</span>
                      <div className="mono" style={{ fontSize: 12, overflowWrap: "anywhere" }}>{id}</div>
                    </div>
                  </div>
                )] : [];
              })}
            </div>
          </Section>

          <Section icon="table" title="Scenarios × seeds → worlds" tip="What each scenario changed and the world each replicate seed ran it in. Click a world to show it in the World, Numbers and channel tabs.">
            <div style={{ display: "grid", gap: 12 }}>
              {s.scenarios.map((sc, si) => (
                <div key={si} className="item">
                  <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <b>{sc.variant.name}</b><span className="mono sub">{sc.variant.variant_id}</span>
                    <span className="mono sub" style={{ marginLeft: "auto", fontSize: 11 }}>scenario {si + 1}</span>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                    <span className="chip plain">{ICONS.dollar} {sc.price.amount} {sc.price.currency}</span>
                    <span className="chip plain">{ICONS.clock} {sc.horizon_ticks} {sc.tick_unit}s</span>
                    {(sc.channels ?? []).length === 0
                      ? <span className="chip plain">{ICONS.survey} concept test</span>
                      : sc.channels.map((c) => <span key={c} className="chip plain" style={{ borderColor: CHANNEL_COLOR[c] }}>{ICONS[CHANNEL_ICON[c] ?? "radio"]} {CHANNEL_LABEL[c] ?? c}</span>)}
                    <span className="chip plain">{ICONS.survey} survey every {sc.survey_every}</span>
                    {/* Launch reach seeds word of mouth only when it is the one channel (ADR 0048); elsewhere it does nothing. */}
                    {sc.launch_reach > 0 && sc.channels.length === 1 && sc.channels[0] === "wom" && <span className="chip plain">{ICONS.target} launch reach {(sc.launch_reach * 100).toFixed(0)}%</span>}
                    {(sc.channels ?? []).length > 0 && <span className="chip plain">{ICONS.layers} {sc.exposure_budget} items a turn</span>}
                    {sc.interventions.map((iv, k) => <span key={k} className="chip plain">{ICONS.sparkles} {iv.kind} at t{iv.tick}</span>)}
                  </div>
                  {Object.keys(sc.audience_weights ?? {}).length > 0 && (
                    <div className="mix">
                      {Object.entries(sc.audience_weights).map(([a, wgt], k) => (
                        <span key={a} style={{ width: `${wgt * 100}%`, background: `var(--seg${(k % 5) + 1})` }} title={`${a}: ${(wgt * 100).toFixed(0)}%`} />
                      ))}
                    </div>
                  )}
                  {Object.keys(sc.audience_weights ?? {}).length > 0 && (
                    <div className="row sub" style={{ gap: 10, flexWrap: "wrap", fontSize: 11.5 }}>
                      {Object.entries(sc.audience_weights).map(([a, wgt], k) => <span key={a} className="row" style={{ gap: 4 }}><span className="swatch" style={{ background: `var(--seg${(k % 5) + 1})` }} />{a.replace(/_/g, " ")} {(wgt * 100).toFixed(0)}%</span>)}
                    </div>
                  )}
                  <div style={{ overflowX: "auto" }}>
                    <table className="tbl tight nowrap">
                      <thead><tr><th>Seed</th><th>World</th><th>Status</th><th className="num">Last tick</th><th>Rungs</th><th className="num">Adoption</th><th className="num">Polarization</th><th /></tr></thead>
                      <tbody>
                        {s.seeds.map((seed) => {
                          const worldId = worldForCell(digests, seed, { worldIds: s.world_ids, scenarios: s.scenarios.length, seeds: s.seeds.length });
                          const oc = s.outcomes.find((o) => o.world_id === worldId);
                          const dg = digests.find((d) => d.world_id === worldId);
                          return (
                            <tr key={seed} className={worldId && worldId === shownWorld ? "picked" : ""}>
                              <td className="num mono">{seed}</td>
                              <td className="mono">{worldId?.slice(0, 12) ?? "—"}</td>
                              <td>{oc ? <Chip className={oc.status === "completed" ? "ok" : "plain"}>{oc.status.replace("_", " ")}</Chip> : "—"}</td>
                              <td className="num">{oc?.last_closed_tick ?? "—"}</td>
                              <td className="mono sub">{oc?.rungs.length ? oc.rungs.join(", ") : "full fidelity"}</td>
                              <td className="num">{dg ? (dg.adoption != null ? `${(dg.adoption * 100).toFixed(1)}%` : <span className="sub" title={dg.unmeasured_reason ?? ""}>unmeasured <Tip>{dg.unmeasured_reason ?? "No wave was scored."}</Tip></span>) : "—"}</td>
                              <td className="num">{dg ? (dg.polarization != null ? dg.polarization.toFixed(3) : <span className="sub">— <Tip>{dg.polarization_reason ?? "Polarization was not measured."}</Tip></span>) : "—"}</td>
                              <td>{worldId && <button type="button" className="btn btn-secondary sm" onClick={() => { setWorld(worldId); clock.setTick(0); setTab("world"); }}>{ICONS.network} Watch</button>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {Object.keys(summaries).length > 0 && s.seeds.length > 1 && (
            <Section icon="shuffle" title="Replicate spread" tip="The study's own variance estimate: how far each measure moved between a scenario's seeds. An ordering between scenarios only survives when their gap is bigger than this. Worlds that ran at different degradation rungs are not comparable.">
              <div style={{ overflowX: "auto" }}><table className="tbl nowrap">
                <thead><tr><th>Scenario</th><th className="num">Adoption spread</th><th className="num">Polarization spread</th><th className="num">Belief-move spread</th><th>Rungs</th></tr></thead>
                <tbody>
                  {Object.values(summaries).map((sm) => (
                    <tr key={sm.scenario_hash}><td className="mono sub">{sm.scenario_hash.slice(0, 12)}…</td>
                      <td className="num">{sm.adoption_spread != null ? `±${(sm.adoption_spread * 100).toFixed(1)}%` : "unmeasured"}</td>
                      <td className="num">{sm.polarization_spread?.toFixed(3) ?? "—"}</td>
                      <td className="num">{sm.belief_move_spread?.toFixed(3) ?? "—"}</td>
                      <td>{sm.rung_mixed ? <Chip className="tier-explo">mixed — not comparable</Chip> : <span className="sub">uniform</span>}</td></tr>
                  ))}
                </tbody>
              </table></div>
            </Section>
          )}

          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <Link className="btn sm" href={`/trace?run=${runId}${shownWorld ? `&world=${shownWorld}` : ""}`}>{ICONS.code} Open trace view</Link>
            <Link className="btn sm" href={`/report?run=${runId}`}>{ICONS.bulb} Findings in the report</Link>
          </div>
        </div>
      )}
    </Shell>
  );
}

const TABS: [string, string, keyof typeof ICONS, string | null][] = [
  ["world", "World", "network", null],
  ["numbers", "Numbers", "pie", null],
  ["feed", "X-like feed", "feed", "social_feed"],
  ["forum", "Reddit-like forum", "forum", "forum"],
  ["wom", "Word of mouth", "wom", "wom"],
  ["details", "Run details", "table", null],
];

/* The replay clock: the tick on show, play and pause, speed, and a jump to the newest closed tick. */
function ClockBar({ clock, watching, loaded }: { clock: Clock; watching: boolean; loaded: number }) {
  const last = clock.lastClosed ?? 0;
  return (
    <div className="clockbar">
      <button type="button" className="btn btn-secondary" aria-label={clock.playing ? "Pause" : "Play"} onClick={() => clock.setPlaying(!clock.playing)}>
        {clock.playing ? "❚❚ Pause" : <>{ICONS.play} Play</>}
      </button>
      <label className="row" style={{ gap: 8, flex: 1, minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 12, minWidth: 54 }}>tick {clock.tick}</span>
        <input type="range" min={0} max={Math.max(0, last)} value={Math.min(clock.tick, last)} aria-label="Tick" onChange={(e) => clock.setTick(Number(e.target.value))} style={{ flex: 1, minWidth: 60 }} />
        <span className="mono sub" style={{ fontSize: 12, whiteSpace: "nowrap" }}>of {last}</span>
      </label>
      <select className="input" aria-label="Speed" value={clock.speed} onChange={(e) => clock.setSpeed(Number(e.target.value))} style={{ width: "auto", fontSize: 12, padding: "3px 6px" }}>
        {[0.5, 1, 2, 4].map((v) => <option key={v} value={v}>{v}×</option>)}
      </select>
      <button type="button" className="btn btn-secondary" onClick={() => clock.setTick(last)} disabled={clock.tick >= last}>Newest tick</button>
      {watching ? <span className="chip ok"><span className="dot" />live · one tick behind</span> : <span className="chip plain">replay</span>}
      {loaded <= last && <span className="sub" style={{ fontSize: 12 }}>loading ticks {loaded}/{last + 1}…</span>}
      <Tip>The engine publishes a tick only when all of it is recorded, so the page replays each closed tick&apos;s decisions in the order they happened. A running study is followed one tick behind; a finished one replays the same way. The feed, forum and word-of-mouth tabs show everything up to the tick on show.</Tip>
    </div>
  );
}

const CHANNEL_ICON: Record<string, keyof typeof ICONS> = { social_feed: "feed", forum: "forum", wom: "wom", survey_room: "survey" };
const CHANNEL_LABEL: Record<string, string> = { social_feed: "X-like feed", forum: "Reddit-like forum", wom: "word of mouth" };
const ROLE_ICON: Record<string, keyof typeof ICONS> = { tier_a: "forum", tier_b: "forum", embed: "database", recsys_embed: "feed", safety: "shield" };
const ROLE_NAME: Record<string, string> = { tier_a: "Chat, tier A", tier_b: "Chat, tier B", embed: "Embeddings (scoring)", recsys_embed: "Feed ranking", safety: "Safety" };

