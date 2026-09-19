"use client";

import React from "react";
import { refusalText } from "./refusal";

/* The interface's own API routes are proxies to the engine, and a refusal keeps the
   reason the engine gave: a 422 arrives with the sentence that says what to fix. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(p: string, init?: RequestInit): Promise<T> {
  const res = await fetch(p, init);
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* a refusal without a body */ }
    throw new ApiError(res.status, refusalText(body, `${p}: ${res.status}`));
  }
  return res.json() as Promise<T>;
}

/* The words to show for anything that went wrong: the engine's own, when it gave any. */
export function whyNot(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function useApi<T>(path: string | null) {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!path) return;
    let live = true;
    setData(null);
    setError(null);
    api<T>(path)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(whyNot(e)); });
    return () => { live = false; };
  }, [path]);
  return { data, error };
}

/* Which run a page is about: the one the address names, else the most recent study that
   finished with a report — the thing a reader most often came to see — else the newest run. */
export function useRunId(fallback?: string): string | null {
  const [id, setId] = React.useState<string | null>(fallback ?? null);
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("run");
    if (q) setId(q);
    else if (!fallback) {
      api<{ run_id: string; has_report?: boolean }[]>("/api/runs")
        .then((runs) => {
          const reported = [...runs].reverse().find((r) => r.has_report);
          setId(reported ? reported.run_id : (runs[runs.length - 1]?.run_id ?? null));
        })
        .catch(() => setId(null));
    }
  }, [fallback]);
  return id;
}
