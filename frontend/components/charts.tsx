"use client";

import React from "react";
import type { WaveDigest } from "@/lib/engine";

/* A validated categorical order (dataviz validator, light surface): adjacent hues stay apart for normal and
   colour-blind vision. Assigned in this order to audiences sorted by name, never cycled by rank. */
const SERIES = ["#be7200", "#0087a0", "#c0504d", "#9c63c2", "#2f8a3e"];
const WHOLE = "var(--ink)";

const pretty = (s: string) => s.replace(/_/g, " ");
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const delta = (v: number | null | undefined, prev: number | null | undefined) =>
  v == null || prev == null ? null : v - prev;

interface Series { key: string; label: string; color: string; dashed?: boolean; points: [number, number][] }

/* Purchase intent (top-two box) at every survey wave: the share-weighted whole, and either each audience or
   the personas a channel had reached against those it had not. Every number is the engine's; the page only
   places it. */
export function IntentOverWaves({ waves }: { waves: WaveDigest[] }) {
  const [view, setView] = React.useState<"audience" | "reach">("audience");
  const [hover, setHover] = React.useState<number | null>(null);
  // Drawn at the width it is shown at, so text stays its real size from a phone to a wide screen.
  const box = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(760);
  React.useEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => setWidth(Math.max(300, Math.round(el.clientWidth)));
    fit();
    const watch = new ResizeObserver(fit);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const reachable = waves.some((w) => w.reached > 0 && w.reached_adoption != null);
  const audiences = [...new Set(waves.flatMap((w) => Object.keys(w.audience_adoption ?? {})))].sort();

  const whole: Series = { key: "whole", label: "All audiences", color: WHOLE, dashed: true, points: waves.filter((w) => w.adoption != null).map((w) => [w.tick, w.adoption!]) };
  const parts: Series[] = view === "reach" && reachable
    ? [
        { key: "reached", label: "Reached by a channel", color: SERIES[1], points: waves.filter((w) => w.reached_adoption != null).map((w) => [w.tick, w.reached_adoption!]) },
        { key: "unreached", label: "Not reached", color: SERIES[0], points: waves.filter((w) => w.unreached_adoption != null).map((w) => [w.tick, w.unreached_adoption!]) },
      ]
    // One audience is the whole: drawing it twice would only overlap.
    : audiences.length < 2 ? [] : audiences.map((a, i) => ({ key: a, label: pretty(a), color: SERIES[i % SERIES.length], points: waves.filter((w) => w.audience_adoption?.[a] != null).map((w) => [w.tick, w.audience_adoption[a]]) }));
  const series = [...parts, whole].filter((s) => s.points.length > 0);

  // Geometry: the plot zooms to where the values are, on 5-point steps, so movement between waves is visible.
  const narrow = width < 560;
  // On a narrow screen the legend above names the lines, so the end labels give their room back to the plot.
  const W = width, H = narrow ? 220 : 260, L = 44, R = narrow ? 16 : 168, T = 14, B = 30;
  const values = series.flatMap((s) => s.points.map(([, v]) => v));
  const lo = Math.max(0, Math.floor((Math.min(...values, 1) - 0.03) * 20) / 20);
  const hi = Math.min(1, Math.ceil((Math.max(...values, 0) + 0.03) * 20) / 20);
  const span = Math.max(0.05, hi - lo);
  const step = span > 0.4 ? 0.1 : span > 0.15 ? 0.05 : 0.025;
  const grid = Array.from({ length: Math.floor(span / step + 1e-9) + 1 }, (_, k) => lo + k * step);
  const ticks = waves.map((w) => w.tick);
  const tLo = Math.min(...ticks), tHi = Math.max(...ticks);
  const x = (t: number) => L + (tHi === tLo ? (W - L - R) / 2 : ((t - tLo) / (tHi - tLo)) * (W - L - R));
  const y = (v: number) => T + (1 - (v - lo) / span) * (H - T - B);
  const path = (pts: [number, number][]) => pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  // Direct labels at each line's end, pushed apart so they never overlap.
  const ends = (narrow ? [] : series).map((s) => ({ s, v: s.points[s.points.length - 1][1], at: y(s.points[s.points.length - 1][1]) })).sort((a, b) => a.at - b.at);
  for (let i = 1; i < ends.length; i++) ends[i].at = Math.max(ends[i].at, ends[i - 1].at + 15);
  const overflow = ends.length ? ends[ends.length - 1].at - (H - B) : 0;
  if (overflow > 0) ends.forEach((e) => (e.at -= overflow));

  const hw = hover != null ? waves[hover] : null;
  const prev = hover != null && hover > 0 ? waves[hover - 1] : null;
  const valueAt = (s: Series, t: number) => s.points.find(([pt]) => pt === t)?.[1] ?? null;

  return (
    <div className="intent-chart">
      <div className="intent-head">
        <div className="intent-legend" aria-label="Lines">
          {series.map((s) => (
            <span key={s.key} className="row" style={{ gap: 6 }}>
              <svg width="22" height="10" aria-hidden><line x1="1" x2="21" y1="5" y2="5" stroke={s.color} strokeWidth={s.dashed ? 2.5 : 2} strokeDasharray={s.dashed ? "5 3" : undefined} /></svg>
              {s.label}{s.dashed ? <span className="sub"> · share-weighted</span> : null}
            </span>
          ))}
        </div>
        {reachable && (
          <div className="segctl" role="tablist" aria-label="Split the whole by">
            <button type="button" role="tab" aria-selected={view === "audience"} className={view === "audience" ? "on" : ""} onClick={() => setView("audience")}>By audience</button>
            <button type="button" role="tab" aria-selected={view === "reach"} className={view === "reach" ? "on" : ""} onClick={() => setView("reach")}>Reached vs not</button>
          </div>
        )}
      </div>

      <div className="intent-plot" ref={box} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
          aria-label={`Purchase intent over survey waves: ${series.map((s) => `${s.label} ${pct(s.points[s.points.length - 1][1])} at the last wave`).join(", ")}`}>
          {grid.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
              <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)">{Math.round(v * 1000) / 10}%</text>
            </g>
          ))}
          {waves.map((w, i) => <text key={w.tick} x={x(w.tick)} y={H - 9} textAnchor={waves.length > 1 && i === 0 ? "start" : waves.length > 1 && i === waves.length - 1 ? "end" : "middle"} fontSize="11" fill="var(--ink-3)">{narrow ? `t${w.tick}` : `wave · t${w.tick}`}</text>)}
          {hw && <line x1={x(hw.tick)} x2={x(hw.tick)} y1={T} y2={H - B} stroke="var(--ink-3)" strokeDasharray="3 3" />}
          {series.map((s) => (
            <g key={s.key}>
              <path d={path(s.points)} fill="none" stroke={s.color} strokeWidth={s.dashed ? 2.5 : 2} strokeDasharray={s.dashed ? "6 4" : undefined} strokeLinejoin="round" />
              {s.points.map(([t, v]) => (
                <circle key={t} cx={x(t)} cy={y(v)} r={hw?.tick === t ? 5.5 : 4} fill={s.color} stroke="var(--bg)" strokeWidth="2" />
              ))}
            </g>
          ))}
          {ends.map(({ s, v, at }) => (
            <g key={s.key}>
              <circle cx={W - R + 12} cy={at - 4} r="4" fill={s.color} />
              <text x={W - R + 21} y={at} fontSize="12" fill="var(--ink)" style={{ fontWeight: s.dashed ? 700 : 500 }}>
                {pct(v, 0)} <tspan fill="var(--ink-2)" style={{ fontWeight: 400 }}>{s.label.length > 16 ? `${s.label.slice(0, 15)}…` : s.label}</tspan>
              </text>
            </g>
          ))}
          {/* Hit targets: one column per wave, wider than any mark. */}
          {waves.map((w, i) => {
            const half = waves.length > 1 ? (W - L - R) / (waves.length - 1) / 2 : (W - L - R) / 2;
            return <rect key={w.tick} x={x(w.tick) - half} y={T} width={half * 2} height={H - T - B} fill="transparent" onMouseEnter={() => setHover(i)} />;
          })}
        </svg>
        {hw && (
          // Centred on the wave, but kept inside the chart so a narrow screen never clips it.
          <div className="intent-tip" style={{ left: Math.min(W - 124, Math.max(124, x(hw.tick))) }}>
            <b>Wave at tick {hw.tick}</b> <span className="sub">· {hw.respondents} answered</span>
            {series.map((s) => {
              const v = valueAt(s, hw.tick), d = delta(v, prev ? valueAt(s, prev.tick) : null);
              return (
                <div key={s.key} className="row" style={{ gap: 6 }}>
                  <span className="swatch" style={{ background: s.color }} />{s.label}
                  <span className="mono" style={{ marginLeft: "auto", fontWeight: s.dashed ? 700 : 400 }}>{pct(v)}</span>
                  {d != null && Math.abs(d) >= 0.0005 && <span className="mono" style={{ color: d > 0 ? "var(--ok)" : "var(--risk)", minWidth: 52, textAlign: "right" }}>{d > 0 ? "▲" : "▼"}{(Math.abs(d) * 100).toFixed(1)}</span>}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="tbl nowrap" style={{ marginTop: 8 }}>
          <thead><tr><th className="num">Wave</th><th className="num">Answered</th><th className="num">Adoption</th><th className="num">Change</th><th className="num">Reached by a channel</th><th className="num">Not reached</th></tr></thead>
          <tbody>{waves.map((w, i) => {
            const d = delta(w.adoption, i > 0 ? waves[i - 1].adoption : null);
            return (
              <tr key={w.tick}>
                <td className="num">t{w.tick}</td><td className="num">{w.respondents}</td>
                <td className="num"><b>{pct(w.adoption)}</b></td>
                <td className="num" style={{ color: d == null || Math.abs(d) < 0.0005 ? "var(--ink-3)" : d > 0 ? "var(--ok)" : "var(--risk)" }}>{d == null ? "—" : Math.abs(d) < 0.0005 ? "±0.0 pts" : `${d > 0 ? "+" : "−"}${(Math.abs(d) * 100).toFixed(1)} pts`}</td>
                <td className="num">{w.reached}{w.reached_adoption != null ? ` · ${pct(w.reached_adoption)}` : ""}</td>
                <td className="num">{w.unreached}{w.unreached_adoption != null ? ` · ${pct(w.unreached_adoption)}` : ""}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
    </div>
  );
}
