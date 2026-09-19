"""The HTTP surface: one path to every number, and no arithmetic on the way there.

Each of the five shapes has an endpoint returning frozen models, with a typed
filter (`EventFilter`, `VerbatimGrouping`) rather than free keyword arguments.
Run artefacts (`digest.json`, `report.json`, `trace-summary.json`) are read and
returned as written — the CLI wrote them from the same functions this module
calls live, so neither path recomputes what the other computes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from simcore.analysis import trace_summary
from simcore.runner import ENGINE_VERSION
from simcore.schemas import EventFilter, VerbatimGrouping
from simcore.trace import TraceStore

# An open tick range runs to the last tick ever recorded; the bound is a
# constant, not arithmetic over what is served.
_MAX_TICK = 2147483647


def _runs_dir(request: Request) -> Path:
    return Path(request.app.state.runs_dir)


def _run_dir(request: Request, run_id: str) -> Path:
    candidate = Path(_runs_dir(request), run_id)
    if candidate.is_dir():
        return candidate
    raise _missing(f"no record of run {run_id}")


def _missing(detail: str) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=404, detail=detail)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _missing(f"no record at {path.name}")


def _store(run_dir: Path) -> TraceStore:
    return TraceStore(Path(run_dir, "trace"))


def _worlds_of(store: TraceStore, run_id: str) -> tuple[str, ...]:
    try:
        return tuple(store.world_ids(run_id))
    except Exception:
        raise _missing(f"no record of run {run_id}")


def _view(store: TraceStore, run_id: str, world_id: str | None):
    try:
        return store.view(run_id, world_id)
    except Exception:
        raise _missing(f"no record of world {world_id} in run {run_id}")


def _event_filter(
    kinds: list[str] | None,
    persona_ids: list[str] | None,
    world_ids: list[str] | None,
    tick_from: int | None,
    tick_to: int | None,
) -> EventFilter:
    """The typed filter one shape takes — a closed object, never free kwargs."""
    ticks: tuple[int, int] | None = None
    if tick_from is not None or tick_to is not None:
        ticks = (tick_from if tick_from is not None else 0, tick_to if tick_to is not None else _MAX_TICK)
    return EventFilter.model_validate({
        "kinds": tuple(kinds or ()),
        "persona_ids": tuple(persona_ids or ()),
        "world_ids": tuple(world_ids or ()),
        "ticks": ticks,
    })


def _page(items: list[Any], offset: int, limit: int) -> list[Any]:
    """One page of an ordered shape. Slicing, never arithmetic over what is served."""
    return items[offset:][:limit]


def create_app(
    *,
    runs_dir: str | Path,
    ontology_dir: str | Path | None = None,
    briefs_dir: str | Path | None = None,
) -> FastAPI:
    """Serve the engine's record over HTTP. Reads artefacts and views, derives nothing."""
    app = FastAPI(title="ConsumerSim engine API")
    app.state.runs_dir = str(runs_dir)
    app.state.ontology_dir = str(ontology_dir) if ontology_dir is not None else None
    app.state.briefs_dir = str(briefs_dir) if briefs_dir is not None else None

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine_version": ENGINE_VERSION}

    @app.get("/api/runs")
    def list_runs(request: Request) -> dict[str, Any]:
        runs = []
        for child in sorted(_runs_dir(request).iterdir()):
            if child.is_dir():
                entry = _run_entry(child)
                if entry is not None:
                    runs.append(entry)
        return {"runs": runs}

    @app.get("/api/runs/{run_id}")
    def run_detail(request: Request, run_id: str) -> dict[str, Any]:
        entry = _run_entry(_run_dir(request, run_id))
        if entry is None:
            raise _missing(f"no record of run {run_id}")
        return entry

    @app.get("/api/runs/{run_id}/summary")
    def run_summary(request: Request, run_id: str) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        stored = Path(run_dir, "trace-summary.json")
        if stored.is_file():
            return _read_json(stored)
        store = _store(run_dir)
        worlds = _worlds_of(store, run_id)
        views = {world_id: _view(store, run_id, world_id) for world_id in worlds}
        return json.loads(trace_summary(views, run_id=run_id).model_dump_json())

    @app.get("/api/runs/{run_id}/events")
    def run_events(
        request: Request,
        run_id: str,
        world_id: list[str] | None = Query(default=None),
        kind: list[str] | None = Query(default=None),
        persona_id: list[str] | None = Query(default=None),
        tick_from: int | None = None,
        tick_to: int | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        store = _store(run_dir)
        try:
            asked = _event_filter(kind, persona_id, world_id, tick_from, tick_to)
            events = store.view(run_id).events(asked)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            raise _missing(f"no record of run {run_id}")
        dumped = [json.loads(event.model_dump_json()) for event in events]
        return {"events": _page(dumped, offset, limit), "total": len(dumped)}

    @app.get("/api/runs/{run_id}/worlds/{world_id}/beliefs")
    def world_beliefs(request: Request, run_id: str, world_id: str, persona_id: str) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        view = _view(_store(run_dir), run_id, world_id)
        return json.loads(view.beliefs(persona_id).model_dump_json())

    @app.get("/api/runs/{run_id}/worlds/{world_id}/edges")
    def world_edges(request: Request, run_id: str, world_id: str) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        view = _view(_store(run_dir), run_id, world_id)
        return {"edges": [json.loads(edge.model_dump_json()) for edge in view.edges()]}

    @app.get("/api/runs/{run_id}/worlds/{world_id}/verbatims")
    def world_verbatims(request: Request, run_id: str, world_id: str, grouping: str = "persona") -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        view = _view(_store(run_dir), run_id, world_id)
        try:
            asked = VerbatimGrouping(grouping)
        except ValueError:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"unknown verbatim grouping {grouping!r}")
        return {
            "grouping": grouping,
            "groups": [json.loads(group.model_dump_json()) for group in view.verbatims(asked)],
        }

    @app.get("/api/runs/{run_id}/worlds/{world_id}/resolve")
    def world_resolve(
        request: Request,
        run_id: str,
        world_id: str,
        trace_id: list[str] = Query(),
    ) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        view = _view(_store(run_dir), run_id, world_id)
        try:
            resolved = view.resolve(trace_id)
        except KeyError as exc:
            raise _missing(str(exc))
        return {"events": [json.loads(event.model_dump_json()) for event in resolved]}

    @app.get("/api/runs/{run_id}/digest")
    def run_digest(request: Request, run_id: str) -> dict[str, Any]:
        return _read_json(Path(_run_dir(request, run_id), "digest.json"))

    @app.get("/api/runs/{run_id}/findings")
    def run_findings(request: Request, run_id: str) -> dict[str, Any]:
        report = _read_json(Path(_run_dir(request, run_id), "report.json"))
        return {"findings": report.get("findings", [])}

    @app.get("/api/runs/{run_id}/clusters")
    def run_clusters(request: Request, run_id: str) -> dict[str, Any]:
        report = _read_json(Path(_run_dir(request, run_id), "report.json"))
        return {"clusters": report.get("objection_clusters", [])}

    @app.get("/api/runs/{run_id}/anomalies")
    def run_anomalies(request: Request, run_id: str) -> dict[str, Any]:
        report = _read_json(Path(_run_dir(request, run_id), "report.json"))
        return {"anomalies": report.get("anomalies", [])}

    @app.get("/api/runs/{run_id}/report")
    def run_report(request: Request, run_id: str) -> dict[str, Any]:
        return _read_json(Path(_run_dir(request, run_id), "report.json"))

    @app.get("/api/runs/{run_id}/gate")
    def run_gate(request: Request, run_id: str) -> dict[str, Any]:
        return _read_json(Path(_run_dir(request, run_id), "gate-report.json"))

    @app.get("/api/runs/{run_id}/manifest")
    def run_manifest(request: Request, run_id: str) -> dict[str, Any]:
        return _read_json(Path(_run_dir(request, run_id), "manifest.json"))

    @app.get("/api/ontologies")
    def list_ontologies(request: Request) -> dict[str, Any]:
        found = []
        root = request.app.state.ontology_dir
        if root is not None:
            for category_dir in sorted(Path(root).iterdir()):
                if category_dir.is_dir():
                    for version_file in sorted(category_dir.glob("*.json")):
                        data = _read_json(version_file)
                        found.append({
                            "category": data.get("category"),
                            "version": data.get("version"),
                            "attributes": sorted((data.get("attribute_domains") or {}).keys()),
                            "conditioning_set": data.get("conditioning_set"),
                        })
        return {"ontologies": found}

    @app.get("/api/ontologies/{category}/{version}")
    def read_ontology(request: Request, category: str, version: str) -> dict[str, Any]:
        root = request.app.state.ontology_dir
        if root is None:
            raise _missing(f"no record of ontology {category}@{version}")
        return _read_json(Path(root, category, f"{version}.json"))

    @app.get("/api/briefs")
    def list_briefs(request: Request) -> dict[str, Any]:
        found = []
        root = request.app.state.briefs_dir
        if root is not None:
            import yaml

            for brief_file in sorted(Path(root).glob("*.yaml")):
                if brief_file.name.endswith(".evidence.json"):
                    continue
                try:
                    raw = yaml.safe_load(brief_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(raw, dict) and "product" in raw:
                    product = raw.get("product") or {}
                    found.append({
                        "name": brief_file.stem,
                        "product": product.get("name"),
                        "category": product.get("category"),
                        "claims": len(raw.get("claims") or []),
                        "audiences": [
                            audience.get("name")
                            for audience in (raw.get("audiences") or [])
                            if isinstance(audience, dict)
                        ],
                    })
        return {"briefs": found}

    @app.get("/api/briefs/{name}")
    def read_brief(request: Request, name: str) -> dict[str, Any]:
        root = request.app.state.briefs_dir
        if root is None:
            raise _missing(f"no record of brief {name}")
        import yaml

        try:
            raw = yaml.safe_load(Path(root, f"{name}.yaml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise _missing(f"no record of brief {name}")
        evidence = _read_json_silent(Path(root, f"{name}.yaml.evidence.json"))
        return {"name": name, "brief": raw, "evidence": evidence}

    @app.exception_handler(404)
    async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
        from fastapi import HTTPException

        detail = exc.detail if isinstance(exc, HTTPException) else "not found"  # type: ignore[attr-defined]
        return JSONResponse(status_code=404, content={"error": detail})

    return app


def _run_entry(run_dir: Path) -> dict[str, Any] | None:
    """One registry entry's story: status, spend, worlds and what was written.

    Reads the run's own `result.json`, `report.json` and `gate-report.json` —
    the artefacts the CLI wrote — and serialises their fields.
    """
    result = _read_json_silent(Path(run_dir, "result.json"))
    gate = _read_json_silent(Path(run_dir, "gate-report.json"))
    report = _read_json_silent(Path(run_dir, "report.json"))
    if result is None and gate is None:
        return None
    registry = (result or {}).get("registry", {})
    config = registry.get("config", {})
    outcomes = (result or {}).get("outcomes", [])
    trust = (report or {}).get("trust", {})
    pins = config.get("pins", {})
    return {
        "run_id": run_dir.name,
        "status": (result or {}).get("status", "partial"),
        "engine_version": registry.get("engine_version"),
        "recorded_cost": registry.get("recorded_cost", 0.0),
        "discarded_ticks": registry.get("discarded_ticks", 0),
        "config_hash": registry.get("config_hash"),
        "seeds": config.get("seeds", []),
        "budget": config.get("budget"),
        "scenarios": config.get("scenarios", []),
        "world_ids": [outcome.get("world_id") for outcome in outcomes],
        "outcomes": outcomes,
        "has_gate_report": gate is not None,
        "has_report": report is not None,
        "trust_level": (trust or {}).get("level"),
        "finding_count": len((report or {}).get("findings", [])),
        "pins": pins,
    }


def _read_json_silent(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
