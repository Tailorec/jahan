"""The HTTP surface: one path to every number, and no arithmetic on the way there.

Each of the five shapes has an endpoint returning frozen models, with a typed
filter (`EventFilter`, `VerbatimGrouping`) rather than free keyword arguments.
Run artefacts (`digest.json`, `report.json`, `trace-summary.json`) are read and
returned as written — the CLI wrote them from the same functions this module
calls live, so neither path recomputes what the other computes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from simcore.analysis import trace_summary
from simcore.runner import ENGINE_VERSION
from simcore.schemas import EventFilter, VerbatimGrouping
from simcore.trace import TraceStore

from . import _lifecycle as lifecycle

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


def _study_argv(request: Request, run_id: str, body: dict[str, Any]) -> list[str]:
    """The subprocess command a start runs: the CLI with study inputs as flags.

    Model pins travel as flags because they are study inputs, recorded and
    hashed; the key, the endpoint and the limits travel in the environment
    because they are execution configuration and never do.
    """
    import sys

    run_dir = Path(_runs_dir(request), run_id)
    seeds = body.get("seeds", "4021")
    if isinstance(seeds, list):
        seeds = ",".join(str(seed) for seed in seeds)
    argv = [
        sys.executable, "-m", "simcore.cli", "concepts", "run",
        str(Path(run_dir, "brief.yaml")),
        "--ontologies", str(request.app.state.ontology_dir or "ontologies"),
        "--anchors", str(request.app.state.anchors_dir or "anchors"),
        "--out", str(_runs_dir(request)),
        "--run-id", run_id,
        "--n", str(body.get("n", 24)),
        "--horizon", str(body.get("horizon", 2)),
        "--tick-unit", str(body.get("tick_unit", "day")),
        "--budget", str(body.get("budget", 20.0)),
        "--channel", str(body.get("channel", "survey_room")),
        "--seeds", str(seeds),
    ]
    if body.get("fake", True):
        argv.append("--fake")
    else:
        argv.extend(["--model", str(body["model"]), "--embed-model", str(body["embed_model"])])
    anchors = request.app.state.anchors_dir
    versions = body.get("anchor_versions") or _default_anchor_versions(anchors)
    for version in versions:
        argv.extend(["--anchor-version", str(version)])
    return argv


def _default_anchor_versions(anchors_dir: str | None) -> list[str]:
    """The scale a study runs on when it names none: the shipped default, if any."""
    if anchors_dir is not None:
        candidate = Path(anchors_dir, "purchase_intent", "v1.json")
        if candidate.is_file():
            return ["purchase_intent=v1"]
    return []


def create_app(
    *,
    runs_dir: str | Path,
    ontology_dir: str | Path | None = None,
    briefs_dir: str | Path | None = None,
    anchors_dir: str | Path | None = None,
    engine_root: str | Path | None = None,
    corpus_dir: str | Path | None = None,
) -> FastAPI:
    """Serve the engine's record over HTTP. Reads artefacts and views, derives nothing."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        lifecycle.sweep_orphans(app.state.runs_dir)
        yield

    app = FastAPI(title="ConsumerSim engine API", lifespan=_lifespan)
    app.state.runs_dir = str(runs_dir)
    app.state.ontology_dir = str(ontology_dir) if ontology_dir is not None else None
    app.state.briefs_dir = str(briefs_dir) if briefs_dir is not None else None
    app.state.anchors_dir = str(anchors_dir) if anchors_dir is not None else None
    app.state.engine_root = str(engine_root) if engine_root is not None else str(Path.cwd())
    app.state.corpus_dir = str(corpus_dir) if corpus_dir is not None else None

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

    @app.post("/api/runs", status_code=202)
    def start_run(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Start a study from the interface, running as a subprocess.

        The first study anyone runs is fake: no key, no corpus, no network, a
        real report in minutes. Execution configuration stays in the server's
        environment — never hashed, never rendered, never accepted here.
        """
        from simcore.cli._ids import mint_run_id

        brief_yaml = body.get("brief_yaml")
        if not isinstance(brief_yaml, str) or not brief_yaml.strip():
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="brief_yaml (string) is required")
        fake = body.get("fake", True)
        if not fake and (not body.get("model") or not body.get("embed_model")):
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="a real study pins its models: model and embed_model")
        run_id = body.get("run_id") or mint_run_id()
        run_dir = Path(_runs_dir(request), run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        Path(run_dir, "brief.yaml").write_text(brief_yaml, encoding="utf-8")
        evidence = body.get("evidence_json")
        if isinstance(evidence, dict):
            Path(run_dir, "brief.yaml.evidence.json").write_text(
                "\n".join([json.dumps(evidence, indent=2, sort_keys=True), ""]), encoding="utf-8"
            )
        argv = _study_argv(request, run_id, body)
        lifecycle.write_launch_record(run_dir, {"argv": argv, "cwd": request.app.state.engine_root})
        try:
            lifecycle.launch(run_id, argv, request.app.state.engine_root)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(exc))
        return {"run_id": run_id}

    @app.delete("/api/runs/{run_id}")
    def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
        """Stop a run, losing at most the tick in flight; the trace stays valid."""
        _run_dir(request, run_id)
        stopped = lifecycle.terminate(run_id)
        if stopped:
            lifecycle.mark_interrupted(Path(_runs_dir(request), run_id), run_id)
        entry = _run_entry(_run_dir(request, run_id))
        return {"run_id": run_id, "stopped": stopped, "status": (entry or {}).get("status")}

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(request: Request, run_id: str) -> dict[str, Any]:
        """Resume a cancelled run: a re-run with the same id, skipping finished worlds."""
        run_dir = _run_dir(request, run_id)
        record = lifecycle.launch_record(run_dir)
        if record is None or not isinstance(record.get("argv"), list):
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=f"run {run_id} was not started here and names no relaunch")
        if lifecycle.is_live(run_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=f"run {run_id} is already running")
        try:
            lifecycle.launch(run_id, list(record["argv"]), str(record.get("cwd") or request.app.state.engine_root))
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(exc))
        return {"run_id": run_id}

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

    @app.get("/api/runs/{run_id}/ontology")
    def run_ontology(request: Request, run_id: str) -> dict[str, Any]:
        return _read_json(Path(_run_dir(request, run_id), "ontology.json"))

    @app.get("/api/runs/{run_id}/personas")
    def run_personas(request: Request, run_id: str, offset: int = 0, limit: int = 6) -> dict[str, Any]:
        stored = _read_json(Path(_run_dir(request, run_id), "personas.json"))
        personas = stored.get("personas", [])
        return {
            "personas": _page(personas, offset, limit),
            "total": len(personas),
            "run_id": stored.get("run_id", run_id),
        }

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

    @app.get("/api/codebook")
    def read_codebook(
        request: Request, query: str = "", offset: int = 0, limit: int = 50,
    ) -> dict[str, Any]:
        """The corpus's own attributes with their declared value sets.

        Read from the cached corpus, never from a copy: what can be studied
        is bounded by the data. Without a corpus present there is nothing to
        bound it by, and the builder says so.
        """
        codebook = _codebook_or_refuse(request)
        lowered = query.lower()
        matched = [
            {"id": attribute, "values": list(codebook.vocabulary(attribute) or ())}
            for attribute in codebook.attributes
            if lowered in attribute.lower()
        ]
        return {"attributes": _page(matched, offset, limit), "total": len(matched)}

    @app.post("/api/ontologies/validate")
    def validate_ontology(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Check a draft against the corpus before it can become a version.

        A draft may be authored without the corpus present, but pinning one
        needs the codebook — without it the check refuses rather than guesses.
        """
        from simcore.brief import validate_against_codebook
        from simcore.schemas import CategoryOntology

        draft = body.get("ontology", body)
        try:
            ontology = CategoryOntology.model_validate(draft)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc))
        codebook = _codebook_or_refuse(request)
        try:
            validate_against_codebook(ontology, codebook)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc))
        return {"valid": True, "category": ontology.category, "version": str(ontology.version)}

    @app.post("/api/ontologies", status_code=201)
    def save_ontology(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Save a validated draft as a new version, leaving every existing one alone.

        An ontology is hashed into every identity a study mints, so an edit is
        a new version rather than a changed file: past studies keep resolving
        to what they actually ran on.
        """
        from simcore.brief import validate_against_codebook
        from simcore.schemas import CategoryOntology

        root = request.app.state.ontology_dir
        if root is None:
            raise _missing("no ontology directory is configured")
        draft = body.get("ontology", body)
        try:
            ontology = CategoryOntology.model_validate(draft)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc))
        codebook = _codebook_or_refuse(request)
        try:
            validate_against_codebook(ontology, codebook)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc))
        dest = Path(root, ontology.category, f"{ontology.version}.json")
        if dest.exists():
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail=f"{ontology.category}@{ontology.version} already exists: save as a new version",
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join([ontology.model_dump_json(indent=2), ""]), encoding="utf-8")
        return {"category": ontology.category, "version": str(ontology.version)}

    @app.exception_handler(404)
    async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
        from fastapi import HTTPException

        detail = exc.detail if isinstance(exc, HTTPException) else "not found"  # type: ignore[attr-defined]
        return JSONResponse(status_code=404, content={"error": detail})

    return app


def _codebook_or_refuse(request: Request):
    """The corpus's own codebook, or an honest refusal when no corpus is cached."""
    from simcore.ports.decoder import Codebook

    candidates = []
    if request.app.state.corpus_dir is not None:
        candidates.append(Path(request.app.state.corpus_dir, "persona_codes.schema.json"))
    try:
        from simcore.ports.hf import default_cache_dir

        candidates.append(Path(default_cache_dir(), "persona_codes.schema.json"))
    except Exception:
        pass
    for candidate in candidates:
        if candidate.is_file():
            return Codebook.from_json(candidate)
    from fastapi import HTTPException

    raise HTTPException(
        status_code=409,
        detail="no corpus is cached here, so no draft can be pinned: author freely, "
        "then validate where the corpus is present",
    )


def _run_entry(run_dir: Path) -> dict[str, Any] | None:
    """One registry entry's story: status, spend, worlds and what was written.

    Reads the run's own `result.json`, `report.json` and `gate-report.json` —
    the artefacts the CLI wrote — and serialises their fields. While a run is
    going there is no `result.json` yet, so status, recorded cost and ticks
    closed come from the registry entry and the live views instead: the entry
    is the published cache of what the trace already says.
    """
    result = _read_json_silent(Path(run_dir, "result.json"))
    gate = _read_json_silent(Path(run_dir, "gate-report.json"))
    report = _read_json_silent(Path(run_dir, "report.json"))
    if result is not None and result.get("status") == "completed":
        return _finished_entry(run_dir, result, gate, report)
    live = _live_entry(run_dir)
    if live is not None:
        return _running_entry(run_dir, live, gate, report)
    if result is None and gate is None:
        return None
    if result is not None:
        return _finished_entry(run_dir, result, gate, report)
    # A gate report with no registry entry: either a study still starting
    # (its process lives, the registry write comes after the build) or a
    # gate-only run that never proceeded. The process table tells them apart.
    starting = lifecycle.is_live(run_dir.name)
    return _finished_entry(
        run_dir,
        {"status": "running" if starting else "partial", "registry": {}, "outcomes": []},
        gate,
        report,
    )


def _is_fake(pins: dict[str, Any]) -> bool:
    """A fake run needs no key, no corpus and no network — and says so everywhere."""
    models = [
        pin.get("model_id") for pin in pins.values()
        if isinstance(pin, dict) and "model_id" in pin
    ]
    return bool(models) and all(str(model).startswith("fake/") for model in models)


def _finished_entry(run_dir: Path, result: dict[str, Any], gate: Any, report: Any) -> dict[str, Any]:
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
        "has_trace_summary": Path(run_dir, "trace-summary.json").is_file(),
        "trust_level": (trust or {}).get("level"),
        "finding_count": len((report or {}).get("findings", [])),
        "pins": pins,
        "fake": _is_fake(pins),
        "progress": [],
        "live": lifecycle.is_live(run_dir.name),
    }


def _live_entry(run_dir: Path) -> dict[str, Any] | None:
    """The registry entry of a run with no `result.json` yet, if it was recorded."""
    if not Path(run_dir, "trace").exists():
        return None
    try:
        store = _store(run_dir)
        entry = store.registry.entry(run_dir.name)
    except Exception:
        return None
    if entry is None:
        return None
    return json.loads(entry.model_dump_json())


def _running_entry(run_dir: Path, live: dict[str, Any], gate: Any, report: Any) -> dict[str, Any]:
    config = live.get("config", {})
    trust = (report or {}).get("trust", {})
    pins = config.get("pins", {})
    return {
        "run_id": run_dir.name,
        "status": live.get("status", "running"),
        "engine_version": live.get("engine_version"),
        "recorded_cost": live.get("recorded_cost", 0.0),
        "discarded_ticks": live.get("discarded_ticks", 0),
        "config_hash": live.get("config_hash"),
        "seeds": config.get("seeds", []),
        "budget": config.get("budget"),
        "scenarios": config.get("scenarios", []),
        "world_ids": list(live.get("world_ids", [])),
        "outcomes": [],
        "has_gate_report": gate is not None,
        "has_report": report is not None,
        "has_trace_summary": Path(run_dir, "trace-summary.json").is_file(),
        "trust_level": (trust or {}).get("level"),
        "finding_count": len((report or {}).get("findings", [])),
        "pins": pins,
        "fake": _is_fake(pins),
        "progress": _live_progress(run_dir, list(live.get("world_ids", []))),
        "live": lifecycle.is_live(run_dir.name),
    }


def _live_progress(run_dir: Path, world_ids: list[str]) -> list[dict[str, Any]]:
    """Ticks closing, turns landing and the rung in force, per world, from live views."""
    try:
        store = _store(run_dir)
    except Exception:
        return []
    progress = []
    for world_id in world_ids:
        try:
            view = store.view(run_dir.name, world_id)
            closed = view.events(EventFilter.model_validate({"kinds": ("tick_closed",)}))
            turns = view.events(EventFilter.model_validate({"kinds": ("turn",)}))
            degraded = view.events(EventFilter.model_validate({"kinds": ("degraded",)}))
        except Exception:
            continue
        progress.append({
            "world_id": world_id,
            "last_closed_tick": max([event.tick for event in closed], default=None),
            "turns": len(turns),
            "rungs": sorted({str(event.payload.rung) for event in degraded}),
        })
    return progress


def _read_json_silent(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
