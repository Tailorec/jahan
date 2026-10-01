import React from "react";
import type { WaveDigest } from "@/lib/engine";

const SERIES = ["var(--seg1)", "var(--seg2)", "var(--seg3)", "var(--seg4)", "var(--seg5)"];

/* Purchase intent (top-two box) at every survey wave: one line per audience, and the share-weighted
   whole dashed. Every number is the engine's; the page only places it. */
export function IntentOverWaves({ waves }: { waves: WaveDigest[] }) {
  const W = 520, H = 180, L = 36, R = 12, T = 10, B = 26;
  const ticks = waves.map((w) => w.tick);
  const lo = Math.min(...ticks), hi = Math.max(...ticks);
  const x = (t: number) => L + (hi === lo ? (W - L - R) / 2 : ((t - lo) / (hi - lo)) * (W - L - R));
  const y = (v: number) => T + (1 - v) * (H - T - B);
  const audiences = [...new Set(waves.flatMap((w) => Object.keys(w.audience_adoption ?? {})))].sort();
  const path = (points: [number, number][]) => points.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const whole = waves.filter((w) => w.adoption != null).map((w) => [w.tick, w.adoption!] as [number, number]);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W }} role="img" aria-label="Purchase intent over survey waves, by audience">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize="10" fill="var(--ink-3)">{Math.round(v * 100)}%</text></g>
        ))}
        {ticks.map((t) => <text key={t} x={x(t)} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--ink-3)">tick {t}</text>)}
        {audiences.map((a, i) => {
          const points = waves.filter((w) => w.audience_adoption?.[a] != null).map((w) => [w.tick, w.audience_adoption[a]] as [number, number]);
          return <g key={a}><path d={path(points)} fill="none" stroke={SERIES[i % SERIES.length]} strokeWidth="2" />
            {points.map(([t, v]) => <circle key={t} cx={x(t)} cy={y(v)} r="3" fill={SERIES[i % SERIES.length]} />)}</g>;
        })}
        {whole.length > 0 && <path d={path(whole)} fill="none" stroke="var(--ink-2)" strokeWidth="1.5" strokeDasharray="4 3" />}
      </svg>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12 }}>
        {audiences.map((a, i) => <span key={a}><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: SERIES[i % SERIES.length], marginRight: 4 }} />{a}</span>)}
        <span style={{ color: "var(--ink-2)" }}>- - - all audiences, share-weighted</span>
      </div>
      <div style={{ overflowX: "auto" }}>
      <table className="tbl" style={{ marginTop: 8 }}>
        <thead><tr><th className="num">Tick</th><th className="num">Answered</th><th className="num">Adoption</th><th className="num">Reached by a channel</th><th className="num">Not reached</th></tr></thead>
        <tbody>{waves.map((w) => (
          <tr key={w.tick}><td className="num">{w.tick}</td><td className="num">{w.respondents}</td>
            <td className="num">{w.adoption != null ? `${(w.adoption * 100).toFixed(1)}%` : "—"}</td>
            <td className="num">{w.reached}{w.reached_adoption != null ? ` · ${(w.reached_adoption * 100).toFixed(1)}%` : ""}</td>
            <td className="num">{w.unreached}{w.unreached_adoption != null ? ` · ${(w.unreached_adoption * 100).toFixed(1)}%` : ""}</td></tr>
        ))}</tbody>
      </table>
      </div>
    </div>
  );
}
