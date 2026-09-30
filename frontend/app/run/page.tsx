"use client";

import Link from "next/link";
import React from "react";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, PmfBar, PmfLegend, ICONS, TrustLine } from "@/components/ui";
import { useApi, useRunId, api, whyNot } from "@/lib/api";
import { worldForCell } from "@/lib/worlds";
import { FORCE_WARNING, movedInputRefusal } from "@/lib/resume";
import { pmfMean, top2box, type OutcomeDigest, type RunSummary, type ScenarioSummary } from "@/lib/engine";

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
    <Shell crumbs={<><Link href="/">Workspace</Link> / <b>Run</b>{runId && <> / <span className="mono">{runId}</span></>}</>}>
      <PageHead
        title="Run — worlds over the population"
        sub={s ? <>One run over many worlds — scenarios × seeds sharing one budget. Status <b>{s.status}</b> · engine <span className="mono">{s.engine_version}</span> · config <span className="mono">{s.config_hash?.slice(0, 12)}…</span></>
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
      {s && (watching || (s.progress ?? []).length > 0 || (s.status !== "completed" && !s.has_report && !s.has_gate_report)) && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-head"><h2>{watching ? "Running" : "Stopped"} — live progress</h2><span className="hint">status, recorded cost and ticks closed, published as the run works</span>
            <div className="tools" style={{ display: "flex", gap: 8 }}>
              {watching && <button className="btn sm" onClick={cancel} disabled={busy !== null}>{busy === "cancel" ? "Cancelling…" : "Cancel run"}</button>}
              {!watching && s.status !== "completed" && <button className="btn sm" onClick={() => resume()} disabled={busy !== null}>{busy === "resume" ? "Resuming…" : "Resume run"}</button>}
              {!watching && s.status !== "completed" && movedInputRefusal(s.launch_error) && <button className="btn sm" onClick={() => resume(true)} disabled={busy !== null}>Force resume…</button>}
            </div></div>
          <div className="panel-body tight"><table className="tbl">
            <thead><tr><th>World</th><th className="num">Last closed tick</th><th className="num">Turns landed</th><th>Turns by channel</th><th>Waves answered</th><th>Rung in force</th></tr></thead>
            <tbody>
              {(s.progress ?? []).map((p) => (
                <tr key={p.world_id}><td className="mono">{p.world_id}</td>
                  <td className="num">{p.last_closed_tick ?? "—"}</td>
                  <td className="num">{p.turns ?? "—"}</td>
                  <td className="mono sub">{Object.entries(p.turns_by_channel ?? {}).map(([c, k]) => `${c === "survey_room" ? "survey" : c} ${k}`).join(" · ") || "—"}</td>
                  <td className="mono sub">{(p.waves_answered ?? []).length ? `ticks ${p.waves_answered!.join(", ")}` : "none yet"}</td>
                  <td className="mono sub">{(p.rungs ?? []).length ? p.rungs!.join(", ") : "full fidelity"}</td></tr>
              ))}
              {!(s.progress ?? []).length && <tr><td colSpan={6} className="sub" style={{ textAlign: "center" }}>starting — the registry write comes after the build</td></tr>}
            </tbody>
          </table></div>
        </div>
      )}
      {s && (
        <>
          <div className="stat-strip" style={{ marginBottom: 20 }}>
            <div className="stat"><div className="k">Worlds</div><div className="v">{s.world_ids.length}</div><div className="d">{s.scenarios.length} scenario(s) × {s.seeds.length} seed(s)</div></div>
            <div className="stat"><div className="k">Cost ledger</div><div className="v">${s.recorded_cost.toFixed(2)}</div><div className="d">derived from billed calls, never kept separately</div></div>
            <div className="stat"><div className="k">Discarded ticks</div><div className="v">{s.discarded_ticks}</div><div className="d">{s.discarded_ticks ? "interrupted before tick-closed — spend unknown but not zero" : "every tick recorded whole"}</div></div>
            <div className="stat"><div className="k">Pins</div><div className="v" style={{ fontSize: 13 }}>{pinned(data?.pins)}</div><div className="d">fixed for the whole run</div></div>
            <div className="stat"><div className="k">Seeds</div><div className="v" style={{ fontSize: 15 }}>{s.seeds.join(", ") || "—"}</div><div className="d">world ids derived, not chosen</div></div>
          </div>

          <div className="sect-title">Scenarios × seeds → worlds</div>
          <div className="panel"><div className="panel-body tight">
            <table className="tbl">
              <thead><tr><th>Scenario</th><th>Variant · price</th><th className="num">Horizon</th><th>Tick unit</th><th>Seed</th><th>World</th><th>Status</th><th className="num">Last tick</th><th>Rungs</th></tr></thead>
              <tbody>
                {s.scenarios.flatMap((sc, si) => s.seeds.map((seed) => {
                  const worldId = worldForCell(digests, seed, { worldIds: s.world_ids, scenarios: s.scenarios.length, seeds: s.seeds.length });
                  const oc = s.outcomes.find((o) => o.world_id === worldId);
                  return (
                    <tr key={`${si}-${seed}`} onClick={() => worldId && setWorld(worldId)} style={{ cursor: "pointer" }}>
                      <td className="mono sub">scenario {si + 1}</td>
                      <td className="strong">{sc.variant.variant_id} · {sc.variant.name} <span className="sub">${sc.price.amount} {sc.price.currency}</span></td>
                      <td className="num">{sc.horizon_ticks}</td>
                      <td className="mono">{sc.tick_unit}</td>
                      <td className="num mono">{seed}</td>
                      <td className="mono">{worldId?.slice(0, 12) ?? "—"}</td>
                      <td>{oc ? <Chip className={oc.status === "completed" ? "ok" : "plain"}>{oc.status.replace("_", " ")}</Chip> : "—"}</td>
                      <td className="num">{oc?.last_closed_tick ?? "—"}</td>
                      <td className="mono sub">{oc?.rungs.length ? oc.rungs.join(", ") : "full fidelity"}</td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div></div>

          {active && (
            <div style={{ marginTop: 24 }}>
              <div className="sect-title">Digest — world <span className="mono">{active.world_id}</span> (seed {active.seed})</div>
              <div className="stat-strip" style={{ marginBottom: 16 }}>
                <div className="stat"><div className="k">Adoption</div><div className="v">{active.adoption != null ? `${(active.adoption * 100).toFixed(1)}%` : "unmeasured"}</div><div className="d">{active.unmeasured_reason ?? "top-2 box, audience-weighted"}</div></div>
                <div className="stat"><div className="k">Polarization</div><div className="v">{active.polarization != null ? active.polarization.toFixed(3) : "—"}</div><div className="d">{active.polarization_reason ?? "size-weighted community divergence"}</div></div>
                <div className="stat"><div className="k">Turns</div><div className="v">{active.turn_count}</div><div className="d">{active.turns_without_intent} without intent</div></div>
                <div className="stat"><div className="k">Word of mouth</div><div className="v">{active.wom_deliveries}</div><div className="d">reach {active.wom_reach}</div></div>
                <div className="stat"><div className="k">Belief move</div><div className="v">{active.belief_move_mean >= 0 ? "+" : ""}{active.belief_move_mean.toFixed(2)}</div><div className="d">mean across turns</div></div>
              </div>
              <div className="grid g2">
                <div className="panel">
                  <div className="panel-head"><h2>Audience PMFs</h2><span className="hint">SSR purchase-intent distributions</span></div>
                  <div className="panel-body" style={{ display: "grid", gap: 12 }}>
                    {Object.entries(active.audience_pmfs).map(([a, pmf]) => (
                      <div key={a}>
                        <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                          <b className="mono">{a}</b>
                          <span className="mono sub" style={{ marginLeft: "auto" }}>mean {pmfMean(pmf).toFixed(2)} · top-2 {(top2box(pmf) * 100).toFixed(0)}% · share {((active.audience_shares[a] ?? 0) * 100).toFixed(0)}%</span>
                        </div>
                        <PmfBar p={pmf} maxWidth="100%" />
                      </div>
                    ))}
                    <PmfLegend />
                  </div>
                </div>
                <div>
                  <div className="panel">
                    <div className="panel-head"><h2>Belief movement</h2><span className="hint">per dimension, mean and absolute</span></div>
                    <div className="panel-body tight"><table className="tbl">
                      <thead><tr><th>Dimension</th><th className="num">Mean Δ</th><th className="num">Mean |Δ|</th></tr></thead>
                      <tbody>
                        {(["value", "fit", "trust"] as const).map((d) => (
                          <tr key={d}><td className="mono">{d}</td>
                            <td className="num" style={{ color: active.belief_movement_mean[d] >= 0 ? "var(--ok)" : "var(--risk)" }}>{active.belief_movement_mean[d] >= 0 ? "+" : ""}{active.belief_movement_mean[d].toFixed(3)}</td>
                            <td className="num">{active.belief_movement_abs[d].toFixed(3)}</td></tr>
                        ))}
                      </tbody>
                    </table></div>
                  </div>
                  <div className="panel">
                    <div className="panel-head"><h2>Action mix</h2></div>
                    <div className="panel-body tight"><table className="tbl"><tbody>
                      {Object.entries(active.action_mix).map(([a, c]) => (
                        <tr key={a}><td className="mono">{a}</td><td className="num">{c}</td></tr>
                      ))}
                    </tbody></table></div>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <Link className="btn sm" href={`/trace?run=${runId}&world=${active.world_id}`}>Open trace view {ICONS.arrow}</Link>
                    <Link className="btn sm" href={`/report?run=${runId}`}>Findings citing this world</Link>
                  </div>
                </div>
              </div>
            </div>
          )}

          {Object.keys(summaries).length > 0 && (
            <div style={{ marginTop: 24 }}>
              <div className="sect-title">Replicate spread — the study&apos;s own variance estimate</div>
              <div className="panel"><div className="panel-body tight"><table className="tbl">
                <thead><tr><th>Scenario</th><th className="num">Adoption spread</th><th className="num">Polarization spread</th><th className="num">Belief-move spread</th><th>Mixed rungs</th></tr></thead>
                <tbody>
                  {Object.values(summaries).map((sm) => (
                    <tr key={sm.scenario_hash}><td className="mono sub">{sm.scenario_hash.slice(0, 12)}…</td>
                      <td className="num">{sm.adoption_spread?.toFixed(3) ?? "no spread — unmeasured"}</td>
                      <td className="num">{sm.polarization_spread?.toFixed(3) ?? "—"}</td>
                      <td className="num">{sm.belief_move_spread?.toFixed(3) ?? "—"}</td>
                      <td>{sm.rung_mixed ? <Chip className="tier-explo">mixed — not comparable</Chip> : <span className="sub">uniform</span>}</td></tr>
                  ))}
                </tbody>
              </table></div></div>
            </div>
          )}
        </>
      )}
    </Shell>
  );
}
