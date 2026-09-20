# ConsumerSim frontend — UI layer for sim_engine (Next.js)

Same lab-instrument design system as `~/jahan_sim/mockups` (Inter + JetBrains Mono, honey-amber tokens in
`app/globals.css`), but every page is bound to the engine's real domain. Vocabulary follows `CONTEXT.md`:
Population, Audience, Community — never cohort or segment.

## How it connects to the engine

Over HTTP, and nothing else. The interface holds no engine logic: it reads no run directory, starts no
process and finds no checkout. Its own `app/api/*` routes are proxies to the engine API
(`python -m simcore.web`, from the `simcore[web]` extra), so there is one path to every number.

```bash
# the engine (from the sim_engine checkout)
uv run --extra web python -m simcore.web --runs runs --port 8000

# the interface
cd frontend && npm install
SIMCORE_WEB_URL=http://127.0.0.1:8000 npm run dev   # http://localhost:3000 — the default URL is the one above
```

`SIMCORE_WEB_URL` is the only thing the interface is configured with. The inference endpoint, its key and its
limits are the *server's* environment: this interface reports whether an endpoint is configured and never asks
for, accepts or displays a key.

| UI surface | Engine source |
|---|---|
| Overview — runs, ontologies, briefs, totals | `/api/workspace` (derived in `analysis` over registry entries), `/api/runs`, `/api/ontologies`, `/api/briefs` |
| Intake — brief authoring, brief check, population gate, launch | `/api/briefs/validate` (the assumption ledger), `/api/gate`, `POST /api/runs`, `/api/status`, `/api/corpus` (cached shards, sources), `/api/anchors` (each scale version with its check verdict, and the default) |
| Ontology builder | `/api/codebook`, `/api/ontologies/validate`, `POST /api/ontologies` (a new version, never an overwrite) |
| Population — gates, requested vs achieved mix, origins, communities | `/api/runs/{id}` (`gate`, `manifest`, `personas`, `ontology`, `digest`) |
| Run — watched live, cancel, resume | `/api/runs/{id}` (progress, spend, rung), `DELETE /api/runs/{id}`, `POST /api/runs/{id}/resume` |
| Trace, persona history | `/api/runs/{id}/summary`, `/events`, `/resolve`, `…/worlds/{w}/turns/{t}/prompt` (rebuilt and verified against the turn's hash) |
| Atlas, report | `/api/runs/{id}` (`digest`, `report`) |
| Calibration | `/api/trust` (the ladder and the floors), `/api/anchors-checks`, the run's `report.trust` |

`lib/engine.ts` mirrors `simcore/schemas`. `lib/server.ts` is the API client; `lib/refusal.ts` keeps the reason
the engine gave for a refusal all the way to the screen; `lib/briefYaml.ts` writes the form's brief out as the
YAML intake reads (and back), with an audience's filter kept as the value, list or range it was stated as.

## Tests

```bash
npm test                                   # the plain functions in lib/, under node's own runner
uv run --extra web pytest tests/boundary/web/test_interface.py   # from sim_engine/: the real stack
```

`test_interface.py` starts the engine API and this server against a fake study and a gate-only run, asks the
routes what the pages ask, and renders every page in headless Chrome (skipped where none is installed).
