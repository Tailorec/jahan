"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout, TrustLine } from "@/components/ui";
import { useApi, useRunId } from "@/lib/api";
import { ORIGIN_WORDS, REFERENCE_WORDS, explainGate, explainRelaxation } from "@/lib/gates";
import type {
  CategoryOntology, FieldOrigin, GateReport, OutcomeDigest, PersonaRecord, PopulationManifest,
} from "@/lib/engine";

interface Detail {
  gate: GateReport | null;
  manifest: PopulationManifest | null;
  report: { trust: { level: string } } | null;
  digest: { digests: OutcomeDigest[] } | null;
  personas: PersonaRecord[] | null;
  personaTotal: number;
  ontology: CategoryOntology | null;
}

const SOURCE_NAMES: Record<string, string> = {
  stackoverflow: "Stack Overflow", gss: "GSS (US public)", prism: "PRISM", real_human_survey: "Real human survey",
  amazon: "Amazon reviewers", wiki: "Wikipedia figures", synthetic: "synthetic",
};
const label = (id: string) => id.replace(/^demo_/, "").replace(/_/g, " ");
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

/* A small "?" that explains a term on hover, and to a screen reader. */
function Tip({ text }: { text: string }) {
  return (
    <span title={text} aria-label={text} role="note" style={{
      display: "inline-grid", placeItems: "center", width: 15, height: 15, marginLeft: 5, borderRadius: "50%",
      border: "1px solid var(--line-2)", fontSize: 10, color: "var(--ink-3)", cursor: "help", verticalAlign: 1,
    }}>?</span>
  );
}

function OriginTag({ origin }: { origin: string }) {
  const cls = origin === "measured" ? "ok" : origin === "extracted" ? "tier-cat" : "tier-explo";
  return <span className={`tag ${cls}`} title={ORIGIN_WORDS[origin as FieldOrigin] ?? origin} style={{ cursor: "help" }}>{origin}</span>;
}

export default function PopulationPage() {
  const runId = useRunId();
  const { data, error } = useApi<Detail>(runId ? `/api/runs/${runId}` : null);
  const gate = data?.gate ?? null;
  const manifest = data?.manifest ?? null;
  const digest = data?.digest?.digests[0] ?? null;
  const personas = data?.personas ?? null;
  const onto = data?.ontology ?? null;
  const completable: string[] = (onto?.completion_policy as { completable_domains?: string[] } | undefined)?.completable_domains ?? [];
  const failures = gate?.results.filter((r) => !r.passed) ?? [];

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Population / <b>Population</b></>}>
      <PageHead
        title="Population — who is in this study"
        sub={runId ? <>
          Run <span className="mono">{runId}</span>{manifest && <> · population hash <span className="mono">{manifest.population_hash.slice(0, 12)}…</span> · draw seed <span className="mono">{manifest.population_seed}</span></>}
          <br />The <b>population gate</b> draws the personas and checks them before anything is simulated. If the draw fails, the study stops here and nothing is spent on it.
        </> : "Pick a run."}
        actions={gate && <>
          {gate.overall ? <Chip className="ok">gate passed</Chip> : <Chip className="risk">gate failed</Chip>}
          <span title="The weakest source behind the checked attributes. A pass is never read as stronger than its weakest evidence: measured (surveyed) is strongest, then calibrated, extracted (read from text), synthesized (invented)." style={{ cursor: "help" }}>
            <Chip className="tier-explo">evidence: weakest {gate.evidence}</Chip>
          </span>
        </>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading population…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !gate && <Callout icon="alert"><div>No gate-report.json for this run.</div></Callout>}
      {gate && !gate.overall && (
        <Callout icon="alert"><div>
          <b>This study never ran.</b> The draw failed {failures.length} of its {gate.results.length} checks, so no personas were kept, nothing was simulated and nothing was spent.
          {failures.length > 0 && <ul style={{ margin: "6px 0 0 16px" }}>{failures.map((r, i) => {
            const words = explainGate(r, label);
            return <li key={i}><b>{words.title}</b>: {words.failed}</li>;
          })}</ul>}
          <div style={{ marginTop: 6 }}>Fix the audience in <Link href="/who">Who you study</Link>, or draw again with another population seed and say that you did.</div>
        </div></Callout>
      )}
      {gate && (
        <>
          <div className="stat-strip" style={{ marginBottom: 20 }}>
            <div className="stat"><div className="k">Personas<Tip text="How many personas were drawn and kept for this study." /></div><div className="v">{manifest ? manifest.persona_ids.length.toLocaleString() : "none built"}</div><div className="d">{manifest ? "drawn to the audience shares" : "the draw failed its gates, so no population was kept"}</div></div>
            <div className="stat"><div className="k">Source mix<Tip text="Which dataset each drawn persona came from. If one survey dominates, the personas are mostly that survey's kind of people." /></div><div className="v" style={{ fontSize: 15 }}>{Object.entries(gate.source_mix).sort((a, b) => b[1] - a[1]).map(([s, w]) => `${SOURCE_NAMES[s] ?? s} ${pct(w)}`).join(" · ")}</div><div className="d">who the personas really are</div></div>
            <div className="stat"><div className="k">Synthesized<Tip text="The share of persona fields a model filled in because the person never answered them. Only money, media and decision fields may be filled; who people are and how they think never are." /></div><div className="v">{manifest ? <>{(manifest.synthesized_share * 100).toFixed(1)}<small>%</small></> : "—"}</div><div className="d">{manifest ? "of fields filled in by a model" : "no manifest to state it"}</div></div>
            <div className="stat"><div className="k">Relaxations<Tip text="How many times an audience's filters had to be loosened because too few people matched them exactly." /></div><div className="v">{gate.relaxations.length}</div><div className="d">{gate.relaxations.length ? "filters loosened to fill audiences" : "every audience filled as declared"}</div></div>
            <div className="stat"><div className="k">Judged against<Tip text={REFERENCE_WORDS[gate.reference]} /></div><div className="v" style={{ fontSize: 16 }}>{gate.reference === "design" ? "the study's design" : "category targets"}</div><div className="d">what the checks compare the draw with</div></div>
          </div>

          <div className="grid g2">
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Audience mix</h2><span className="hint">the shares you asked for, and what the draw reached</span></div>
                <div className="panel-body tight"><table className="tbl">
                  <thead><tr><th>Audience</th><th className="num">Asked for<Tip text="The audience's share of the study, from the audience set." /></th><th className="num">Reached<Tip text="The share of drawn personas that belong to this audience. Lower than asked means too few people matched." /></th></tr></thead>
                  <tbody>
                    {Object.keys(manifest?.requested_mix ?? gate.achieved_mix).map((a) => {
                      const asked = manifest?.requested_mix[a];
                      const reached = gate.achieved_mix[a] ?? 0;
                      const short = asked !== undefined && reached + 0.0005 < asked;
                      return (
                        <tr key={a}><td className="strong mono">{a}</td>
                          <td className="num">{asked !== undefined ? pct(asked) : "not recorded"}</td>
                          <td className="num" style={{ color: short ? "var(--risk)" : undefined }}>{pct(reached)}{short ? " — short" : ""}</td></tr>
                      );
                    })}
                  </tbody>
                </table></div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Distribution gates</h2><span className="hint">does the draw look like the people it was drawn from?</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 10 }}>
                  <p className="sub" style={{ fontSize: 12.5, margin: 0 }}>
                    Each check compares one attribute of the drawn personas with the same attribute among the people they could have been drawn from. A random draw is never a perfect copy; a check fails only when the gap is bigger than chance explains. {REFERENCE_WORDS[gate.reference]}
                  </p>
                  {gate.results.map((r, i) => {
                    const words = explainGate(r, label);
                    return (
                      <div key={i} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10, borderColor: r.passed ? "var(--line)" : "var(--risk)" }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <b style={{ textTransform: "capitalize" }}>{words.title}</b>
                          <span className="sub" style={{ fontSize: 11 }}>{r.kind === "categorical" ? "categories" : r.kind === "ordinal" ? "ordered scale" : "network"}</span>
                          <span style={{ marginLeft: "auto" }}>{r.passed ? <Chip className="ok">pass</Chip> : <Chip className="risk">fail</Chip>}</span>
                        </div>
                        <div className="sub" style={{ fontSize: 12, marginTop: 2 }}>{words.question}</div>
                        <div style={{ fontSize: 12.5, marginTop: 6 }}>{words.result} <span className="sub">{words.rule}</span></div>
                        {!r.passed && words.failed && <div style={{ fontSize: 12.5, marginTop: 4, color: "var(--risk)" }}>{words.failed}</div>}
                        <div className="mono sub" style={{ fontSize: 11, marginTop: 4 }}>
                          {words.raw}
                          <Tip text={r.kind === "categorical"
                            ? "Chi-square test. χ² measures how far the drawn counts are from the expected counts; dof is the number of categories minus one; p is the chance of a gap at least this big if the draw were fair. Pass when p is above the significance level."
                            : r.kind === "ordinal"
                              ? "Kolmogorov–Smirnov test. D is the largest gap between the two cumulative spreads across the ordered bands; similarity is 1 − D. Pass when similarity reaches the threshold."
                              : "A structural measure of the generated social network, with the floor it must reach."} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              {gate.relaxations.length > 0 && (
                <Callout icon="alert"><div><b>{gate.relaxations.length} relaxation{gate.relaxations.length > 1 ? "s" : ""}: </b>
                  some audiences are no longer exactly what was declared, because too few people matched.
                  {gate.relaxations.map((r, i) => <div key={i} style={{ fontSize: 12.5, marginTop: 4 }}>{explainRelaxation(r, label)}</div>)}</div></Callout>
              )}
              <div className="panel">
                <div className="panel-head"><h2>Completion</h2><span className="hint">fields a model may fill when a person never answered them</span></div>
                <div className="panel-body tight"><table className="tbl"><tbody>
                  <tr><td>May be filled in<Tip text="Kinds of field a model may complete for a persona who left them blank, as the category's ontology allows." /></td><td className="mono sub">{completable.length ? completable.join(", ") : "—"}</td></tr>
                  <tr><td>Never filled in<Tip text="Who a person is and how they think are only ever what they said; a persona without them is not drawn." /></td><td className="mono sub">demographic, psychographic</td></tr>
                  <tr><td>Model that filled them</td><td className="num mono">{manifest?.completion?.model_id ?? "—"}</td></tr>
                  <tr><td>Social graph<Tip text="The fingerprint of the network the personas are connected by; the same draw always builds the same network." /></td><td className="num mono">{manifest ? (manifest.graph_hash ? `${manifest.graph_hash.slice(0, 12)}…` : "none attached") : "—"}</td></tr>
                </tbody></table></div>
              </div>
            </div>
            <div>
              <div className="panel">
                <div className="panel-head"><h2>Sample personas</h2><span className="hint">{(data?.personaTotal ?? 0).toLocaleString()} in this study — hover a tag for where a value came from</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                  <div className="sub" style={{ fontSize: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {(["measured", "extracted", "synthesized"] as FieldOrigin[]).map((o) => <span key={o}><OriginTag origin={o} /> {ORIGIN_WORDS[o].split(" — ")[1]}</span>)}
                  </div>
                  {!personas && (manifest
                    ? <div className="empty"><b>No persona records.</b>Runs recorded before personas.json need a re-run — the manifest alone cannot say where a field came from.</div>
                    : <div className="empty"><b>No personas were built.</b>The draw failed its gates before any persona was kept, so there is no record to sample.</div>)}
                  {(personas ?? []).map((p) => (
                    <div key={p.persona_id} style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", padding: 10 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <b className="mono">{p.persona_id}</b>
                        <span className="tag">from {SOURCE_NAMES[p.source] ?? p.source}</span>
                        <Link href={`/trace?run=${runId}&persona=${encodeURIComponent(p.persona_id)}`} style={{ marginLeft: "auto", fontSize: 12 }}>beliefs →</Link>
                      </div>
                      <div className="mono sub" style={{ marginTop: 6, fontSize: 11.5 }}>
                        {Object.entries({ ...p.conditioning, ...p.attributes }).map(([k, v]) => (
                          <span key={k} style={{ marginRight: 10 }}>{k}={String(v)} <OriginTag origin={p.origins[k] ?? "?"} /></span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel">
                <div className="panel-head"><h2>Audiences vs communities</h2><span className="hint">the groups you declared, against the groups the network formed</span></div>
                <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                  <p className="sub" style={{ fontSize: 12.5 }}>Audiences are the groups you declared. Communities are groups of personas who ended up closely tied in the social network; they often cut across audiences, and that is a finding, not a defect.</p>
                  {digest && Object.keys(digest.community_sizes ?? {}).length > 0 ? (
                    <table className="tbl"><thead><tr><th>Community</th><th className="num">Share of personas</th></tr></thead><tbody>
                      {Object.entries(digest.community_sizes).map(([c, s]) => (
                        <tr key={c}><td className="mono">{c}</td><td className="num">{pct(s)}</td></tr>
                      ))}
                    </tbody></table>
                  ) : (
                    <div className="empty"><b>No communities formed.</b>{digest?.polarization_reason ? <> {digest.polarization_reason}</> : " The network formed no clear groups, so polarization is unmeasured rather than zero."}</div>
                  )}
                  {digest && <p className="sub" style={{ fontSize: 12 }}>
                    <span className="mono">world {digest.world_id}</span> · audience divergence <b>{digest.audience_divergence != null ? digest.audience_divergence.toFixed(3) : "—"}</b>
                    <Tip text="How differently the audiences ended up responding: 0 means they answered alike, higher means further apart." />
                    {" "}· polarization <b>{digest.polarization != null ? digest.polarization.toFixed(3) : "unmeasured"}</b>
                    <Tip text="How far the communities split into opposing views: 0 means none. Unmeasured when the network formed no communities to compare." />
                  </p>}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}
