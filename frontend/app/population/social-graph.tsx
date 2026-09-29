"use client";

import React from "react";
import { Callout, Chip } from "@/components/ui";
import { useApi } from "@/lib/api";
import { explainGate, gateMeter, type GateMeter } from "@/lib/gates";
import type { GateResult } from "@/lib/engine";
import type Graph from "graphology";

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

// Plain colours, not CSS variables: the whole network is drawn by WebGL, which cannot read them. The
// circle uses the same ones, so an audience is one colour in both views.
export const PALETTE = ["#b8822b", "#2a8797", "#3f8a55", "#9a66b3", "#b35d47", "#8e8a82", "#5b7fc4", "#c4a13a"];

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

      <WholeNetwork runId={runId} picked={data.circle.center} onPick={setCenter} />

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

interface Network { graph_hash: string; nodes: [string, string | null, string | null, number][]; edges: [number, number, number][]; audiences: string[]; communities: string[] }

/* The whole network: one dot per persona — every one of them, sized by how many ties it has and coloured by
   audience or community — laid out by ForceAtlas2 in a worker, so tied people pull together. */
function WholeNetwork({ runId, picked, onPick }: { runId: string; picked: string | null; onPick: (id: string) => void }) {
  const { data, error } = useApi<Network>(`/api/runs/${encodeURIComponent(runId)}/graph/network`);
  const box = React.useRef<HTMLDivElement>(null);
  const [by, setBy] = React.useState<"audience" | "community">("audience");
  const [phase, setPhase] = React.useState<"drawing" | "arranging" | "settled">("drawing");
  const [flat, setFlat] = React.useState(false); // drawn on a 2D canvas: this browser has no WebGL
  const graphRef = React.useRef<{ refresh: () => void; paint: (by: "audience" | "community", picked: string | null) => void } | null>(null);
  const groups = data ? (by === "audience" ? data.audiences : data.communities) : [];

  React.useEffect(() => {
    if (!data || !box.current) return;
    let renderer: { kill: () => void; refresh: () => void } | null = null;
    let layout: { start: () => void; stop: () => void; kill: () => void } | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let tick: ReturnType<typeof setInterval> | undefined;
    let live = true;
    (async () => {
      const [{ default: Graph }, { default: Sigma }, { default: FA2Layout }, { default: forceAtlas2 }] = await Promise.all([
        import("graphology"), import("sigma"), import("graphology-layout-forceatlas2/worker"), import("graphology-layout-forceatlas2"),
      ]);
      if (!live || !box.current) return;
      const graph = new Graph({ type: "undirected", multi: false });
      const n = data.nodes.length;
      data.nodes.forEach(([id, audience, community, ties], i) => {
        // A sunflower spiral to start from: deterministic, so the same network always settles the same way.
        const angle = i * 2.399963, radius = Math.sqrt(i + 1);
        graph.addNode(String(i), {
          x: radius * Math.cos(angle), y: radius * Math.sin(angle),
          size: Math.max(1.2, Math.min(10, (n > 5000 ? 0.8 : 1.6) + Math.sqrt(ties) * 0.55)),
          label: `${id} · ${audience ?? "no audience"} · ${ties} ties`, persona: id, audience, community,
          color: "#8e8a82",
        });
      });
      // Solid colours only: sigma's WebGL drew translucent (rgba) ties as nothing at all. At least a pixel wide,
      // and lighter as the network grows, so tens of thousands of ties stay a soft layer behind the dots.
      data.edges.forEach(([u, v, w], k) => graph.addEdgeWithKey(String(k), String(u), String(v), { size: 1 + w, color: n > 5000 ? "#e4e0d9" : n > 1000 ? "#dad5cd" : "#cfc9bf" }));
      const paint = (group: "audience" | "community", chosen: string | null) => {
        const names = group === "audience" ? data.audiences : data.communities;
        graph.forEachNode((key, attrs) => {
          const g = group === "audience" ? attrs.audience : attrs.community;
          graph.setNodeAttribute(key, "color", attrs.persona === chosen ? "#111111" : g === null ? "#b9b4ab" : PALETTE[names.indexOf(g) % PALETTE.length]);
          graph.setNodeAttribute(key, "zIndex", attrs.persona === chosen ? 1 : 0);
        });
      };
      paint("audience", picked);
      // WebGL when the browser has it; many Linux browsers turn it off for their GPU, and then the same network
      // is drawn on a plain 2D canvas — slower to redraw, but every persona and every tie is still there.
      let sigma: InstanceType<typeof Sigma> | null = null;
      if (hasWebGL()) {
        try {
          sigma = new Sigma(graph, box.current, { labelRenderedSizeThreshold: n > 2000 ? 14 : 9, zIndex: true, defaultEdgeType: "line", minEdgeThickness: 1 });
          sigma.on("clickNode", ({ node }) => onPick(graph.getNodeAttribute(node, "persona")));
        } catch {
          box.current.innerHTML = "";
          sigma = null;
        }
      }
      if (sigma) {
        const drawn = sigma;
        renderer = drawn;
        graphRef.current = { refresh: () => drawn.refresh(), paint: (g, chosen) => { paint(g, chosen); drawn.refresh(); } };
      } else {
        const drawn = flatRenderer(graph, box.current, onPick);
        renderer = drawn;
        setFlat(true);
        tick = setInterval(drawn.refresh, 250); // the layout moves nodes; a 2D canvas redraws on a clock
        graphRef.current = { refresh: drawn.refresh, paint: (g, chosen) => { paint(g, chosen); drawn.refresh(); } };
      }
      const settings = forceAtlas2.inferSettings(graph);
      layout = new FA2Layout(graph, { settings: { ...settings, barnesHutOptimize: n > 800, slowDown: 2 } });
      layout.start();
      setPhase("arranging");
      timer = setTimeout(() => { layout?.stop(); clearInterval(tick); renderer?.refresh(); setPhase("settled"); }, n > 5000 ? 20000 : n > 1000 ? 9000 : 4000);
    })();
    return () => { live = false; clearTimeout(timer); clearInterval(tick); layout?.kill(); renderer?.kill(); graphRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  React.useEffect(() => { graphRef.current?.paint(by, picked); }, [by, picked]);

  if (error) return null; // the panel above already says there is no saved network
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>The whole network</b>
        <span className="sub" style={{ fontSize: 12 }}>
          {data ? <>every persona is one dot — {data.nodes.length.toLocaleString()} personas, {data.edges.length.toLocaleString()} ties · {phase === "arranging" ? "arranging: tied people pull together…" : phase === "settled" ? "settled" : "drawing…"}{flat && " · drawn without WebGL, which this browser has turned off"}</> : "reading the network…"}
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center", fontSize: 12 }}>
          colour by
          <select className="input" style={{ width: "auto", fontSize: 12, padding: "2px 6px" }} value={by} onChange={(e) => setBy(e.target.value as "audience" | "community")}>
            <option value="audience">audience</option>
            <option value="community" disabled={!data?.communities.length}>community{data && !data.communities.length ? " (none formed)" : ""}</option>
          </select>
        </span>
      </div>
      <div ref={box} style={{ height: 560, marginTop: 8, border: "1px solid var(--line)", borderRadius: "var(--r-md)", background: "var(--bg)" }} />
      <div className="sub" style={{ fontSize: 11.5, display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        {groups.map((g) => <span key={g}><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: PALETTE[groups.indexOf(g) % PALETTE.length], marginRight: 4 }} />{g}</span>)}
        <span>· bigger dot: more ties · scroll to zoom, drag to move · hover for who it is · click a dot to open that persona&apos;s circle below (shown in black)</span>
      </div>
    </div>
  );
}

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/* The network on a 2D canvas, for browsers without WebGL: ties as one batched path, dots grouped by colour.
   Scroll zooms, drag pans, hover names a persona and a click opens their circle. */
function flatRenderer(graph: Graph, host: HTMLDivElement, onPick: (id: string) => void) {
  const canvas = document.createElement("canvas");
  Object.assign(canvas.style, { width: "100%", height: "100%", display: "block", cursor: "grab" });
  host.appendChild(canvas);
  const ctx = canvas.getContext("2d")!;
  let zoom = 1, panX = 0, panY = 0, fit = { s: 1, cx: 0, cy: 0 }, w = 1, h = 1;
  const screen = (x: number, y: number): [number, number] => [(x - fit.cx) * fit.s * zoom + w / 2 + panX, (y - fit.cy) * fit.s * zoom + h / 2 + panY];

  const draw = () => {
    const dpr = window.devicePixelRatio || 1;
    w = host.clientWidth || 1; h = host.clientHeight || 1;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    graph.forEachNode((_, a) => { minX = Math.min(minX, a.x); maxX = Math.max(maxX, a.x); minY = Math.min(minY, a.y); maxY = Math.max(maxY, a.y); });
    fit = { s: 0.92 * Math.min(w / Math.max(1e-6, maxX - minX), h / Math.max(1e-6, maxY - minY)), cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
    ctx.lineWidth = 0.5;
    ctx.strokeStyle = graph.order > 5000 ? "rgba(95,90,80,0.10)" : "rgba(95,90,80,0.28)";
    ctx.beginPath();
    graph.forEachEdge((_e, _a, _s, _t, sa, ta) => {
      const [x1, y1] = screen(sa.x, sa.y), [x2, y2] = screen(ta.x, ta.y);
      ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
    });
    ctx.stroke();
    const byColour = new Map<string, [number, number, number][]>();
    let chosen = null as [number, number, number] | null;
    graph.forEachNode((_, a) => {
      const [x, y] = screen(a.x, a.y);
      const r = Math.max(1, (a.size as number) * 0.55 * Math.sqrt(zoom));
      if (a.color === "#111111") chosen = [x, y, r + 2];
      else byColour.set(a.color, [...(byColour.get(a.color) ?? []), [x, y, r]]);
    });
    for (const [colour, dots] of byColour) {
      ctx.fillStyle = colour;
      ctx.beginPath();
      for (const [x, y, r] of dots) { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 2 * Math.PI); }
      ctx.fill();
    }
    if (chosen) {
      const [x, y, r] = chosen;
      ctx.fillStyle = "#111111"; ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill();
    }
  };

  const nearest = (event: MouseEvent, within: number): string | null => {
    const box = canvas.getBoundingClientRect();
    const mx = event.clientX - box.left, my = event.clientY - box.top;
    let best: string | null = null, bestDistance = within * within;
    graph.forEachNode((key, a) => {
      const [x, y] = screen(a.x, a.y);
      const d = (x - mx) ** 2 + (y - my) ** 2;
      if (d < bestDistance) { bestDistance = d; best = key; }
    });
    return best;
  };
  let dragging = false, moved = false, lastX = 0, lastY = 0;
  const down = (e: MouseEvent) => { dragging = true; moved = false; lastX = e.clientX; lastY = e.clientY; canvas.style.cursor = "grabbing"; };
  const move = (e: MouseEvent) => {
    if (dragging) {
      panX += e.clientX - lastX; panY += e.clientY - lastY; lastX = e.clientX; lastY = e.clientY; moved = true; draw();
      return;
    }
    const key = nearest(e, 7);
    canvas.title = key ? String(graph.getNodeAttribute(key, "label")) : "";
  };
  const up = (e: MouseEvent) => {
    canvas.style.cursor = "grab";
    if (dragging && !moved) { const key = nearest(e, 9); if (key) onPick(String(graph.getNodeAttribute(key, "persona"))); }
    dragging = false;
  };
  const wheel = (e: WheelEvent) => {
    e.preventDefault();
    const box = canvas.getBoundingClientRect();
    const mx = e.clientX - box.left - w / 2 - panX, my = e.clientY - box.top - h / 2 - panY;
    const factor = Math.exp(-e.deltaY * 0.0015);
    zoom *= factor; panX -= mx * (factor - 1); panY -= my * (factor - 1);
    draw();
  };
  canvas.addEventListener("mousedown", down);
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
  canvas.addEventListener("wheel", wheel, { passive: false });
  draw();
  return {
    refresh: draw,
    kill: () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      canvas.remove();
    },
  };
}

