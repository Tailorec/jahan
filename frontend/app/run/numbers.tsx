"use client";

import React from "react";
import { Kpi, PmfBar, Section, Tip } from "@/components/ui";
import { IntentOverWaves } from "@/components/charts";
import { pmfMean, top2box, type OutcomeDigest } from "@/lib/engine";

const DIM = ["value", "fit", "trust"] as const;

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
            : <IntentDiverging pmfs={d.audience_pmfs} shares={d.audience_shares} />}
        </Section>

        <Section icon="sliders" title="Belief movement per dimension" tip="For value, fit and trust: the solid bar is the net change per turn (which way beliefs moved on balance) and the shaded band is the average size of a move in either direction. A short bar in a wide band means personas moved a lot but in opposite directions, so the moves cancelled out. Survey answers only read beliefs, so they are not counted.">
          <BeliefMoves mean={d.belief_movement_mean} abs={d.belief_movement_abs} />
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

const sentence = (s: string) => { const t = s.replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
const LEVELS = ["definitely not", "probably not", "maybe", "probably yes", "definitely yes"];
const DIM_TIP: Record<string, string> = {
  value: "Whether the product seems worth its price.",
  fit: "Whether the product suits the persona's life.",
  trust: "Whether the persona believes the brand's claims.",
};

/* Each audience's intent as a bar centred on "maybe": would-not-buy extends left, would-buy right, so rows
   line up and compare at a glance. The layout scales so the longest side of any row fills its half. */
function IntentDiverging({ pmfs, shares }: { pmfs: Record<string, number[]>; shares: Record<string, number> }) {
  const [hover, setHover] = React.useState<{ audience: string; level: number; at: number } | null>(null);
  const rows = Object.entries(pmfs).sort((a, b) => (shares[b[0]] ?? 0) - (shares[a[0]] ?? 0));
  const left = (p: number[]) => p[0] + p[1] + p[2] / 2;
  const right = (p: number[]) => p[2] / 2 + p[3] + p[4];
  const reach = Math.max(...rows.flatMap(([, p]) => [left(p), right(p)]), 0.01);
  const scale = 50 / reach; // percent of the bar's width per unit of probability
  return (
    <div className="div-chart">
      <div className="div-row div-head sub"><span /><div className="div-axis"><span>← would not buy</span><span>maybe</span><span>would buy →</span></div><span /></div>
      {rows.map(([audience, p]) => {
        let at = 50 - left(p) * scale;
        return (
          <div key={audience} className="div-row">
            <div className="div-name">
              <b>{sentence(audience)}</b>
              <span className="sub">{((shares[audience] ?? 0) * 100).toFixed(0)}% of the market</span>
            </div>
            <div className="div-bar" onMouseLeave={() => setHover(null)}>
              <span className="div-mid" />
              {p.map((v, level) => {
                const width = v * scale, x = at;
                at += width;
                const on = hover?.audience === audience && hover.level === level;
                return (
                  <span key={level} className={`div-seg likert-${level + 1}${on ? " on" : ""}`} style={{ left: `${x}%`, width: `${width}%` }}
                    onMouseEnter={() => setHover({ audience, level, at: x + width / 2 })} aria-label={`${LEVELS[level]}: ${(v * 100).toFixed(1)}%`}>
                    {width >= 7 ? `${Math.round(v * 100)}%` : ""}
                  </span>
                );
              })}
              {hover?.audience === audience && (
                <span className="div-tip" style={{ left: `${Math.min(85, Math.max(15, hover.at))}%` }}>
                  <b>{(p[hover.level] * 100).toFixed(1)}%</b> {LEVELS[hover.level]}
                </span>
              )}
            </div>
            <div className="div-stat">
              <b>{(top2box(p) * 100).toFixed(0)}%</b>
              <span className="sub">would buy</span>
              <span className="sub mono">mean {pmfMean(p).toFixed(2)}</span>
            </div>
          </div>
        );
      })}
      <div className="pmf-legend">
        {LEVELS.map((label, i) => <span key={label}><i className={`likert-${i + 1}`} />{label}</span>)}
      </div>
    </div>
  );
}

/* Net direction and size of belief moves: a solid bar from zero to the mean change, over a shaded band as
   wide as the average move either way. Both share one scale, centred on zero. */
function BeliefMoves({ mean, abs }: { mean: Record<string, number>; abs: Record<string, number> }) {
  const reach = Math.max(0.01, ...DIM.map((k) => Math.max(Math.abs(mean[k] ?? 0), abs[k] ?? 0)));
  const pos = (v: number) => 50 + (v / reach) * 46; // keep 4% clear at each end
  return (
    <div className="moves">
      <div className="moves-row moves-head sub"><span /><div className="moves-axis"><span>−{reach.toFixed(2)}</span><span>no change</span><span>+{reach.toFixed(2)}</span></div><span /></div>
      {DIM.map((k) => {
        const m = mean[k] ?? 0, a = abs[k] ?? 0;
        const up = m >= 0;
        return (
          <div key={k} className="moves-row">
            <span className="moves-name">{k}<Tip>{DIM_TIP[k]}</Tip></span>
            <div className="moves-track" aria-label={`${k}: net ${up ? "+" : ""}${m.toFixed(3)}, average move ${a.toFixed(3)}`}>
              <span className="moves-band" style={{ left: `${pos(-a)}%`, width: `${pos(a) - pos(-a)}%` }} />
              <span className="moves-zero" />
              <span className={`moves-bar ${up ? "up" : "down"}`} style={{ left: `${Math.min(pos(0), pos(m))}%`, width: `${Math.abs(pos(m) - pos(0))}%` }} />
            </div>
            <span className="moves-val">
              <b className={up ? "up" : "down"}>{up ? "+" : "−"}{Math.abs(m).toFixed(3)}</b>
              <span className="sub"> net · ±{a.toFixed(3)} typical</span>
            </span>
          </div>
        );
      })}
      <div className="moves-key sub">
        <span><i className="moves-key-bar" />net change per turn</span>
        <span><i className="moves-key-band" />typical size of a move</span>
      </div>
    </div>
  );
}

