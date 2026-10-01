"use client";

import React from "react";
import { Kpi, PmfBar, PmfLegend, Section } from "@/components/ui";
import { IntentOverWaves } from "@/components/charts";
import { pmfMean, top2box, type OutcomeDigest } from "@/lib/engine";

const DIM = ["value", "fit", "trust"] as const;

/* The world's numbers — every one the engine's. While the study runs they are its digest as of the last
   closed tick; once it ends, the final digest the report is built on. */
export default function Numbers({ d, asOf }: { d: OutcomeDigest; asOf: string }) {
  const waves = d.waves ?? [];
  const maxAbs = Math.max(0.001, ...DIM.map((k) => Math.abs(d.belief_movement_abs[k] ?? 0)));
  const mixTotal = Object.values(d.action_mix).reduce((a, b) => a + b, 0) || 1;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <p className="sub" style={{ fontSize: 12 }}>{asOf}</p>
      <div className="kpis">
        <Kpi icon="target" label="Adoption" tip="Share-weighted top-two-box purchase intent at the last survey wave." value={d.adoption != null ? `${(d.adoption * 100).toFixed(1)}%` : "unmeasured"} note={d.adoption == null ? d.unmeasured_reason ?? undefined : undefined} />
        <Kpi icon="fork" label="Polarization" tip="How far the network's communities split in intent, size-weighted. Unmeasured when no communities formed." value={d.polarization != null ? d.polarization.toFixed(3) : "—"} note={d.polarization == null ? d.polarization_reason ?? undefined : undefined} />
        <Kpi icon="forum" label="Turns" tip="Every turn the world recorded; survey answers that could not be scored are counted, never zeroed." value={d.turn_count.toLocaleString()} note={`${d.turns_without_intent} without intent`} />
        <Kpi icon="wom" label="Word of mouth" tip="Messages passed person to person, and how many personas they reached." value={d.wom_deliveries.toLocaleString()} note={`reached ${d.wom_reach}`} />
        <Kpi icon="sliders" label="Belief move" tip="Mean belief change per turn across value, fit and trust." value={`${d.belief_move_mean >= 0 ? "+" : ""}${d.belief_move_mean.toFixed(3)}`} />
      </div>

      <Section icon="survey" title="Purchase intent over survey waves" tip="Top-two-box intent at every survey wave so far, one line per audience and the share-weighted whole dashed. A new point appears when a wave's tick closes.">
        {waves.length ? <IntentOverWaves waves={waves} /> : <p className="sub" style={{ fontSize: 12 }}>No wave answered yet{d.unmeasured_reason ? `: ${d.unmeasured_reason}` : ""}.</p>}
      </Section>

      <div className="grid g2">
        <Section icon="pie" title="Audience PMFs" tip="SSR purchase-intent distributions at the latest wave: the share of each audience at every point of the five-point scale.">
          <div style={{ display: "grid", gap: 12 }}>
            {Object.entries(d.audience_pmfs).length === 0 && <p className="sub" style={{ fontSize: 12 }}>unmeasured: {d.unmeasured_reason ?? "no wave answered yet"}</p>}
            {Object.entries(d.audience_pmfs).map(([a, pmf]) => (
              <div key={a}>
                <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <b>{a.replace(/_/g, " ")}</b>
                  <span className="mono sub" style={{ marginLeft: "auto", fontSize: 11 }}>mean {pmfMean(pmf).toFixed(2)} · top-2 {(top2box(pmf) * 100).toFixed(0)}% · share {((d.audience_shares[a] ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <PmfBar p={pmf} maxWidth="100%" />
              </div>
            ))}
            {Object.keys(d.audience_pmfs).length > 0 && <PmfLegend />}
          </div>
        </Section>

        <Section icon="sliders" title="Belief movement per dimension" tip="Mean change per turn (signed: which way beliefs moved) and mean absolute change (how much they moved at all), for value, fit and trust. Survey answers only read beliefs, so they are not in it.">
          <div style={{ display: "grid", gap: 12 }}>
            {DIM.map((k) => {
              const mean = d.belief_movement_mean[k] ?? 0, abs = d.belief_movement_abs[k] ?? 0;
              return (
                <div key={k} className="move-row">
                  <b>{k}</b>
                  <div className="move-bars">
                    <div className="move-axis"><span className="move-signed" style={{ [mean >= 0 ? "left" : "right"]: "50%", width: `${(Math.abs(mean) / maxAbs) * 50}%`, background: mean >= 0 ? "var(--ok)" : "var(--risk)" }} /></div>
                    <div className="move-abs"><span style={{ width: `${(abs / maxAbs) * 100}%` }} /></div>
                  </div>
                  <span className="mono" style={{ fontSize: 12, color: mean >= 0 ? "var(--ok)" : "var(--risk)" }}>{mean >= 0 ? "+" : ""}{mean.toFixed(3)}</span>
                  <span className="mono sub" style={{ fontSize: 12 }}>|{abs.toFixed(3)}|</span>
                </div>
              );
            })}
            <p className="sub" style={{ fontSize: 11 }}>top bar: mean Δ, centred on zero · bottom bar: mean |Δ|</p>
          </div>
        </Section>
      </div>

      <div className="grid g2">
        <Section icon="layers" title="Action mix" tip="What personas did across every channel, survey answers included.">
          <div style={{ display: "grid", gap: 6 }}>
            {Object.entries(d.action_mix).sort((a, b) => b[1] - a[1]).map(([a, n]) => (
              <div key={a} className="bar-row" style={{ cursor: "default" }}>
                <span style={{ minWidth: 90 }}>{a}</span>
                <span className="bar"><span style={{ width: `${(n / mixTotal) * 100}%` }} /></span>
                <span className="mono" style={{ minWidth: 50, textAlign: "right" }}>{n}</span>
              </div>
            ))}
          </div>
        </Section>
        <Section icon="fork" title="Communities" tip="Intent by the network's communities at the latest wave. Communities are fixed when the population is drawn; when none formed, the reason is shown.">
          {Object.keys(d.community_pmfs).length === 0
            ? <p className="sub" style={{ fontSize: 12 }}>{d.polarization_reason ?? "No communities formed in this network."}</p>
            : (
              <div style={{ display: "grid", gap: 8 }}>
                {Object.entries(d.community_pmfs).map(([c, pmf]) => (
                  <div key={c} className="row" style={{ gap: 8 }}>
                    <span className="mono" style={{ minWidth: 90, fontSize: 12 }}>{c} <span className="sub">({d.community_sizes[c] ?? 0})</span></span>
                    <div style={{ flex: 1 }}><PmfBar p={pmf} maxWidth="100%" /></div>
                    <span className="mono sub" style={{ fontSize: 11 }}>{(top2box(pmf) * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            )}
        </Section>
      </div>
    </div>
  );
}
