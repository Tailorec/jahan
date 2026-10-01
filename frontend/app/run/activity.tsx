"use client";

import React from "react";
import { ICONS, Tip } from "@/components/ui";
import { CHANNEL_COLOR, type Act, type Clock, type Post } from "./replay";

const VERB: Record<string, string> = {
  like: "liked", repost: "reposted", quote: "quoted", comment: "commented on", reply: "replied to", post: "posted",
  upvote: "upvoted", downvote: "downvoted", follow: "followed the author of", ask_peer: "asked a peer about",
  buy: "decided to buy after", reject: "rejected", complain: "complained about", ignore: "scrolled past", answer: "answered",
};
const INTRO: Record<string, { title: string; icon: keyof typeof ICONS; tip: string }> = {
  social_feed: { title: "X-like feed", icon: "feed", tip: "Every turn a persona took on the X-like feed: posts from ties and follows first, then the rest ranked by TwHIN-BERT similarity and age. Likes, reposts, quotes, comments and follows, in their own words." },
  forum: { title: "Reddit-like forum", icon: "forum", tip: "Every turn a persona took on the Reddit-like forum: threads ranked hot, then upvotes, downvotes, replies and new posts, in their own words." },
  wom: { title: "Word of mouth", icon: "wom", tip: "Every message passed person to person along the social network's ties: who heard it from whom, and what they did with it." },
};

export const short = (id: string | null) => (id ? `…${id.split(":").pop()}` : "the study");

/* One channel's turns as a stream, newest tick first, up to the tick the replay clock shows. */
export default function ActivityStream({ channel, acts, posts, clock, runId }: { channel: string; acts: Record<number, Act[]>; posts: Record<string, Post>; clock: Clock; runId: string }) {
  const [shown, setShown] = React.useState(120);
  const [who, setWho] = React.useState("");
  const intro = INTRO[channel];
  const ticks = Object.keys(acts).map(Number).filter((t) => t <= clock.tick).sort((a, b) => b - a);
  const rows = ticks.flatMap((t) => (acts[t] ?? []).filter((a) => a.channel === channel && (!who || a.persona.includes(who) || (a.from ?? "").includes(who))).slice().reverse());
  const color = CHANNEL_COLOR[channel];
  const actions = rows.reduce<Record<string, number>>((m, a) => { m[a.action] = (m[a.action] ?? 0) + 1; return m; }, {});
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="sec-head"><span className="sec-icon" style={{ color }}>{ICONS[intro.icon]}</span><h2>{intro.title}</h2><Tip>{intro.tip}</Tip></div>
        <div className="tools"><input className="input mono" aria-label="Find a persona" placeholder="find a persona…" value={who} onChange={(e) => setWho(e.target.value)} style={{ maxWidth: 200 }} /></div>
      </div>
      <div className="panel-body" style={{ display: "grid", gap: 10 }}>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <span className="chip plain">{rows.length.toLocaleString()} turns up to tick {clock.tick}</span>
          {Object.entries(actions).sort((a, b) => b[1] - a[1]).map(([a, n]) => <span key={a} className="chip plain">{a} · {n}</span>)}
        </div>
        {rows.length === 0 && <div className="empty"><b>Nothing here yet.</b>{Object.keys(acts).length ? "No persona has acted on this channel up to this tick." : "Loading the record…"}</div>}
        <ol className="stream">
          {rows.slice(0, shown).map((a) => {
            const subject = a.subject ? posts[a.subject] : null;
            const parent = subject?.in_reply_to ? posts[subject.in_reply_to] : null;
            return (
              <li key={a.id} className="stream-item" style={{ borderLeftColor: color }}>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <a className="mono strong" href={`/trace?run=${encodeURIComponent(runId)}&persona=${encodeURIComponent(a.persona)}`} title={a.persona}>{short(a.persona)}</a>
                  <span className="sub">{VERB[a.action] ?? a.action}</span>
                  {channel === "wom"
                    ? <span className="sub">a message from <b className="mono" title={a.from ?? ""}>{short(a.from)}</b></span>
                    : subject && <span className="sub">{subject.author ? <>a {subject.kind.replace("_", " ")} by <b className="mono" title={subject.author}>{short(subject.author)}</b></> : <>the study&apos;s {subject.kind.replace("_", " ")}</>}</span>}
                  <span className="mono sub" style={{ marginLeft: "auto", fontSize: 11 }}>t{a.tick}</span>
                </div>
                {a.text && <p className="stream-text">{a.text}</p>}
                {subject && (
                  <blockquote className="stream-quote">
                    {parent && <span className="sub">in reply to “{clip(parent.text, 80)}” · </span>}
                    “{clip(subject.text, 220)}”
                  </blockquote>
                )}
              </li>
            );
          })}
        </ol>
        {rows.length > shown && <button type="button" className="btn btn-secondary" onClick={() => setShown((n) => n + 200)}>Show {Math.min(200, rows.length - shown)} more</button>}
      </div>
    </div>
  );
}

const clip = (t: string, n: number) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);
