"use client";

import React from "react";
import { useApi } from "@/lib/api";
import { ICONS, Tip } from "@/components/ui";
import type { RunSummary } from "@/lib/engine";
import { runKind, runLabel, runName, runWhen } from "@/lib/runs";

const STATUS: Record<string, { word: string; tone: string }> = {
  completed: { word: "done", tone: "ok" },
  running: { word: "running", tone: "wait" },
  partial: { word: "stopped", tone: "no" },
  failed: { word: "failed", tone: "no" },
};

/* Which run this page shows, said plainly at the top of every run page — its name, what it was,
   how many personas, when — with every other run one choice away. */
export default function RunBar({ runId }: { runId: string | null }) {
  const { data: runs } = useApi<RunSummary[]>("/api/runs");
  const [named, setNamed] = React.useState(true);
  React.useEffect(() => { setNamed(new URLSearchParams(window.location.search).has("run")); }, [runId]);
  if (!runId) return null;
  const all = [...(runs ?? [])].reverse();
  const run = all.find((r) => r.run_id === runId);
  const drawOnly = !!run && !run.scenarios?.length && !run.has_report;
  const status = drawOnly ? { word: "drawn", tone: "ok" } : STATUS[run?.status ?? ""] ?? { word: run?.status ?? "…", tone: "wait" };
  const go = (id: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("run", id);
    window.location.assign(url.toString());
  };
  return (
    <div className="runbar">
      <span className="sec-icon">{ICONS.layers}</span>
      <div style={{ minWidth: 0 }}>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <b className="runbar-name">{run ? runName(run) : "…"}</b>
          <span className={`status-dot ${status.tone}`}>{status.word}{run?.live ? " · live" : ""}</span>
          {!named && <span className="chip plain" title="No run was named in the address, so this page shows the latest study with a report.">latest</span>}
        </div>
        <div className="row sub" style={{ gap: 12, fontSize: 12, flexWrap: "wrap", marginTop: 2 }}>
          {run && <span className="row" style={{ gap: 4 }}>{ICONS.radio}{runKind(run)}</span>}
          {run?.personas ? <span className="row" style={{ gap: 4 }}>{ICONS.users}{run.personas.toLocaleString()} personas</span> : null}
          {run && runWhen(run) && <span className="row" style={{ gap: 4 }}>{ICONS.clock}{runWhen(run)}</span>}
          {run && run.recorded_cost > 0 && <span className="row" style={{ gap: 4 }}>{ICONS.dollar}{run.recorded_cost.toFixed(3)}</span>}
          <span className="mono" title={runId}>{runId}</span>
        </div>
      </div>
      <label className="runbar-switch">
        <span className="sr-only">Switch run</span>
        <select className="input" aria-label="Switch run" value={runId} onChange={(e) => go(e.target.value)}>
          {!run && <option value={runId}>{runId}</option>}
          {all.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
        </select>
      </label>
      <Tip>Every run page shows one run. Its name is the product in its brief; a population draw that never ran a study is named by its category. Pick another run here and this page shows it instead.</Tip>
    </div>
  );
}
