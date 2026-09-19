"use client";

import React from "react";

export async function api<T>(p: string, init?: RequestInit): Promise<T> {
  const res = await fetch(p, init);
  if (!res.ok) throw new Error(`${p}: ${res.status}`);
  return res.json() as Promise<T>;
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
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [path]);
  return { data, error };
}

export function useRunId(fallback?: string): string | null {
  const [id, setId] = React.useState<string | null>(fallback ?? null);
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("run");
    if (q) setId(q);
    else if (!fallback) {
      api<{ runs: { run_id: string }[] }>("/api/runs")
        .then((d) => {
          const full = d.runs.find((r) => r.run_id === "run-5t329fy3ct04k2tht5714ahms8");
          setId(full ? full.run_id : (d.runs[0]?.run_id ?? null));
        })
        .catch(() => setId(null));
    }
  }, [fallback]);
  return id;
}
