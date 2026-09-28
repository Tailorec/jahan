"use client";

import React from "react";
import { Callout, Chip } from "@/components/ui";
import { useApi } from "@/lib/api";
import { explainGate, gateMeter, type GateMeter } from "@/lib/gates";
import type { GateResult } from "@/lib/engine";

/* The social graph a run's population was built with, as the engine reads it: its shape, the checks it
   passed, how ties are spread, the hubs, and one persona's circle drawn as rings. */

interface Person { id: string; audience: string | null; community: string | null; ties: number; depth?: number }
interface GraphView {
  graph_hash: string;
  summary: { personas: number; ties: number; mean_ties: number; most_ties: number; fewest_ties: number; audience_assortativity: number | null };
  checks: GateResult[];
  degree_histogram: [number, number][];
  hubs: Person[];
  circle: { center: string; friends: number; friends_of_friends: number; nodes: Person[]; edges: [number, number, number][] };
}

const PALETTE = ["var(--seg1)", "var(--seg2)", "var(--seg3)", "var(--seg4)", "var(--seg5)", "oklch(0.7 0.02 75)"];

export function SocialGraph({ runId, Meter, Tip }: {
  runId: string;
  Meter: (p: { meter: GateMeter; passed: boolean }) => React.ReactElement;
  Tip: (p: { text: string }) => React.ReactElement;
}) {
  const [center, setCenter] = React.useState<string | null>(null);
  const [typed, setTyped] = React.useState("");
  const q = center ? `?persona=${encodeURIComponent(center)}` : "";
  const { data, error } = useApi<GraphView>(`/api/runs/${encodeURIComponent(runId)}/graph${q}`);
  const audiences = React.useMemo(() => [...new Set((data?.hubs ?? []).concat(data?.circle.nodes ?? []).map((p) => p.audience ?? "—"))].sort(), [data]);
  const color = (a: string | null) => PALETTE[Math.max(0, audiences.indexOf(a ?? "—")) % PALETTE.length];

  if (error) {
    return <div className="empty"><b>No saved network for this run.</b>{/no social graph/.test(error) ? " It was gated before networks were saved, or its population was never built. Run the gate again and the network is kept." : ` ${error}`}</div>;
  }
  if (!data) return <div className="empty"><b>Reading the network…</b></div>;
  const s = data.summary;
  const maxCount = Math.max(1, ...data.degree_histogram.map(([, n]) => n));

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="stat-strip">
        <div className="stat"><div className="k">Personas</div><div className="v">{s.personas.toLocaleString()}</div><div className="d">each one a node</div></div>
        <div className="stat"><div className="k">Ties<Tip text="A tie is a relationship between two personas — who knows whom. Stronger ties join more similar people." /></div><div className="v">{s.ties.toLocaleString()}</div><div className="d">relationships in all</div></div>
        <div className="stat"><div className="k">Ties per person</div><div className="v">{s.mean_ties}</div><div className="d">from {s.fewest_ties} to {s.most_ties}</div></div>
        <div className="stat"><div className="k">Follows audiences<Tip text="Audience assortativity: whether ties join people of the same declared audience more than chance. 0 means ties ignore audiences, 1 that people only know their own audience. At 0.9 or above the network merely restates the audiences, and the population is refused." /></div><div className="v">{s.audience_assortativity === null ? "—" : s.audience_assortativity.toFixed(2)}</div><div className="d">0 ignores them · 1 only within</div></div>
        <div className="stat"><div className="k">Fingerprint</div><div className="v mono" style={{ fontSize: 13 }}>{data.graph_hash.slice(0, 12)}…</div><div className="d">the same draw builds this exact network</div></div>
      </div>

      {data.checks.length > 0 && (
        <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)" }}>
          {data.checks.map((r, i) => {
            const words = explainGate(r);
            const meter = gateMeter(r);
            return (
              <div key={i} title={words.question} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(140px, 1.2fr) 64px", gap: 14, alignItems: "center", padding: "9px 12px", borderTop: i ? "1px solid var(--line)" : 0 }}>
                <span><b>{words.title.replace("Social network: ", "")}</b><div className="sub" style={{ fontSize: 11 }}>{words.result}</div></span>
                <span><Meter meter={meter} passed={r.passed} /><div className="mono sub" style={{ fontSize: 11, marginTop: 7 }}>{meter.short}</div></span>
                <span style={{ justifySelf: "end" }}>{r.passed ? <Chip className="ok">pass</Chip> : <Chip className="risk">fail</Chip>}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid g2" style={{ gap: 14 }}>
        <div>
          <div className="sub" style={{ fontSize: 12, marginBottom: 6 }}>How many ties people have — most have a few, a handful are hubs</div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 110, borderBottom: "1px solid var(--line-2)" }}>
            {data.degree_histogram.map(([ties, n]) => (
              <div key={ties} title={`${n.toLocaleString()} ${n === 1 ? "person has" : "people have"} ${ties} ties`} style={{ flex: 1, minWidth: 2, height: `${(n / maxCount) * 100}%`, background: "var(--primary)", opacity: 0.75, borderRadius: "2px 2px 0 0" }} />
            ))}
          </div>
          <div className="sub mono" style={{ fontSize: 10.5, display: "flex", justifyContent: "space-between", marginTop: 3 }}>
            <span>{data.degree_histogram[0]?.[0]} ties</span><span>{data.degree_histogram[data.degree_histogram.length - 1]?.[0]} ties</span>
          </div>
        </div>
        <div>
          <div className="sub" style={{ fontSize: 12, marginBottom: 6 }}>Best-connected — click to see their circle</div>
          <div style={{ display: "grid", gap: 3 }}>
            {data.hubs.slice(0, 6).map((h) => (
              <button key={h.id} className="btn sm quiet" style={{ justifyContent: "flex-start", gap: 8 }} onClick={() => setCenter(h.id)}>
                <span style={{ width: 9, height: 9, borderRadius: "50%", background: color(h.audience) }} />
                <span className="mono" style={{ fontSize: 11.5 }}>{h.id}</span>
                <span className="sub" style={{ marginLeft: "auto" }}>{h.ties} ties · {h.audience ?? "no audience"}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <b style={{ fontSize: 13 }}>One persona&apos;s circle</b>
          <span className="sub" style={{ fontSize: 12 }}>
            <span className="mono">{data.circle.center}</span> · {data.circle.friends} friends · {data.circle.friends_of_friends.toLocaleString()} friends of friends
            {data.circle.nodes.length - 1 - data.circle.friends < data.circle.friends_of_friends && <> (showing the {Math.max(0, data.circle.nodes.length - 1 - data.circle.friends)} with the strongest ties)</>}
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
            <input className="input mono" style={{ width: 230, fontSize: 12 }} placeholder="persona id, from the table below" value={typed} onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && typed.trim()) setCenter(typed.trim()); }} />
            <button className="btn sm" disabled={!typed.trim()} onClick={() => setCenter(typed.trim())}>Show</button>
          </span>
        </div>
        <Circle view={data.circle} color={color} onPick={setCenter} />
        <div className="sub" style={{ fontSize: 11.5, display: "flex", gap: 12, flexWrap: "wrap" }}>
          {audiences.map((a) => <span key={a}><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: color(a), marginRight: 4 }} />{a}</span>)}
          <span>· inner ring: friends · outer ring: their friends · thicker line: stronger tie · click anyone to centre on them</span>
        </div>
      </div>
      {!data.circle.nodes.some((p) => p.community) && (
        <Callout icon="info"><div>No communities were found in this network: the partition the engine looks for (4–8 groups, each at least 5% of people, clearly separated) did not form. That is recorded, not hidden — the network still passed its checks.</div></Callout>
      )}
    </div>
  );
}

/* The circle as rings: the persona at the centre, friends on the inner ring, friends of friends on the outer
   ring beside the friend they come through. A layout only — every node and tie is the engine's. */
function Circle({ view, color, onPick }: { view: GraphView["circle"]; color: (a: string | null) => string; onPick: (id: string) => void }) {
  const size = 560, mid = size / 2;
  const at = React.useMemo(() => {
    const where: [number, number][] = view.nodes.map(() => [mid, mid]);
    const inner = view.nodes.map((p, i) => ({ p, i })).filter(({ p }) => p.depth === 1).map(({ i }) => i);
    // Each friend of a friend sits by the friend it is most strongly tied to.
    const via = new Map<number, [number, number]>();
    for (const [u, v, w] of view.edges) {
      for (const [a, b] of [[u, v], [v, u]]) {
        if (view.nodes[a].depth === 2 && view.nodes[b].depth === 1 && w > (via.get(a)?.[1] ?? -1)) via.set(a, [b, w]);
      }
    }
    const byFriend = new Map<number, number[]>(inner.map((f) => [f, []]));
    view.nodes.forEach((p, i) => { if (p.depth === 2) { const f = via.get(i)?.[0] ?? inner[0] ?? -1; byFriend.set(f, [...(byFriend.get(f) ?? []), i]); } });
    // Each friend's slice of the circle is as wide as the people who come through them, so none is crowded.
    const units = inner.reduce((t, f) => t + Math.max(1, byFriend.get(f)!.length), 0) || 1;
    let start = -Math.PI / 2;
    for (const f of inner) {
      const members = byFriend.get(f)!;
      const width = (2 * Math.PI * Math.max(1, members.length)) / units;
      const centre = start + width / 2;
      where[f] = [mid + 115 * Math.cos(centre), mid + 115 * Math.sin(centre)];
      members.forEach((i, k) => {
        const a = start + (width * (k + 0.5)) / members.length;
        const r = 215 + (members.length > 24 ? (k % 2) * 22 : 0);
        where[i] = [mid + r * Math.cos(a), mid + r * Math.sin(a)];
      });
      start += width;
    }
    return where;
  }, [view, mid]);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: "100%", maxWidth: 620, display: "block", margin: "8px auto" }} role="img" aria-label="one persona's circle of friends">
      {view.edges.map(([u, v, w], k) => {
        const inner = view.nodes[u].depth! < 2 && view.nodes[v].depth! < 2;
        return <line key={k} x1={at[u][0]} y1={at[u][1]} x2={at[v][0]} y2={at[v][1]} stroke="var(--ink-3)" strokeOpacity={inner ? 0.55 : 0.18} strokeWidth={0.5 + w * 2.5} />;
      })}
      {view.nodes.map((p, i) => (
        <g key={p.id} onClick={() => onPick(p.id)} style={{ cursor: "pointer" }}>
          <title>{`${p.id}\n${p.audience ?? "no audience"} · ${p.ties} ties${p.community ? ` · community ${p.community}` : ""}`}</title>
          <circle cx={at[i][0]} cy={at[i][1]} r={p.depth === 0 ? 13 : p.depth === 1 ? 8 : 4.5 + Math.min(4, p.ties / 12)}
            fill={color(p.audience)} fillOpacity={p.depth === 2 ? 0.65 : 1} stroke={p.depth === 0 ? "var(--ink)" : "var(--bg)"} strokeWidth={p.depth === 0 ? 2.5 : 1} />
        </g>
      ))}
    </svg>
  );
}
