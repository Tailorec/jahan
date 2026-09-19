import Link from "next/link";
import Shell from "@/components/shell";
import { PageHead, Chip, Callout } from "@/components/ui";
import { readAnchorsCheck, readOntology, listOntologies, readRunDetail } from "@/lib/server";

export default async function CalibrationPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}) {
  const { run: runId } = await searchParams;
  const [anchors, ontos, detail] = await Promise.all([
    readAnchorsCheck(),
    listOntologies(),
    runId ? readRunDetail(runId).catch(() => null) : Promise.resolve(null),
  ]);
  const onto = ontos.find((o) => o.category === "beverage_protein_persona1m") ?? ontos[0];
  const full = onto ? await readOntology(onto.category, onto.version) : null;
  const trust = detail?.report?.trust ?? null;

  return (
    <Shell crumbs={<><Link href="/">Workspace</Link> / Study / <b>Calibration</b></>}>
      <PageHead
        title="Calibration & trust"
        sub="Whether results have been checked against real human data — stated once per run. The mapping claim (free text → rating distribution) is checked on human writing; the simulation claim needs human answers to the same question."
        actions={<Chip className="tier-explo">engine trust: uncalibrated</Chip>}
      />
      <style>{`.tier-ladder { display: flex; align-items: center; gap: 0; } .tier-step { flex: 1; text-align: center; position: relative; padding: 14px 8px 12px; border-top: 3px solid var(--line); color: var(--ink-3); font-size: 12px; } .tier-step b { display: block; font-size: 12.5px; color: var(--ink-2); margin-bottom: 2px; } .tier-step.done { border-top-color: var(--teal); } .tier-step.done b { color: var(--ink); } .tier-step.cur { border-top-color: var(--primary); } .tier-step.cur b { color: var(--primary-strong); }`}</style>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head"><h2>Trust ladder</h2><span className="hint">uncalibrated is the only level the engine can currently reach</span></div>
        <div className="panel-body">
          {runId && (
            <p className="sub" style={{ fontSize: 13, marginBottom: 12 }}>
              Run <span className="mono">{runId}</span>: <b>{trust ? trust.level.replace(/_/g, " ") : "no report — trust not yet stated"}</b>
              {trust?.caveats?.length ? <> — {trust.caveats.join(" ")}</> : null}
            </p>
          )}
          <div className="tier-ladder">
            <div className="tier-step cur"><b>Uncalibrated</b><span className="mono" style={{ fontSize: 10.5 }}>current · no human benchmark</span></div>
            <div className="tier-step"><b>Category-benchmarked</b><span className="mono" style={{ fontSize: 10.5 }}>needs KS ≥ 0.80 + rank ≥ 0.80</span></div>
            <div className="tier-step"><b>Prospectively-validated</b><span className="mono" style={{ fontSize: 10.5 }}>needs registered blind prediction</span></div>
          </div>
          <table className="tbl" style={{ marginTop: 12 }}><thead><tr><th>Next rung</th><th>What earns it</th></tr></thead><tbody>
            <tr><td className="strong">Category-benchmarked</td><td className="sub">a <span className="mono">CalibrationRef</span> pinning a benchmark report and a human study by content hash, measuring distribution similarity ≥ 0.80 and rank attainment ≥ 0.80 — nothing in the repository produces one</td></tr>
            <tr><td className="strong">Prospectively-validated</td><td className="sub">the above, plus a prediction registered before its outcome was observed and checked after it</td></tr>
          </tbody></table>
          <Callout icon="info" style={{ marginTop: 12 }}><div>A report may not claim to match the measured category on anything short of measured evidence — that refusal is enforced by the gate schema, not by convention. A finding&apos;s own confidence (low / medium / high) is the strength of that finding&apos;s evidence, never the engine&apos;s calibration.</div></Callout>
        </div>
      </div>

      <div className="grid g2">
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Anchor check (SSR mapping claim)</h2><span className="hint">runs/run-ssrv2/anchors-check.json</span></div>
            <div className="panel-body tight">
              {anchors ? (
                <table className="tbl"><tbody>
                  <tr><td>Anchor set</td><td className="num mono">{String(anchors.anchor_set_id)} · {String(anchors.version)}</td></tr>
                  <tr><td>Construct</td><td className="num mono">{String(anchors.construct)}</td></tr>
                  <tr><td>Embed model</td><td className="num mono">{String(anchors.embed_model_id)}</td></tr>
                  <tr><td>Personas</td><td className="num">{String(anchors.personas)}</td></tr>
                  <tr><td>Spearman min</td><td className="num">{Number(anchors.spearman_min).toFixed(3)}</td></tr>
                  <tr><td>Collapse distance</td><td className="num">{Number(anchors.collapse_distance).toFixed(3)}</td></tr>
                  <tr><td>Detail</td><td className="sub">{String(anchors.detail)}</td></tr>
                  <tr><td>Pinnable</td><td>{anchors.passed ? <span className="chip ok"><span className="dot" />passed</span> : <span className="chip risk"><span className="dot" />failed</span>}</td></tr>
                </tbody></table>
              ) : <div className="empty"><b>No anchors check.</b></div>}
            </div>
          </div>
          <Callout icon="info" style={{ marginTop: 16 }}><div>The anchor check validates the <b>mapping claim</b> only — that free text converts to the rating its author gave. It says nothing about whether simulated people answer like real ones.</div></Callout>
        </div>
        <div>
          <div className="panel">
            <div className="panel-head"><h2>Category targets</h2><span className="hint">{onto ? `${onto.category} @ ${onto.version}` : "no ontology"}</span></div>
            <div className="panel-body tight">
              {full?.targets ? (
                <table className="tbl">
                  <thead><tr><th>Attribute</th><th>Measured distribution</th><th>Source</th></tr></thead>
                  <tbody>
                    {Object.entries(full.targets.marginals).map(([a, m]) => (
                      <tr key={a}><td className="mono">{a}</td><td className="mono sub">{Object.entries(m).map(([v, p]) => `${v} ${(p * 100).toFixed(0)}%`).join(" · ")}</td><td className="sub">{full.targets?.source}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="empty"><b>No category targets declared.</b>{full ? <> Gates for <span className="mono">{full.category}</span> judge against design expectations, and the gate reference reads <span className="mono">design</span> — see any gate report.</> : null}</div>}
            </div>
          </div>
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h2>Ontologies on disk</h2></div>
            <div className="panel-body tight"><table className="tbl">
              <thead><tr><th>Category</th><th className="num">Version</th><th>Anchors</th></tr></thead>
              <tbody>
                {ontos.map((o) => (
                  <tr key={`${o.category}@${o.version}`}><td className="mono strong">{o.category}</td><td className="num mono">{o.version}</td><td className="mono sub">{o.attributes.length} attrs · {o.conditioning_set.length} conditioning</td></tr>
                ))}
              </tbody>
            </table></div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
