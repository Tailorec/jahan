"use client";

import Link from "next/link";
import Shell from "@/components/shell";
import RunBar from "@/components/runbar";
import { PageHead, Chip, Callout, TrustLine, ICONS, Section, Tip, Kpi } from "@/components/ui";
import React from "react";
import { useApi, useRunId } from "@/lib/api";
import { PALETTE, SocialGraph } from "./social-graph";
import { SOURCE_COLORS, SOURCE_NAMES, TEXT_SOURCES } from "@/lib/sources";
import { ORIGIN_WORDS, REFERENCE_WORDS, explainGate, explainRelaxation, gateMeter, type GateMeter } from "@/lib/gates";
import { DOMAIN_WORDS } from "@/lib/engine";
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
  summary: { launch_error?: string | null } | null;
}

const label = (id: string) => id.replace(/^demo_/, "").replace(/_/g, " ");
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

/* Where one result landed against its pass line: the pale zone below the line fails, the dot is this draw. */
function Meter({ meter, passed }: { meter: GateMeter; passed: boolean }) {
  const at = (x: number) => `${Math.min(100, Math.max(0, (x / meter.max) * 100))}%`;
  return (
    <div aria-hidden style={{ position: "relative", height: 8, borderRadius: 4, background: "var(--surface-2)" }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: at(meter.line), background: "var(--risk-soft)", borderRadius: "4px 0 0 4px", borderRight: "1px solid var(--line-2)" }} />
      <div style={{ position: "absolute", left: at(meter.line), top: -3, bottom: -3, width: 2, marginLeft: -1, background: "var(--ink-3)" }} />
      <div style={{ position: "absolute", left: at(meter.value), top: -3, width: 14, height: 14, marginLeft: -7, borderRadius: "50%", background: passed ? "var(--ok)" : "var(--risk)", border: "2px solid var(--bg)", boxShadow: "0 0 0 1px var(--line-2)" }} />
    </div>
  );
}

/* Who the personas really are: each source's share as one bar, then a line per source, largest first; a source
   whose answers were read from text by a model says so. */
function SourceMix({ mix }: { mix: Record<string, number> }) {
  const entries = Object.entries(mix).sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "var(--surface-2)" }}>
        {entries.map(([s, w]) => <span key={s} title={`${SOURCE_NAMES[s] ?? s}: ${pct(w)}`} style={{ width: `${w * 100}%`, background: SOURCE_COLORS[s] ?? "var(--ink-3)" }} />)}
      </div>
      <div style={{ display: "grid", gap: 3, marginTop: 8, fontSize: 12 }}>
        {entries.map(([s, w]) => (
          <div key={s} style={{ display: "grid", gridTemplateColumns: "10px 1fr auto", gap: 6, alignItems: "center" }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: SOURCE_COLORS[s] ?? "var(--ink-3)" }} />
            <span>{SOURCE_NAMES[s] ?? s}{TEXT_SOURCES.includes(s) && <span style={{ color: "oklch(0.5 0.11 70)", fontSize: 11 }}> · read from text</span>}</span>
            <span className="mono" style={{ fontVariantNumeric: "tabular-nums" }}>{pct(w)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* The social graph takes its tip as a prop of text; this hands it the shared one. */
function TextTip({ text }: { text: string }) {
  return <Tip>{text}</Tip>;
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
      <RunBar runId={runId} />
      <PageHead
        title="Population"
        sub={runId ? <>
          <span className="mono">{runId}</span>{manifest && <> · seed <span className="mono">{manifest.population_seed}</span> · hash <span className="mono">{manifest.population_hash.slice(0, 12)}…</span></>}
          {" "}<Tip>The <b>population gate</b> draws the personas and checks them before anything is simulated. If the draw fails, the study stops here and nothing is spent on it.</Tip>
        </> : "Pick a run."}
        actions={gate && <>
          {gate.overall ? <Chip className="ok">gate passed</Chip> : <Chip className="risk">gate failed</Chip>}
          <Chip className="tier-explo" title="The weakest source behind the checked attributes. A pass is never read as stronger than its weakest evidence: measured (surveyed) is strongest, then calibrated, extracted (read from text), synthesized (invented).">evidence: weakest {gate.evidence}</Chip>
        </>}
      />
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      {!data && !error && <div className="empty"><b>Loading population…</b></div>}
      {data && <TrustLine level={data.report?.trust.level ?? null} runId={runId} />}
      {data && !gate && <Callout icon="alert"><div>No gate-report.json for this run.</div></Callout>}
      {gate && gate.overall && !manifest && (
        <Callout icon="alert"><div>
          <b>The draw passed every check, but the population was not built.</b> Building it — filling unanswered fields and
          connecting the personas into a social network — stopped, so no personas were kept and nothing was simulated.
          <div className="mono" style={{ fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}>{data?.summary?.launch_error ?? "No reason was recorded for this run: run the gate again, and the reason appears here."}</div>
        </div></Callout>
      )}
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
          <div className="kpis" style={{ marginBottom: 16 }}>
            <Kpi icon="users" label="Personas" tip="How many personas were drawn and kept for this study."
              value={manifest ? manifest.persona_ids.length.toLocaleString() : "none"}
              note={manifest ? undefined : gate.overall ? "build stopped" : "draw failed"} />
            <Kpi icon="shield" label="Checks passed" tip="Distribution gates: does the draw look like the people it was drawn from?"
              value={`${gate.results.length - failures.length}/${gate.results.length}`} tone={failures.length ? "no" : "ok"} />
            <Kpi icon="sparkles" label="Synthesized" tip="The share of persona fields a model filled in because the person never answered them. Only money, media and decision fields may be filled; who people are and how they think never are."
              value={manifest ? `${(manifest.synthesized_share * 100).toFixed(1)}%` : "—"} />
            <Kpi icon="sliders" label="Relaxations" tip="How many times an audience's filters had to be loosened because too few people matched them exactly."
              value={String(gate.relaxations.length)} tone={gate.relaxations.length ? "warn" : undefined} />
            <Kpi icon="target" label="Judged against" tip={REFERENCE_WORDS[gate.reference]}
              value={gate.reference === "design" ? "design" : "category"} />
          </div>

          <div className="grid g2">
            <div>
              <Section icon="users" title="Audience mix" tip="The shares you asked for, and what the draw reached. The dark tick is the share asked for; the bar is the share reached.">
                <AudienceMix asked={manifest?.requested_mix ?? null} reached={gate.achieved_mix} people={manifest?.persona_ids.length ?? null} relaxations={gate.relaxations} />
              </Section>
              <Section icon="shield" title="Distribution gates" done={!failures.length}
                tip={`Does the draw look like the people it was drawn from? Each check compares one attribute of the drawn personas with the same attribute among the people they could have been drawn from. A random draw is never a perfect copy, so a check fails only when the gap is bigger than chance explains. ${REFERENCE_WORDS[gate.reference]}`}>
                <div style={{ display: "grid", gap: 10 }}>
                  <div className="row sub" style={{ fontSize: 11.5, gap: 12, flexWrap: "wrap" }}>
                    <span><span style={{ display: "inline-block", width: 14, height: 7, background: "var(--risk-soft)", border: "1px solid var(--line-2)", verticalAlign: 0 }} /> fails</span>
                    <span><span style={{ display: "inline-block", width: 2, height: 11, background: "var(--ink-3)", verticalAlign: -1 }} /> pass line</span>
                    <span><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: "var(--ok)", verticalAlign: 0 }} /> this draw</span>
                  </div>
                  <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-md)", overflow: "hidden" }}>
                    {gate.results.map((r, i) => {
                      const words = explainGate(r, label);
                      const meter = gateMeter(r);
                      return (
                        <details key={i} open={!r.passed} style={{ borderTop: i ? "1px solid var(--line)" : 0, boxShadow: r.passed ? undefined : "inset 3px 0 0 var(--risk)" }}>
                          <summary style={{ display: "grid", gridTemplateColumns: "20px minmax(0, 1fr) minmax(120px, 1.2fr)", gap: 12, alignItems: "center", padding: "10px 12px", cursor: "pointer", listStyle: "none" }}>
                            <span style={{ color: r.passed ? "var(--ok)" : "var(--risk)", display: "inline-flex" }} aria-label={r.passed ? "pass" : "fail"}>{r.passed ? ICONS.check : ICONS.x}</span>
                            <span>
                              <b style={{ textTransform: "capitalize" }}>{words.title}</b>
                              <div className="sub" style={{ fontSize: 11 }}>{r.kind === "categorical" ? "categories" : r.kind === "ordinal" ? "ordered scale" : "network"}</div>
                            </span>
                            <span>
                              <Meter meter={meter} passed={r.passed} />
                              <div className="mono sub" style={{ fontSize: 11, marginTop: 7 }}>{meter.short}</div>
                            </span>
                          </summary>
                          <div style={{ padding: "0 12px 12px 44px", fontSize: 12.5, display: "grid", gap: 4 }}>
                            <div className="sub">{words.question}</div>
                            <div>{words.result} <span className="sub">{words.rule}</span></div>
                            {!r.passed && words.failed && <div style={{ color: "var(--risk)" }}>{words.failed}</div>}
                            <div className="mono sub" style={{ fontSize: 11 }}>
                              {words.raw}{" "}
                              <Tip>{r.kind === "categorical"
                                ? "Chi-square test. χ² measures how far the drawn counts are from the expected counts; dof is the number of categories minus one; p is the chance of a gap at least this big if the draw were fair. Pass when p is above the significance level."
                                : r.kind === "ordinal"
                                  ? "Kolmogorov–Smirnov test. D is the largest gap between the two cumulative spreads across the ordered bands; similarity is 1 − D. Pass when similarity reaches the threshold."
                                  : "A structural measure of the generated social network, with the floor it must reach."}</Tip>
                            </div>
                          </div>
                        </details>
                      );
                    })}
                  </div>
                </div>
              </Section>
              <Section icon="sparkles" title="Completion" tip="Fields a model may fill when a person never answered them — and the ones it never may.">
                <Completion ontology={onto} origins={gate.attribute_origins} synthesized={manifest?.synthesized_share ?? null} model={manifest?.completion?.model_id ?? null} />
              </Section>
            </div>
            <div>
              <Section icon="pie" title="Source mix" tip="Which dataset each drawn persona came from. If one survey dominates, the personas are mostly that survey's kind of people.">
                <SourceMix mix={gate.source_mix} />
              </Section>
              <Section icon="fork" title="Audiences vs communities"
                tip="Audiences are the groups you declared. Communities are groups of personas who ended up closely tied in the social network; they often cut across audiences, and that is a finding, not a defect.">
                <div style={{ display: "grid", gap: 8 }}>
                  {digest && Object.keys(digest.community_sizes ?? {}).length > 0 ? (
                    <table className="tbl"><thead><tr><th>Community</th><th className="num">Share of personas</th></tr></thead><tbody>
                      {Object.entries(digest.community_sizes).map(([c, s]) => (
                        <tr key={c}><td className="mono">{c}</td><td className="num">{pct(s)}</td></tr>
                      ))}
                    </tbody></table>
                  ) : !digest ? (
                    <div className="empty" style={{ padding: 20 }}><b>{ICONS.clock} Not yet — the study has not run.</b>Communities form as the study runs. <Tip>Communities are found in the social network as the study runs: who talks to whom, and which groups form. A gate run builds the network but runs nothing, so there is nothing to show until the study is launched.</Tip></div>
                  ) : (
                    <div className="empty" style={{ padding: 20 }}><b>No communities formed.</b>{digest.polarization_reason ? <> {digest.polarization_reason}</> : " The network formed no clear groups, so polarization is unmeasured rather than zero."}</div>
                  )}
                  {digest && <div className="row sub" style={{ fontSize: 12, flexWrap: "wrap" }}>
                    <span className="mono">world {digest.world_id}</span>
                    <span>audience divergence <b>{digest.audience_divergence != null ? digest.audience_divergence.toFixed(3) : "—"}</b></span>
                    <Tip>How differently the audiences ended up responding: 0 means they answered alike, higher means further apart.</Tip>
                    <span>polarization <b>{digest.polarization != null ? digest.polarization.toFixed(3) : "unmeasured"}</b></span>
                    <Tip>How far the communities split into opposing views: 0 means none. Unmeasured when the network formed no communities to compare.</Tip>
                  </div>}
                </div>
              </Section>
            </div>
          </div>
          {manifest && runId && (
            <Section icon="network" title="Social network" tip="Who knows whom among the personas — word of mouth, feeds and forums travel along these ties.">
              <SocialGraph runId={runId} Meter={Meter} Tip={TextTip} />
            </Section>
          )}
          <Section icon="table" title={`Personas · ${(data?.personaTotal ?? 0).toLocaleString()}`}
            tip="All the personas in this study, read from its personas.json — each value coloured by where it came from. Hover a value for its origin.">
            <div style={{ display: "grid", gap: 8 }}>
              <div className="row" style={{ fontSize: 12, flexWrap: "wrap", gap: 12 }}>
                {(["measured", "extracted", "synthesized"] as FieldOrigin[]).map((o) => (
                  <span key={o} className="row" style={{ gap: 4 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: ORIGIN_COLOR[o] }} /><b style={{ color: ORIGIN_COLOR[o] }}>{o}</b><Tip>{ORIGIN_WORDS[o]}</Tip></span>
                ))}
              </div>
              {!personas && (manifest
                ? <div className="empty"><b>No persona records.</b>Runs recorded before personas.json need a re-run — the manifest alone cannot say where a field came from.</div>
                : <div className="empty"><b>No personas were built.</b>{gate?.overall ? "The draw passed its gates, but building the population stopped — see the note above." : "The draw failed its gates before any persona was kept, so there is no record to sample."}</div>)}
              {personas && runId && <PersonaTable runId={runId} total={data?.personaTotal ?? 0} order={onto?.relevance_order ?? []} />}
            </div>
          </Section>
        </>
      )}
    </Shell>
  );
}

const PAGE = 50;
const ORIGIN_COLOR: Record<string, string> = { measured: "var(--ink)", calibrated: "var(--ink)", extracted: "oklch(0.5 0.11 70)", synthesized: "var(--risk)" };

/* Every persona the study drew, a page at a time from the engine: one row each, one column per field, each
   value coloured by where it came from and explained on hover. */
function PersonaTable({ runId, total, order }: { runId: string; total: number; order: string[] }) {
  const [offset, setOffset] = React.useState(0);
  const { data, error } = useApi<{ personas: PersonaRecord[]; total: number }>(`/api/runs/${encodeURIComponent(runId)}/personas?offset=${offset}&limit=${PAGE}`);
  const rows = data?.personas ?? [];
  // The ontology's own order, the same on every page; anything else a record carries follows, sorted.
  const carried = [...new Set(rows.flatMap((p) => [...Object.keys(p.conditioning), ...Object.keys(p.attributes)]))];
  const fields = [...order, ...carried.filter((f) => !order.includes(f)).sort()];
  const last = Math.min(offset + PAGE, total);
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {error && <Callout icon="alert"><div>{error}</div></Callout>}
      <div style={{ overflowX: "auto", border: "1px solid var(--line)", borderRadius: "var(--r-md)" }}>
        <table className="tbl" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
          <thead><tr><th>Persona</th><th>From</th>{fields.map((f) => <th key={f}>{f.replace(/^demo_/, "").replace(/_/g, " ")}</th>)}<th /></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.persona_id}>
                <td className="mono">{p.persona_id}</td>
                <td>{SOURCE_NAMES[p.source] ?? p.source}</td>
                {fields.map((f) => {
                  const value = p.conditioning[f] ?? p.attributes[f];
                  const origin = p.origins[f] ?? "";
                  return <td key={f} title={value === undefined ? "not answered" : ORIGIN_WORDS[origin as FieldOrigin] ?? origin}
                    style={{ color: value === undefined ? "var(--ink-3)" : ORIGIN_COLOR[origin] ?? undefined, cursor: "help" }}>{value === undefined ? "—" : String(value)}</td>;
                })}
                <td><Link href={`/trace?run=${runId}&persona=${encodeURIComponent(p.persona_id)}`} style={{ fontSize: 12 }}>beliefs →</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12 }}>
        <span className="sub">{total ? `${(offset + 1).toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()}` : "none"}</span>
        <button className="btn sm" style={{ marginLeft: "auto" }} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Previous</button>
        <button className="btn sm" disabled={last >= total} onClick={() => setOffset(offset + PAGE)}>Next {PAGE} →</button>
      </div>
    </div>
  );
}

/* Each audience as a row: the share asked for as a tick, the share reached as a bar, how many people that is,
   and anything that had to be loosened to reach it. Colours match the social network's. */
function AudienceMix({ asked, reached, people, relaxations }: {
  asked: Record<string, number> | null; reached: Record<string, number>; people: number | null;
  relaxations: GateReport["relaxations"];
}) {
  const names = Object.keys(asked ?? reached);
  const colour = (name: string) => PALETTE[[...names].sort().indexOf(name) % PALETTE.length];
  const top = Math.max(0.05, ...names.map((n) => Math.max(asked?.[n] ?? 0, reached[n] ?? 0)));
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div title="The whole population, by audience" style={{ display: "flex", height: 12, borderRadius: 6, overflow: "hidden", background: "var(--surface-2)" }}>
        {names.map((n) => <span key={n} title={`${label(n)}: ${pct(reached[n] ?? 0)}`} style={{ width: `${(reached[n] ?? 0) * 100}%`, background: colour(n) }} />)}
      </div>
      {names.map((n) => {
        const want = asked?.[n];
        const got = reached[n] ?? 0;
        const short = want !== undefined && got + 0.0005 < want;
        const loosened = relaxations.filter((r) => r.audience === n);
        return (
          <div key={n} style={{ display: "grid", gap: 4 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: colour(n), alignSelf: "center" }} />
              <b style={{ textTransform: "capitalize" }}>{label(n)}</b>
              <span className="sub" style={{ marginLeft: "auto", fontSize: 12 }}>
                {people !== null && <><b style={{ color: "var(--ink)" }}>{Math.round(got * people).toLocaleString()}</b> people · </>}
                reached <b style={{ color: short ? "var(--risk)" : "var(--ink)" }}>{pct(got)}</b>{want !== undefined && <> of {pct(want)} asked</>}
              </span>
            </div>
            <div style={{ position: "relative", height: 8, borderRadius: 4, background: "var(--surface-2)" }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(got / top) * 100}%`, borderRadius: 4, background: colour(n), opacity: short ? 0.55 : 1 }} />
              {want !== undefined && <div title={`asked for ${pct(want)}`} style={{ position: "absolute", left: `${(want / top) * 100}%`, top: -3, bottom: -3, width: 2, marginLeft: -1, background: "var(--ink)" }} />}
            </div>
            {short && people !== null && want !== undefined && (
              <div style={{ fontSize: 12, color: "var(--risk)" }}>Short by {Math.round((want - got) * people).toLocaleString()} people: too few matched this audience.</div>
            )}
            {loosened.map((r, i) => <div key={i} className="note-line" style={{ fontSize: 12, color: "oklch(0.42 0.10 85)" }}>Loosened: {explainRelaxation(r, label)}</div>)}
          </div>
        );
      })}
      <div className="row sub" style={{ fontSize: 11.5, gap: 10 }}>
        <span><span style={{ display: "inline-block", width: 2, height: 11, background: "var(--ink)", verticalAlign: -1 }} /> asked for</span>
        <span><span style={{ display: "inline-block", width: 14, height: 7, borderRadius: 3, background: "var(--ink-3)", verticalAlign: 0 }} /> reached</span>
        <Tip>Reached below asked means the audience&apos;s pool held too few people. Filters loosened to reach a share are listed under its audience, and the audience is then no longer exactly what was declared.</Tip>
      </div>
    </div>
  );
}

/* What a model was allowed to fill, what it did fill, and which of this study's attributes each rule covers. */
function Completion({ ontology, origins, synthesized, model }: {
  ontology: CategoryOntology | null; origins: Record<string, FieldOrigin>; synthesized: number | null; model: string | null;
}) {
  const allowed = new Set<string>((ontology?.completion_policy?.completable_domains ?? []) as string[]);
  const words = Object.fromEntries(DOMAIN_WORDS) as Record<string, string>;
  const attributes = Object.entries(ontology?.attribute_domains ?? {});
  const may = attributes.filter(([, d]) => allowed.has(d));
  const never = attributes.filter(([, d]) => !allowed.has(d));
  const chip = (text: string, open: boolean) => (
    <span key={text} className="tag" style={{ background: open ? "var(--warn-soft)" : "var(--ok-soft)", borderColor: "transparent" }}>{text}</span>
  );
  const row = ([id, domain]: [string, string]) => (
    <div key={id} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 150px 84px", gap: 8, fontSize: 12, padding: "3px 0", borderTop: "1px solid var(--line)" }}>
      <span className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{id}</span>
      <span className="sub">{words[domain] ?? domain}</span>
      <span title={origins[id] ? ORIGIN_WORDS[origins[id]] : "not checked by the gate"} style={{ cursor: "help", color: origins[id] === "synthesized" ? "var(--risk)" : origins[id] === "extracted" ? "oklch(0.5 0.11 70)" : "var(--ink-3)" }}>{origins[id] ?? "—"}</span>
    </div>
  );
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontSize: 26, fontWeight: 650, fontVariantNumeric: "tabular-nums" }}>{synthesized === null ? "—" : `${(synthesized * 100).toFixed(1)}%`}</span>
        <span className="sub" style={{ fontSize: 12.5 }}>
          {synthesized === null ? "no population was built, so nothing was filled"
            : synthesized === 0 ? "filled by a model — every value came from the people themselves"
              : <>filled by a model{model && <> · <span className="mono">{model}</span></>}</>}
        </span>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        <div style={{ fontSize: 12.5 }}>
          <b>May be filled in</b> <Tip>When a person left them blank. The category&apos;s ontology lists the kinds of field a model may complete. Only these, and only for a persona who never answered.</Tip>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>{[...allowed].map((d) => chip(words[d] ?? d, true))}{!allowed.size && <span className="sub">{ontology ? "nothing — this category lets no field be filled" : "not recorded with this run — its ontology was not kept"}</span>}</div>
        </div>
        <div style={{ fontSize: 12.5 }}>
          <b>Never filled in</b> <Tip>Who a person is and how they think are only ever what they said. A persona missing a required one is not drawn at all; a missing optional one stays missing.</Tip>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>{(ontology ? DOMAIN_WORDS.filter(([d]) => !allowed.has(d)) : DOMAIN_WORDS.slice(0, 2)).map(([, w]) => chip(w, false))}</div>
        </div>
      </div>
      {attributes.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: 12.5 }}>This study&apos;s {attributes.length} attributes: {may.length} may be filled, {never.length} never</summary>
          <div style={{ marginTop: 6 }}>
            <div className="sub" style={{ fontSize: 11, display: "grid", gridTemplateColumns: "minmax(0, 1fr) 150px 84px", gap: 8 }}><span>attribute</span><span>kind</span><span>came from</span></div>
            {may.length > 0 && <div className="sub" style={{ fontSize: 11, marginTop: 6 }}>may be filled</div>}
            {may.map(row)}
            <div className="sub" style={{ fontSize: 11, marginTop: 6 }}>never filled</div>
            {never.map(row)}
          </div>
        </details>
      )}
    </div>
  );
}

