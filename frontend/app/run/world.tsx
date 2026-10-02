"use client";

import React from "react";
import { useApi } from "@/lib/api";
import { ICONS, Tip } from "@/components/ui";
import { CHANNEL_COLOR, CHANNEL_NAME, type Act, type Clock } from "./replay";

interface Network { nodes: [string, string | null, string | null, number][]; edges: [number, number, number][]; audiences: string[]; communities: string[] }

const PALETTE = ["#c9822b", "#2f8f9d", "#8a55c8", "#3f9b57", "#c4534a", "#5b6cc9", "#a0782c", "#2b7a6f"];
const IDLE = "#b9b4ab";
const FLASH_MS = 1400, TRAVEL_MS = 750, BUBBLE_MS = 2200, MAX_BUBBLES = 6;

type Mode = "decision" | "audience" | "community";
interface Flash { node: number; color: string; at: number }
interface Travel { from: number; to: number; color: string; at: number }
interface Bubble { node: number; label: string; text: string | null; color: string; at: number }
interface Link { a: number; b: number; channel: string; count: number; tick: number; wom: boolean }
type Links = "all" | "wom" | "none";

/* The world as a network: every persona a dot. While the clock plays, each closed tick's decisions happen
   again in the order the record wrote them — the persona flashes in its channel's colour with a bubble
   naming what it did, and when the item came from another persona the link between them lights and stays:
   the conversation network forming. */
export default function WorldGraph({ runId, acts, clock, live, provisional = null }: { runId: string; acts: Record<number, Act[]>; clock: Clock; live: boolean; provisional?: number | null }) {
  const { data, error } = useApi<Network>(`/api/runs/${encodeURIComponent(runId)}/graph/network`);
  const host = React.useRef<HTMLDivElement>(null);
  const [mode, setMode] = React.useState<Mode>("decision");
  const [show, setShow] = React.useState<Links>("all");
  const [hover, setHover] = React.useState<{ x: number; y: number; node: number } | null>(null);
  const [stats, setStats] = React.useState({ acted: 0, links: 0, now: 0, waiting: false });
  const sim = React.useRef({
    pos: 0, tick: -1, fired: 0, last: 0, nextAt: 0,
    color: [] as (string | null)[], did: [] as (string | null)[],
    flashes: [] as Flash[], travels: [] as Travel[], bubbles: [] as Bubble[],
    links: new Map<string, Link>(),
  });
  const props = React.useRef({ acts, clock, mode, live, show, provisional });
  props.current = { acts, clock, mode, live, show, provisional };

  // Layout once per network: ForceAtlas2 run to rest, so tied people sit together.
  const layout = React.useMemo(() => {
    if (!data) return null;
    const n = data.nodes.length;
    const x = new Float32Array(n), y = new Float32Array(n);
    data.nodes.forEach((_, i) => { const a = i * 2.399963, r = Math.sqrt(i + 1); x[i] = r * Math.cos(a); y[i] = r * Math.sin(a); });
    return { n, x, y, index: new Map(data.nodes.map(([id], i) => [id, i])) };
  }, [data]);
  const [settled, setSettled] = React.useState(false);
  React.useEffect(() => {
    if (!data || !layout) return;
    let live = true;
    (async () => {
      const [{ default: Graph }, { default: forceAtlas2 }] = await Promise.all([import("graphology"), import("graphology-layout-forceatlas2")]);
      const g = new Graph({ type: "undirected" });
      data.nodes.forEach((_, i) => g.addNode(String(i), { x: layout.x[i], y: layout.y[i], size: 1 }));
      data.edges.forEach(([u, v], k) => { if (!g.hasEdge(String(u), String(v))) g.addEdgeWithKey(String(k), String(u), String(v)); });
      // ponytail: synchronous layout; past a few thousand personas move it to the worker like the population page.
      forceAtlas2.assign(g, { iterations: Math.max(60, Math.min(400, Math.round(120000 / Math.max(1, layout.n)))), settings: { ...forceAtlas2.inferSettings(g), barnesHutOptimize: layout.n > 800 } });
      if (!live) return;
      g.forEachNode((key, a) => { layout.x[Number(key)] = a.x; layout.y[Number(key)] = a.y; });
      setSettled(true);
    })();
    return () => { live = false; };
  }, [data, layout]);

  // Rebuild what the network looked like when the clock is moved by hand: every act before this tick, at once.
  React.useEffect(() => {
    if (!layout) return;
    const s = sim.current;
    if (s.tick === clock.tick) return;
    s.tick = clock.tick; s.pos = 0; s.fired = 0;
    s.color = new Array(layout.n).fill(null); s.did = new Array(layout.n).fill(null);
    s.flashes = []; s.travels = []; s.bubbles = []; s.links = new Map();
    for (let t = 0; t < clock.tick; t++) for (const act of acts[t] ?? []) apply(act, layout.index, s, null);
  }, [clock.tick, layout, acts]);

  React.useEffect(() => {
    if (!layout || !host.current || !data) return;
    const canvas = document.createElement("canvas");
    Object.assign(canvas.style, { width: "100%", height: "100%", display: "block", cursor: "grab" });
    host.current.appendChild(canvas);
    const ctx = canvas.getContext("2d")!;
    let zoom = 1, panX = 0, panY = 0, w = 1, h = 1, frame = 0;
    const fit = () => {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (let i = 0; i < layout.n; i++) { minX = Math.min(minX, layout.x[i]); maxX = Math.max(maxX, layout.x[i]); minY = Math.min(minY, layout.y[i]); maxY = Math.max(maxY, layout.y[i]); }
      return { s: 0.88 * Math.min(w / Math.max(1e-6, maxX - minX), h / Math.max(1e-6, maxY - minY)), cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
    };
    let f = { s: 1, cx: 0, cy: 0 };
    const sx = (i: number) => (layout.x[i] - f.cx) * f.s * zoom + w / 2 + panX;
    const sy = (i: number) => (layout.y[i] - f.cy) * f.s * zoom + h / 2 + panY;
    const radius = (i: number) => Math.max(2.2, Math.min(9, 2 + Math.sqrt(data.nodes[i][3]) * 0.7)) * Math.sqrt(zoom);
    const groupColor = (i: number, m: Mode) => {
      const [, audience, community] = data.nodes[i];
      if (m === "audience") return audience == null ? IDLE : PALETTE[data.audiences.indexOf(audience) % PALETTE.length];
      if (m === "community") return community == null ? IDLE : PALETTE[data.communities.indexOf(community) % PALETTE.length];
      return sim.current.color[i] ?? IDLE;
    };

    const step = (now: number) => {
      const s = sim.current, { acts: all, clock: c, live: running } = props.current;
      const dt = s.last ? Math.min(100, now - s.last) : 0;
      s.last = now;
      // The clock moved and the network has not been rebuilt for it yet: hold until it is.
      if (s.tick !== c.tick) { draw(now); raf = requestAnimationFrame(step); return; }
      const tickActs = all[c.tick] ?? [];
      // The open tick (ADR 0050): decisions play as they land, one at a time, faster when a backlog builds,
      // and the clock stays here until the record closes the tick.
      if (props.current.provisional === c.tick) {
        const backlog = tickActs.length - s.fired;
        if (c.playing && backlog > 0 && now >= s.nextAt) {
          // Far behind (a page opened mid-tick), the backlog is applied quietly and only the latest play out.
          while (tickActs.length - s.fired > 40) { apply(tickActs[s.fired], layout.index, s, null); s.fired++; }
          apply(tickActs[s.fired], layout.index, s, now);
          s.fired++;
          s.nextAt = now + 140 / c.speed / (1 + backlog / 10);
        }
        s.flashes = s.flashes.filter((x) => now - x.at < FLASH_MS);
        s.travels = s.travels.filter((x) => now - x.at < TRAVEL_MS);
        s.bubbles = s.bubbles.filter((x) => now - x.at < BUBBLE_MS);
        draw(now);
        if (frame % 15 === 0) setStats({ acted: s.color.filter(Boolean).length, links: s.links.size, now: s.fired, waiting: backlog === 0 });
        frame++;
        raf = requestAnimationFrame(step);
        return;
      }
      const duration = Math.max(4000, Math.min(14000, tickActs.length * 90)) / c.speed;
      if (c.playing && all[c.tick]) s.pos += dt;
      // Fire every act whose moment has come: acts are spread evenly over the tick, in record order.
      while (s.fired < tickActs.length && s.pos >= (s.fired / Math.max(1, tickActs.length)) * duration) {
        apply(tickActs[s.fired], layout.index, s, now);
        s.fired++;
      }
      let waiting = false;
      if (c.playing && s.pos >= duration + 600) {
        if (all[c.tick + 1]) c.setTick(c.tick + 1);
        else if (running) waiting = true;
        else c.setPlaying(false);
      }
      s.flashes = s.flashes.filter((x) => now - x.at < FLASH_MS);
      s.travels = s.travels.filter((x) => now - x.at < TRAVEL_MS);
      s.bubbles = s.bubbles.filter((x) => now - x.at < BUBBLE_MS);
      draw(now);
      if (frame % 15 === 0) setStats({ acted: s.color.filter(Boolean).length, links: s.links.size, now: s.fired, waiting });
      frame++;
      raf = requestAnimationFrame(step);
    };

    const draw = (now: number) => {
      const dpr = window.devicePixelRatio || 1;
      w = host.current?.clientWidth || 1; h = host.current?.clientHeight || 1;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      f = fit();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const s = sim.current, m = props.current.mode;
      // The network's own ties: a faint layer behind everything that happens on it.
      ctx.lineWidth = 0.6;
      ctx.strokeStyle = layout.n > 3000 ? "rgba(120,112,100,0.08)" : "rgba(120,112,100,0.20)";
      ctx.beginPath();
      for (const [u, v] of data.edges) { ctx.moveTo(sx(u), sy(u)); ctx.lineTo(sx(v), sy(v)); }
      ctx.stroke();
      // Conversation links: who has reached whom so far, in the channel it last went by; busier is thicker.
      // Word of mouth is a person passing something on: drawn strong. Reacting to someone's post is a
      // weaker tie, and one prolific poster would otherwise fan out over everything: drawn light.
      const which = props.current.show;
      for (const link of which === "none" ? [] : s.links.values()) {
        if (which === "wom" && !link.wom) continue;
        const age = s.tick - link.tick;
        ctx.globalAlpha = (age <= 0 ? 0.85 : Math.max(0.25, 0.7 - age * 0.12)) * (link.wom ? 1 : 0.35);
        ctx.strokeStyle = CHANNEL_COLOR[link.channel] ?? "#777";
        ctx.lineWidth = (link.wom ? Math.min(4, 1.4 + link.count * 0.6) : 0.8) * Math.sqrt(zoom);
        ctx.beginPath(); ctx.moveTo(sx(link.a), sy(link.a)); ctx.lineTo(sx(link.b), sy(link.b)); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // Something travelling: a dot running from the persona it came from to the one it reached.
      for (const t of s.travels) {
        const p = Math.min(1, (now - t.at) / TRAVEL_MS);
        const x = sx(t.from) + (sx(t.to) - sx(t.from)) * p, y = sy(t.from) + (sy(t.to) - sy(t.from)) * p;
        ctx.strokeStyle = t.color; ctx.lineWidth = 2.5; ctx.globalAlpha = 0.9;
        ctx.beginPath(); ctx.moveTo(sx(t.from), sy(t.from)); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = t.color; ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI); ctx.fill();
        ctx.globalAlpha = 1;
      }
      for (let i = 0; i < layout.n; i++) {
        ctx.fillStyle = groupColor(i, m);
        ctx.beginPath(); ctx.arc(sx(i), sy(i), radius(i), 0, 2 * Math.PI); ctx.fill();
      }
      // A decision: a ring pulsing out from the persona that made it.
      for (const fl of s.flashes) {
        const p = (now - fl.at) / FLASH_MS, r = radius(fl.node);
        ctx.strokeStyle = fl.color; ctx.globalAlpha = 1 - p; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.arc(sx(fl.node), sy(fl.node), r + 3 + p * 16, 0, 2 * Math.PI); ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.fillStyle = fl.color; ctx.beginPath(); ctx.arc(sx(fl.node), sy(fl.node), r + 1.5, 0, 2 * Math.PI); ctx.fill();
      }
      const placed: [number, number, number, number][] = [];
      // A narrow screen holds fewer words over the network: the latest few decisions only.
      for (const b of s.bubbles.slice(w < 600 ? -2 : -MAX_BUBBLES)) bubble(b, now, placed);
      if (hoverRef.current != null) {
        const i = hoverRef.current;
        ctx.strokeStyle = "#111"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(sx(i), sy(i), radius(i) + 3, 0, 2 * Math.PI); ctx.stroke();
      }
    };

    // A speech bubble above the persona: what it did and where, and its first words.
    const bubble = (b: Bubble, now: number, placed: [number, number, number, number][]) => {
      const p = (now - b.at) / BUBBLE_MS;
      ctx.globalAlpha = p < 0.1 ? p * 10 : p > 0.75 ? (1 - p) * 4 : 1;
      const x = sx(b.node), y = sy(b.node) - radius(b.node) - 8;
      ctx.font = "600 11.5px system-ui, sans-serif";
      const text = b.text ? `“${b.text.length > 46 ? `${b.text.slice(0, 45)}…` : b.text}”` : "";
      ctx.font = "11px system-ui, sans-serif";
      const tw = Math.max(measure("600 11.5px system-ui, sans-serif", b.label), text ? measure("italic 11px system-ui, sans-serif", text) : 0);
      const bw = tw + 16, bh = text ? 36 : 22;
      const bx = Math.max(4, Math.min(w - bw - 4, x - bw / 2));
      let by = Math.max(4, y - bh - 6);
      // Stack above any bubble already drawn this frame rather than over it.
      for (let k = 0; k < 4 && placed.some(([px, py, pw, ph]) => bx < px + pw && bx + bw > px && by < py + ph && by + bh > py); k++) by = Math.max(4, by - bh - 4);
      placed.push([bx, by, bw, bh]);
      ctx.fillStyle = "#fffdf8"; ctx.strokeStyle = b.color; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, 7); ctx.fill(); ctx.stroke();
      // A thin line down to the persona, however far the bubble had to stack.
      ctx.beginPath(); ctx.moveTo(Math.max(bx + 6, Math.min(bx + bw - 6, x)), by + bh); ctx.lineTo(x, y + 4); ctx.strokeStyle = b.color; ctx.lineWidth = 1.2; ctx.stroke();
      ctx.fillStyle = b.color; ctx.font = "600 11.5px system-ui, sans-serif"; ctx.fillText(b.label, bx + 8, by + 15);
      if (text) { ctx.fillStyle = "#3d3a35"; ctx.font = "italic 11px system-ui, sans-serif"; ctx.fillText(text, bx + 8, by + 29); }
      ctx.globalAlpha = 1;
    };
    const measure = (font: string, text: string) => { ctx.font = font; return ctx.measureText(text).width; };

    const hoverRef = { current: null as number | null };
    const nearest = (mx: number, my: number, within: number) => {
      let best: number | null = null, bd = within * within;
      for (let i = 0; i < layout.n; i++) { const d = (sx(i) - mx) ** 2 + (sy(i) - my) ** 2; if (d < bd) { bd = d; best = i; } }
      return best;
    };
    let dragging = false, moved = false, lx = 0, ly = 0;
    const local = (e: MouseEvent) => { const b = canvas.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top] as const; };
    const down = (e: MouseEvent) => { dragging = true; moved = false; lx = e.clientX; ly = e.clientY; canvas.style.cursor = "grabbing"; };
    const move = (e: MouseEvent) => {
      if (dragging) { panX += e.clientX - lx; panY += e.clientY - ly; lx = e.clientX; ly = e.clientY; moved = true; return; }
      if (e.target !== canvas) return;
      const [mx, my] = local(e);
      const i = nearest(mx, my, 9);
      hoverRef.current = i;
      setHover(i == null ? null : { x: mx, y: my, node: i });
    };
    const up = (e: MouseEvent) => {
      canvas.style.cursor = "grab";
      if (dragging && !moved && e.target === canvas) {
        const [mx, my] = local(e);
        const i = nearest(mx, my, 10);
        if (i != null) window.open(`/trace?run=${encodeURIComponent(runId)}&persona=${encodeURIComponent(data.nodes[i][0])}`, "_blank");
      }
      dragging = false;
    };
    const leave = () => { hoverRef.current = null; setHover(null); };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const [mx0, my0] = local(e);
      const mx = mx0 - w / 2 - panX, my = my0 - h / 2 - panY, factor = Math.exp(-e.deltaY * 0.0015);
      zoom = Math.max(0.3, Math.min(12, zoom * factor)); panX -= mx * (factor - 1); panY -= my * (factor - 1);
    };
    canvas.addEventListener("mousedown", down);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    canvas.addEventListener("mouseleave", leave);
    canvas.addEventListener("wheel", wheel, { passive: false });
    let raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      canvas.remove();
    };
  }, [layout, data, runId]);

  if (error) return <div className="empty"><b>No network to draw.</b>{error}</div>;
  const s = sim.current;
  const hovered = hover != null && data ? data.nodes[hover.node] : null;
  const tickActs = acts[clock.tick] ?? [];
  const byChannel = tickActs.reduce<Record<string, number>>((m, a) => { m[a.channel] = (m[a.channel] ?? 0) + 1; return m; }, {});
  return (
    <div className="world">
      <div className="world-bar">
        <span className="row" style={{ gap: 6 }}>
          {ICONS.network}<b>{data ? `${data.nodes.length.toLocaleString()} personas` : "Reading the network…"}</b>
          {data && !settled && <span className="sub">arranging…</span>}
        </span>
        <span className="row sub" style={{ gap: 10, fontSize: 12 }}>
          <span>{stats.acted} have acted</span>
          <span>{stats.links} conversation links</span>
          <span>tick {clock.tick}: {stats.now}/{tickActs.length} decisions</span>
          {provisional === clock.tick
            ? <span className="chip warn"><span className="dot" />provisional · decisions as they land{stats.waiting ? " · waiting for the next" : ""}</span>
            : stats.waiting && <span className="chip plain">{ICONS.clock} waiting for tick {clock.tick + 1} to close</span>}
        </span>
        <label className="row" style={{ gap: 6, marginLeft: "auto", fontSize: 12 }}>
          colour by
          <select className="input" aria-label="Colour by" value={mode} onChange={(e) => setMode(e.target.value as Mode)} style={{ width: "auto", fontSize: 12, padding: "2px 6px" }}>
            <option value="decision">last decision</option>
            <option value="audience">audience</option>
            <option value="community" disabled={!data?.communities.length}>community{data && !data.communities.length ? " (none formed)" : ""}</option>
          </select>
          <select className="input" aria-label="Links shown" value={show} onChange={(e) => setShow(e.target.value as Links)} style={{ width: "auto", fontSize: 12, padding: "2px 6px" }}>
            <option value="all">all conversation links</option>
            <option value="wom">word of mouth only</option>
            <option value="none">no links</option>
          </select>
          <Tip>Last decision: each persona takes the colour of the channel it last acted on, and stays grey until it first acts; a survey answer flashes a purple ring but leaves the colour, since a wave only reads. Links: word of mouth strong, reactions to another persona's post light. Audience and community colour by who the persona is; communities are fixed when the population is drawn and do not change during a run.</Tip>
        </label>
      </div>
      <div ref={host} className="world-canvas" aria-label="The world network, replaying decisions" role="img">
        {hovered && hover && (
          <div className="world-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
            <b className="mono">{hovered[0]}</b>
            <div className="sub">{hovered[1] ?? "no audience"} · {hovered[3]} ties{hovered[2] ? ` · community ${hovered[2]}` : ""}</div>
            <div>{s.did[hover.node] ?? "has not acted yet"}</div>
            <div className="sub" style={{ fontSize: 11 }}>click to open their history</div>
          </div>
        )}
      </div>
      <div className="world-legend">
        <div className="legend-group">
          <span className="legend-title">Channel <Tip>A persona&apos;s dot takes the colour of the channel it last acted on. The counts are this tick&apos;s decisions.</Tip></span>
          {Object.entries(CHANNEL_NAME).map(([c, name]) => (
            <span key={c} className="legend-item" title={c === "survey_room" ? "A survey answer flashes a ring but leaves the dot's colour: a wave only reads." : undefined}>
              <span className="swatch" style={c === "survey_room" ? { background: "transparent", boxShadow: `inset 0 0 0 2px ${CHANNEL_COLOR[c]}` } : { background: CHANNEL_COLOR[c] }} />{c === "survey_room" ? "survey (ring only)" : name}{byChannel[c] ? <span className="count-pill">{byChannel[c]}</span> : null}</span>
          ))}
          <span className="legend-item"><span className="swatch" style={{ background: IDLE }} />not acted yet</span>
        </div>
        <div className="legend-group">
          <span className="legend-title">Reading it</span>
          <span className="legend-item" title="A persona just made a decision: a ring pulses out from it, with a bubble naming what it did.">
            <svg width="22" height="16" viewBox="0 0 22 16" aria-hidden><circle cx="11" cy="8" r="3.5" fill="#2f7fd8" /><circle cx="11" cy="8" r="6.5" fill="none" stroke="#2f7fd8" strokeWidth="1.5" opacity="0.5" /></svg>decision
          </span>
          <span className="legend-item" title="A persona just reacted to something that came from another persona: a message a friend passed on by word of mouth, or a post someone wrote on the feed or forum. The dot runs from the persona it came from to the one who reacted.">
            <svg width="30" height="16" viewBox="0 0 30 16" aria-hidden><circle cx="3" cy="8" r="2.5" fill="#8e8a82" /><line x1="3" y1="8" x2="20" y2="8" stroke="#2a9d5c" strokeWidth="2" /><circle cx="20" cy="8" r="3.5" fill="#2a9d5c" /><circle cx="27" cy="8" r="2.5" fill="#8e8a82" /></svg>came from another persona
          </span>
          <span className="legend-item" title="Someone passed the product on to this persona by word of mouth. Thicker the more often it happened.">
            <svg width="26" height="16" viewBox="0 0 26 16" aria-hidden><line x1="2" y1="8" x2="24" y2="8" stroke="#2a9d5c" strokeWidth="3.5" strokeLinecap="round" /></svg>word-of-mouth link
          </span>
          <span className="legend-item" title="This persona reacted to a post another persona wrote on the feed or forum: a weaker tie, drawn light.">
            <svg width="26" height="16" viewBox="0 0 26 16" aria-hidden><line x1="2" y1="8" x2="24" y2="8" stroke="#e0672b" strokeWidth="1.2" opacity="0.5" strokeLinecap="round" /></svg>reacted to a post
          </span>
        </div>
        <div className="legend-group legend-controls">
          {[["scroll", "zoom"], ["drag", "move"], ["hover", "who"], ["click", "history"]].map(([k, what]) => (
            <span key={k} className="legend-item"><span className="kbd">{k}</span>{what}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* One decision applied to the network: colour, what it did, the link it came by — animated when `now` is given. */
function apply(act: Act, index: Map<string, number>, s: { color: (string | null)[]; did: (string | null)[]; flashes: Flash[]; travels: Travel[]; bubbles: Bubble[]; links: Map<string, Link> }, now: number | null) {
  const i = index.get(act.persona);
  if (i == null) return;
  const color = CHANNEL_COLOR[act.channel] ?? "#777";
  // A survey answer is a decision too, but a wave only reads: it flashes without recolouring the persona.
  if (act.channel !== "survey_room") s.color[i] = color;
  s.did[i] = `t${act.tick} · ${act.action} on ${CHANNEL_NAME[act.channel] ?? act.channel}`;
  const j = act.from != null ? index.get(act.from) : undefined;
  if (j != null && j !== i) {
    const key = i < j ? `${i}|${j}` : `${j}|${i}`;
    const link = s.links.get(key);
    s.links.set(key, { a: j, b: i, channel: act.channel, count: (link?.count ?? 0) + 1, tick: act.tick, wom: (link?.wom ?? false) || act.via === "wom" });
    if (now != null) s.travels.push({ from: j, to: i, color, at: now });
  }
  if (now == null) return;
  s.flashes.push({ node: i, color, at: now });
  // One bubble per persona — its latest decision — so a busy persona's words never pile up.
  s.bubbles = s.bubbles.filter((b) => b.node !== i);
  if (s.bubbles.length >= MAX_BUBBLES) s.bubbles.shift();
  s.bubbles.push({ node: i, label: `${act.action} · ${CHANNEL_NAME[act.channel] ?? act.channel}`, text: act.text, color, at: now });
}
