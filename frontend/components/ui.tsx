import React from "react";

/* ---------- icons ---------- */
export const ICONS = {
  check: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
  ),
  alert: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>
  ),
  info: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
  ),
  arrow: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></svg>
  ),
  ext: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
  ),
};

/* ---------- primitives ---------- */
export function Chip({ className = "", children, title }: { className?: string; children: React.ReactNode; title?: string }) {
  return (
    <span className={`chip ${className}`} title={title}>
      <span className="dot" />
      {children}
    </span>
  );
}

export function Panel({ title, hint, tools, children, bodyClassName }: {
  title: string; hint?: string; tools?: React.ReactNode;
  children: React.ReactNode; bodyClassName?: string;
}) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {hint && <span className="hint">{hint}</span>}
        {tools && <div className="tools">{tools}</div>}
      </div>
      <div className={`panel-body ${bodyClassName ?? ""}`}>{children}</div>
    </div>
  );
}

export function PageHead({ title, sub, actions }: { title: string; sub: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        <div className="sub">{sub}</div>
      </div>
      <div className="head-actions">{actions}</div>
    </div>
  );
}

export function PmfBar({ p, meta, maxWidth = "180px" }: { p: number[]; meta?: string; maxWidth?: string }) {
  const pct = (v: number) => `${(v * 100).toFixed(0)}%`;
  return (
    <div className="pmf">
      <div className="pmf-bar" style={{ maxWidth }}>
        {p.map((v, i) => (
          <span key={i} className={`seg likert-${i + 1}`} style={{ width: `${(v * 100).toFixed(1)}%` }} title={`Likert ${i + 1}: ${pct(v)}`} />
        ))}
      </div>
      {meta != null && meta !== "" && <span className="pmf-meta">{meta}</span>}
    </div>
  );
}

export function PmfLegend() {
  return (
    <div className="pmf-legend">
      <span><i className="likert-1" />1 def. not</span>
      <span><i className="likert-2" />2 prob. not</span>
      <span><i className="likert-3" />3 maybe</span>
      <span><i className="likert-4" />4 prob. yes</span>
      <span><i className="likert-5" />5 def. yes</span>
    </div>
  );
}

export function Callout({ icon = "info", children, style }: {
  icon?: keyof typeof ICONS; children: React.ReactNode; style?: React.CSSProperties;
}) {
  return (
    <div className="callout" style={style}>
      {ICONS[icon]}
      <div>{children}</div>
    </div>
  );
}

export function SegDot({ index, label }: { index: number; label?: string }) {
  return (
    <span className="chip plain">
      <i style={{ width: 9, height: 9, borderRadius: 2, background: `var(--seg${index + 1})`, display: "inline-block", marginRight: 6 }} />
      {label}
    </span>
  );
}
