"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";

const PAGES: { href: string; label: string; step?: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/intake", label: "New study", step: "1" },
  { href: "/cohort", label: "Cohort preview", step: "2" },
  { href: "/run", label: "Simulation run", step: "3" },
  { href: "/atlas", label: "Scenario atlas", step: "4" },
  { href: "/report", label: "Report", step: "5" },
  { href: "/trace", label: "Trace explorer" },
  { href: "/calibration", label: "Calibration" },
];

export default function Shell({ crumbs, children }: { crumbs: React.ReactNode; children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
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
          <div className="nav-label">Studies</div>
          <Link className="nav-item" href="/report"><span className="step-no">•</span>Oral-care electric brush</Link>
          <Link className="nav-item" href="/atlas"><span className="step-no">•</span>Protein water launch</Link>
          <Link className="nav-item" href="/cohort"><span className="step-no">•</span>Refill pouch pricing</Link>
        </nav>
        <div className="side-foot">
          <div>Engine <span className="mono">v0.4.1</span> · seeds pinned</div>
          <div style={{ marginTop: 3 }}>Coreset <span className="mono">MatrAIx-1M</span></div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn quiet sm menu-btn" aria-label="Toggle navigation" onClick={() => setOpen((o) => !o)}>☰</button>
          <div className="crumbs">{crumbs}</div>
          <div className="topbar-right">
            <span className="chip plain mono" title="Monthly simulation budget">$<span>412</span> / $1,500</span>
            <span className="chip tier-pros" title="Data plan"><span className="dot" />Team plan</span>
            <div className="avatar">FA</div>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
      <style>{`@media (max-width: 900px) { .menu-btn { display: inline-flex !important; } } @media (min-width: 901px) { .menu-btn { display: none !important; } }`}</style>
    </div>
  );
}
