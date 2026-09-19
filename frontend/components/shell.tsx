"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";
import { useApi } from "@/lib/api";

/* What the shell says about the engine and its studies is what the engine says: the recent runs, the
   version, whether an endpoint is configured, and the spend the workspace summary derived. Nothing
   here is a placeholder — a single-operator local application has no plan, no quota and no account,
   and shows none. */
interface Overview {
  workspace: { total_spend: number; total_studies: number } | null;
  runs: { run_id: string; status: string; fake?: boolean; has_report?: boolean }[];
}
interface Status { engine_version: string; endpoint_configured: boolean }

const PAGES: { href: string; label: string; step?: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/ontology", label: "Ontology builder", step: "0" },
  { href: "/intake", label: "New study", step: "1" },
  { href: "/population", label: "Population", step: "2" },
  { href: "/run", label: "Simulation run", step: "3" },
  { href: "/atlas", label: "Scenario atlas", step: "4" },
  { href: "/report", label: "Report", step: "5" },
  { href: "/trace", label: "Trace explorer" },
  { href: "/calibration", label: "Calibration" },
];

export default function Shell({ crumbs, children }: { crumbs: React.ReactNode; children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const { data: overview } = useApi<Overview>("/api/overview");
  const { data: status } = useApi<Status>("/api/status");
  // Runs come oldest first; the shell offers the newest few, and studies over gates that never ran are not studies.
  const recent = (overview?.runs ?? []).filter((r) => r.status !== "partial" || r.has_report).slice(-5).reverse();
  return (
    <div className="shell">
      <aside className={`sidebar${open ? " open" : ""}`} id="sidebar">
        <div className="brand">
          <div className="brand-mark">CS</div>
          <div className="brand-name">ConsumerSim<small>synthetic market engine</small></div>
        </div>
        <nav className="nav-group">
          <div className="nav-label">Workspace</div>
          {PAGES.map((p) => {
            const active = p.href === "/" ? pathname === "/" : pathname === p.href;
            return (
              <Link key={p.href} className={`nav-item${active ? " active" : ""}`} href={p.href} onClick={() => setOpen(false)}>
                {p.step ? <span className="step-no">{p.step}</span> : null}
                {p.label}
                {p.href === "/run" && <span className="nav-dot" style={{ background: "var(--primary)" }} />}
              </Link>
            );
          })}
        </nav>
        <nav className="nav-group">
          <div className="nav-label">Recent studies</div>
          {recent.map((r) => (
            <Link key={r.run_id} className="nav-item" href={`${r.has_report ? "/report" : "/run"}?run=${r.run_id}`} onClick={() => setOpen(false)}>
              <span className="step-no">•</span><span className="mono" style={{ fontSize: 11.5 }}>{r.run_id.slice(0, 16)}…</span>{r.fake ? <span className="sub" style={{ marginLeft: 6, fontSize: 11 }}>fake</span> : null}
            </Link>
          ))}
          {overview && !recent.length && <div className="sub" style={{ padding: "4px 12px", fontSize: 12 }}>No study has run yet.</div>}
        </nav>
        <div className="side-foot">
          <div>Engine <span className="mono">{status?.engine_version ?? "—"}</span></div>
          <div style={{ marginTop: 3 }}>{status ? (status.endpoint_configured ? "endpoint configured" : "no endpoint — fake studies only") : "—"}</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn quiet sm menu-btn" aria-label="Toggle navigation" onClick={() => setOpen((o) => !o)}>☰</button>
          <div className="crumbs">{crumbs}</div>
          <div className="topbar-right">
            {overview?.workspace && (
              <span className="chip plain mono" title="Recorded spend across every study in this workspace">
                ${overview.workspace.total_spend.toFixed(2)} spent · {overview.workspace.total_studies} {overview.workspace.total_studies === 1 ? "study" : "studies"}
              </span>
            )}
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
      <style>{`@media (max-width: 900px) { .menu-btn { display: inline-flex !important; } } @media (min-width: 901px) { .menu-btn { display: none !important; } }`}</style>
    </div>
  );
}
