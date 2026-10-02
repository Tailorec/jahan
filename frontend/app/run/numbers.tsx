"use client";

import React from "react";
import { Kpi, Section, Tip } from "@/components/ui";
import { BeliefMoves, CommunityIntent, IntentDiverging, IntentOverWaves } from "@/components/charts";
import type { OutcomeDigest } from "@/lib/engine";


/* The world's numbers — every one the engine's. While the study runs they are its digest as of the last
   closed tick; once it ends, the final digest the report is built on. */
export default function Numbers({ d, asOf }: { d: OutcomeDigest; asOf: string }) {
  const waves = d.waves ?? [];
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

      <div style={{ display: "grid", gap: 16 }}>
        <Section icon="pie" title="Purchase intent by audience" tip="The SSR purchase-intent distribution at the latest wave: each audience's share at every point of the five-point scale. Bars are centred on 'maybe', so 'would not buy' extends left and 'would buy' extends right; the top-two box is the share who probably or definitely would.">
          {Object.entries(d.audience_pmfs).length === 0
            ? <p className="sub" style={{ fontSize: 12 }}>unmeasured: {d.unmeasured_reason ?? "no wave answered yet"}</p>
            : <IntentDiverging pmfs={d.audience_pmfs} weights={d.audience_shares} caption={(_, share) => `${(share * 100).toFixed(0)}% of the market`} />}
        </Section>

        <Section icon="sliders" title="Belief movement per dimension" tip="For value, fit and trust: the solid bar is the net change per turn (which way beliefs moved on balance) and the shaded band is the average size of a move in either direction. A short bar in a wide band means personas moved a lot but in opposite directions, so the moves cancelled out. Survey answers only read beliefs, so they are not counted.">
          <BeliefMoves mean={d.belief_movement_mean} abs={d.belief_movement_abs} />
        </Section>
      </div>

      <Section icon="fork" title="Communities" tip="Intent in each of the social network's communities at the latest wave — clusters of people tied more to each other than to the rest, found when the population was drawn and fixed for the run. They cut across audiences, so a community can lean differently from any audience in it. Polarization says how far communities' intent differs.">
        <CommunityIntent d={d} />
      </Section>

      <Section icon="layers" title="Action mix" tip="What personas did across every channel, survey answers included.">
        <div className="mix-grid">
          {Object.entries(d.action_mix).sort((a, b) => b[1] - a[1]).map(([a, n]) => (
            <div key={a} className="bar-row" style={{ cursor: "default" }}>
              <span style={{ minWidth: 90 }}>{a.replace(/_/g, " ")}</span>
              <span className="bar"><span style={{ width: `${(n / mixTotal) * 100}%` }} /></span>
              <span className="mono" style={{ minWidth: 50, textAlign: "right" }}>{n}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
