"use client";

import React from "react";
import type { TraceEvent } from "@/lib/engine";

/* One persona's decision, as the record wrote it: who, on which channel, what they did, in their words,
   and — when it travelled to them from another persona — who it came from. */
export interface Act {
  id: string;
  tick: number;
  seq: number;
  persona: string;
  channel: string;
  action: string;
  text: string | null;
  subject: string | null;
  /* The persona the item came from: the word-of-mouth sender, or the author of the post reacted to. */
  from: string | null;
  via: "wom" | "post" | null;
}

export interface Post { id: string; author: string | null; kind: string; text: string; in_reply_to: string | null; tick: number }

export const CHANNEL_COLOR: Record<string, string> = {
  social_feed: "#2f7fd8", forum: "#e0672b", wom: "#2a9d5c", survey_room: "#8a55c8",
};
export const CHANNEL_NAME: Record<string, string> = {
  social_feed: "X-like feed", forum: "Reddit-like forum", wom: "word of mouth", survey_room: "survey",
};

type Turn = {
  impression: { persona_id: string; channel: string; tick: number };
  view: { contexts: Record<string, { via_persona_id?: string | null }> };
  reaction: { action: string; verbatim?: string | null; subject_stimulus_id?: string | null };
};

/* Every closed tick of one world, loaded once each and in order, so a finished run replays and a running
   one follows: a tick appears here when the engine closed it, never before. */
export function useTicks(runId: string | null, world: string | null, lastClosed: number | null) {
  const [acts, setActs] = React.useState<Record<number, Act[]>>({});
  const [posts, setPosts] = React.useState<Record<string, Post>>({});
  const [failed, setFailed] = React.useState<string | null>(null);
  const loading = React.useRef<Set<number>>(new Set());
  const known = React.useRef<Record<string, Post>>({});

  React.useEffect(() => { setActs({}); setPosts({}); setFailed(null); loading.current = new Set(); known.current = {}; }, [runId, world]);

  React.useEffect(() => {
    if (!runId || !world || lastClosed == null) return;
    let live = true;
    (async () => {
      for (let tick = 0; tick <= lastClosed && live; tick++) {
        if (loading.current.has(tick)) continue;
        loading.current.add(tick);
        try {
          const qs = `world_id=${encodeURIComponent(world)}&kind=turn&kind=stimulus_published&tick_from=${tick}&tick_to=${tick}&limit=100000`;
          const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/events?${qs}`);
          if (!res.ok) throw new Error(`the record answered ${res.status}`);
          const events: TraceEvent[] = (await res.json()).events ?? [];
          if (!live) return;
          const published: Record<string, Post> = {};
          for (const ev of events) {
            if (ev.payload.kind !== "stimulus_published") continue;
            const st = ev.payload.stimulus as { stimulus_id: string; author?: string | null; kind: string; text: string; in_reply_to?: string | null; tick: number };
            published[st.stimulus_id] = { id: st.stimulus_id, author: st.author ?? null, kind: st.kind, text: st.text, in_reply_to: st.in_reply_to ?? null, tick: st.tick };
          }
          // A post published this tick is reacted to only later, so earlier ticks' posts are all that is needed.
          known.current = { ...known.current, ...published };
          const tickActs = events.filter((ev) => ev.payload.kind === "turn" && ev.persona_id).map((ev) => toAct(ev, known.current));
          setPosts(known.current);
          setActs((a) => ({ ...a, [tick]: tickActs }));
        } catch (e) {
          loading.current.delete(tick);
          setFailed(e instanceof Error ? e.message : String(e));
          return;
        }
      }
    })();
    return () => { live = false; };
  }, [runId, world, lastClosed]);

  return { acts, posts, failed };
}

function toAct(ev: TraceEvent, posts: Record<string, Post>): Act {
  const turn = ev.payload.turn as Turn;
  const subject = turn.reaction.subject_stimulus_id ?? null;
  const viaWom = subject ? turn.view.contexts[subject]?.via_persona_id ?? null : null;
  const author = subject ? posts[subject]?.author ?? null : null;
  const from = viaWom ?? (author && author !== ev.persona_id ? author : null);
  return {
    id: ev.event_id, tick: ev.tick, seq: ev.seq, persona: ev.persona_id!,
    channel: turn.impression.channel, action: turn.reaction.action, text: turn.reaction.verbatim ?? null,
    subject, from, via: viaWom ? "wom" : from ? "post" : null,
  };
}

export interface Heard { world_id: string; tick: number; persona_id: string; channel: string; action: string; verbatim: string | null; subject_stimulus_id: string | null; via_persona_id: string | null }

/* Decisions heard in an open tick, as each persona's reply lands and before the tick is recorded (ADR 0050):
   polled while the study runs. Without a world yet — a study names its worlds only once one closes a tick —
   it follows whichever world the decisions come from. */
export function useHeard(runId: string | null, world: string | null, watching: boolean) {
  const [decisions, setDecisions] = React.useState<Heard[]>([]);
  React.useEffect(() => {
    setDecisions([]);
    if (!runId || !watching) return;
    let live = true;
    const poll = async () => {
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/live/decisions${world ? `?world_id=${encodeURIComponent(world)}` : ""}`);
        if (res.ok && live) setDecisions((await res.json()).decisions ?? []);
      } catch { /* the next poll tries again */ }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => { live = false; clearInterval(timer); };
  }, [runId, world, watching]);
  return { decisions, world: world ?? decisions[0]?.world_id ?? null };
}

/* The open tick — the one after the last closed — as replay acts. Provisional: replaced by the record. */
export function provisionalActs(decisions: Heard[], world: string | null, lastClosed: number | null, posts: Record<string, Post>) {
  const open = lastClosed == null ? 0 : lastClosed + 1;
  const acts: Act[] = decisions.filter((d) => d.world_id === world && d.tick === open).map((d, i) => {
    const author = d.subject_stimulus_id ? posts[d.subject_stimulus_id]?.author ?? null : null;
    const from = d.via_persona_id ?? (author && author !== d.persona_id ? author : null);
    return {
      id: `live-${open}-${i}`, tick: d.tick, seq: i, persona: d.persona_id, channel: d.channel, action: d.action,
      text: d.verbatim, subject: d.subject_stimulus_id, from, via: d.via_persona_id ? "wom" : from ? "post" : null,
    };
  });
  return { tick: open, acts };
}

/* The replay clock every tab shares: which tick is showing, whether it plays, and how fast. A running
   study's clock waits at the newest closed tick and moves on when the engine closes the next. */
export function useClock(lastClosed: number | null) {
  const [tick, setTick] = React.useState(0);
  const [playing, setPlaying] = React.useState(true);
  const [speed, setSpeed] = React.useState(1);
  return { tick, setTick, playing, setPlaying, speed, setSpeed, lastClosed };
}
export type Clock = ReturnType<typeof useClock>;
