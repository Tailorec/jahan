# ConsumerSim frontend — UI layer for sim_engine (Next.js)

Same lab-instrument design system as `~/jahan_sim/mockups` (Inter + JetBrains
Mono, honey-amber tokens in `app/globals.css`), but every page is bound to the
engine's real domain and artefacts. Vocabulary follows `CONTEXT.md`.

## How it connects to the engine

No mocks. The UI reads the checkout live (override with `SIM_ENGINE_ROOT`):

| UI surface | Engine source |
|---|---|
| Overview — runs, ontologies, briefs | `runs/*/result.json`, `gate-report.json`, `report.json`, `ontologies/*/`, `examples/*.yaml` |
| Intake — brief authoring + cohort gate | `CategoryOntology` JSON (attribute pickers, conditioning set); `POST /api/gate` runs the real `coreset-gate --fake` CLI and persists the run under `runs/` |
| Cohort — gate report viewer | `gate-report.json` (χ²/KS gates, source mix, field origins, relaxations) + `manifest.json` |
| Run — registry, cost ledger, worlds, digests | `result.json`, `digest.json` (audience PMFs, adoption, belief movement, action mix, WOM, rungs, replicate spread) |
| Atlas — sweep matrix | scenarios × seeds from the run config with measured digests |
| Report — findings, objections, ledger, method | `report.json` (evidence trace ids deep-link into trace view) |
| Trace — the 5 Trace View questions | `runs/<id>/ui-trace.json`, produced by `scripts/export_ui_trace.py` through simcore's own `ParquetTraceView` |
| Calibration — anchor check, trust, targets | `runs/run-ssrv2/anchors-check.json`, ontology `targets` |

`lib/engine.ts` mirrors `simcore/schemas` (brief, claim sources, audiences,
gates, digests, findings, trace view). `lib/server.ts` reads artefacts;
`app/api/*` serves them.

## Trace export

After a run finalizes, answer trace questions in the UI with:

```bash
.venv/bin/python scripts/export_ui_trace.py runs/<run-id>
```

This dumps event counts, sampled belief histories, top edges, verbatim groups,
cost by role, and all finding evidence resolved through the Trace View.

## Run it

```bash
npm install
npm run dev   # http://localhost:3000
npm run build # production check
```
