"""The HTTP surface: one path to every number, and no arithmetic on the way there.

Each of the five shapes has an endpoint returning frozen models, with a typed
filter (`EventFilter`, `VerbatimGrouping`) rather than free keyword arguments.
Run artefacts (`digest.json`, `report.json`, `trace-summary.json`) are read and
returned as written — the CLI wrote them from the same functions this module
calls live, so neither path recomputes what the other computes.
"""

from __future__ import annotations

import json
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator, model_validator

from simcore.analysis import trace_summary, workspace_summary, world_progress
from simcore.runner import ENGINE_VERSION
from simcore.schemas import EventFilter, RunId, VerbatimGrouping
from simcore.trace import TraceStore

from . import _lifecycle as lifecycle

# An open tick range runs to the last tick ever recorded; the bound is a
# constant, not arithmetic over what is served.
_MAX_TICK = 2147483647


# A run id names a directory under the runs root and nothing else: no separators,
# no dots that climb out of it. Ids the CLI mints and ids people choose both fit.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# The names ontologies and briefs carry — the engine's own `Identifier` shape.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# The directory `validate` writes its scratch brief into is not a run.
_SCRATCH = "_validate"


def _runs_dir(request: Request) -> Path:
    return Path(request.app.state.runs_dir)


def _run_dir(request: Request, run_id: str) -> Path:
    if _RUN_ID.fullmatch(run_id) and run_id != _SCRATCH:
        candidate = Path(_runs_dir(request), run_id)
        if candidate.is_dir():
            return candidate
    raise _missing(f"no record of run {run_id}")


class _CorpusChoices(BaseModel):
    """Which corpus a draw reads from, shared by a study and by its gate so they refuse the same things.

    Both are study inputs: they decide who can be drawn, so they are recorded and hashed, and naming them
    explicitly keeps a draw reproducible where "whatever is cached" would depend on the machine it ran on.
    Neither is a path — a shard is four digits and a source is one the release documents — so nothing a
    browser sends can name a file.
    """

    shards: list[str] | None = None
    sources: list[str] | None = None

    @field_validator("shards")
    @classmethod
    def _shards_are_shard_numbers(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("name at least one shard, like ['0000', '0004'], or none to read every shard")
        for shard in value:
            if not re.fullmatch(r"\d{4}", str(shard)):
                raise ValueError(f"a shard is four digits, like 0004, not {shard!r}")
        return [str(shard) for shard in value]

    @field_validator("sources")
    @classmethod
    def _sources_are_ones_the_release_documents(cls, value: list[str] | None) -> list[str] | None:
        from simcore.schemas.persona import KNOWN_PERSONA_SOURCES

        if value is None:
            return None
        if not value:
            raise ValueError("name at least one persona source, or none to admit every source")
        unknown = sorted({name for name in value if name not in KNOWN_PERSONA_SOURCES})
        if unknown:
            raise ValueError(
                f"unknown persona source {', '.join(unknown)}; the release documents "
                f"{', '.join(sorted(KNOWN_PERSONA_SOURCES))}"
            )
        return list(value)


class StudyRequest(_CorpusChoices):
    """What a person configures to start a study — study inputs, never execution config.

    The endpoint, the key and the limits are the server's environment; a request
    that names one is refused rather than ignored, so nothing here can be mistaken
    for a way to set them from a browser. Bad numbers are refused before a process
    is started, not after it dies in its first second.
    """

    model_config = ConfigDict(extra="forbid")

    brief_yaml: str = Field(min_length=1)
    evidence_json: dict[str, Any] | None = None
    run_id: str | None = None
    fake: bool = True
    model: str | None = None
    embed_model: str | None = None
    n: int = Field(default=24, ge=1)
    horizon: int = Field(default=2, ge=1)
    tick_unit: Literal["hour", "day", "week"] = "day"
    budget: float = Field(default=20.0, gt=0)
    channel: str = "survey_room"
    seeds: str | list[int] = "4021"
    elicits: Literal["reaction", "purchase"] = "reaction"
    anchor_versions: list[str] | None = None
    # The draw's own seed, and what a real model costs — study inputs, recorded and hashed. Prices are
    # what lets the budget ladder measure spend; a chat price needs both its input and output rate.
    population_seed: int | None = Field(default=None, ge=0)
    price_chat_in: float | None = Field(default=None, ge=0)
    price_chat_out: float | None = Field(default=None, ge=0)
    price_embed_in: float | None = Field(default=None, ge=0)
    # What the report recommends a reader do to check the result against real people.
    validation: str | None = Field(default=None, max_length=2000)

    @field_validator("brief_yaml")
    @classmethod
    def _a_brief_says_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("brief_yaml (string) is required")
        return value

    @field_validator("run_id")
    @classmethod
    def _a_run_id_is_one_the_engine_recognises(cls, value: str | None) -> str | None:
        """A name a person chose must be an id the trace will accept, or the study
        dies inside its first second on a pattern the browser was never told about."""
        if value is not None:
            try:
                TypeAdapter(RunId).validate_python(value)
            except ValueError:
                raise ValueError(f"{value!r} is not a run id: `run-` and 26 characters of a ULID") from None
        return value

    @field_validator("channel")
    @classmethod
    def _a_channel_the_engine_has(cls, value: str) -> str:
        from simcore.schemas import STUDY_CHANNELS

        known = [channel.value for channel in STUDY_CHANNELS]
        if value not in known:
            raise ValueError(f"a study runs on one of {', '.join(known)}, not {value!r}")
        return value

    @field_validator("validation")
    @classmethod
    def _a_blank_validation_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def _a_chat_price_names_both_its_rates(self) -> "StudyRequest":
        if (self.price_chat_in is None) != (self.price_chat_out is None):
            raise ValueError(
                "a chat price needs both rates: price_chat_in and price_chat_out are given together or not at all"
            )
        return self

    @field_validator("seeds")
    @classmethod
    def _seeds_are_integers(cls, value: str | list[int]) -> str | list[int]:
        parts = value.split(",") if isinstance(value, str) else value
        for part in parts:
            try:
                int(str(part).strip())
            except ValueError:
                raise ValueError(f"replicate seeds are integers, not {part!r}") from None
        if not [part for part in parts if str(part).strip()]:
            raise ValueError("at least one replicate seed is required")
        return value


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: StrictBool = False


class GateRequest(_CorpusChoices):
    """A brief to gate: the draw is checked before any model is called.

    A real gate reads the real corpus, so it names the same pins and the same corpus choices the study
    it previews will — a preview drawn from anything else says nothing about the study it belongs to.
    """

    model_config = ConfigDict(extra="forbid")

    brief_yaml: str = Field(min_length=1)
    evidence_json: dict[str, Any] | None = None
    n: int = Field(default=200, ge=1)
    seed: int = Field(default=4021, ge=0)
    fake: bool = True
    model: str | None = None
    embed_model: str | None = None


def _missing(detail: str) -> Exception:
    return HTTPException(status_code=404, detail=detail)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _missing(f"no record at {path.name}")


def _store(run_dir: Path) -> TraceStore:
    """The run's trace, opened only if it has one.

    Opening a `TraceStore` creates what is missing, and a read must not write: a gate
    that refused a population never ran a study, and looking at it must not leave a
    registry behind that says otherwise.
    """
    if not Path(run_dir, "trace", "registry.db").is_file():
        raise _missing(f"run {run_dir.name} recorded no trace")
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


def _registry_model(run_dir: Path):
    """One run's registry entry as a model, or None when it holds no record."""
    from simcore.schemas import RunRegistryEntry

    stored = _read_json_silent(Path(run_dir, "result.json"))
    registry = (stored or {}).get("registry")
    if registry is None:
        registry = _live_entry(run_dir)
    if not isinstance(registry, dict):
        return None
    try:
        return RunRegistryEntry.model_validate(registry)
    except ValueError:
        return None


def _persona_named(personas: list[Any], persona_id: str):
    """One persona's own record, validated — reconstruction renders from records."""
    from simcore.schemas import Persona

    for record in personas:
        if isinstance(record, dict) and record.get("persona_id") == persona_id:
            try:
                return Persona.model_validate(record)
            except ValueError:
                return None
    return None


def _ontology_named(raw: Any):
    """The run's own ontology version, validated — or nothing to render against."""
    if not isinstance(raw, dict):
        return None
    from simcore.schemas import CategoryOntology

    try:
        return CategoryOntology.model_validate(raw)
    except ValueError:
        return None


def _stimulus_texts(view) -> dict[str, str]:
    """What each stimulus said, from the stimuli the record published."""
    texts = {}
    for event in view.events(EventFilter.model_validate({"kinds": ("stimulus_published",)})):
        texts[event.payload.stimulus.stimulus_id] = event.payload.stimulus.text
    return texts


def _page(items: list[Any], offset: int, limit: int) -> list[Any]:
    """One page of an ordered shape. Slicing, never arithmetic over what is served."""
    return items[offset:][:limit]


def _validate_brief(brief_path: Path, ontology_dir: str | None) -> None:
    """Load a brief the way the CLI will: unknown keys, unvalidated claims and
    a version that resolves nowhere are refused here, before anything is spent."""
    _load_pack(brief_path, ontology_dir)


def _load_pack(brief_path: Path, ontology_dir: str | None):
    """A brief pack or a plain ValueError: engine refusals become 422s at this boundary."""
    from simcore.brief import load_brief
    from simcore.schemas.errors import SimError

    try:
        return load_brief(brief_path, Path(ontology_dir))
    except SimError as exc:
        # A refusal names the file that was wrong, never where it lives.
        raise ValueError(str(exc).replace(str(brief_path), "brief.yaml").replace(str(ontology_dir), "ontologies"))


def _study_argv(request: Request, run_id: str, body: StudyRequest) -> list[str]:
    """The subprocess command a start runs: the CLI with study inputs as flags.

    Model pins travel as flags because they are study inputs, recorded and
    hashed; the key, the endpoint and the limits travel in the environment
    because they are execution configuration and never do.
    """
    import sys

    run_dir = Path(_runs_dir(request), run_id)
    seeds = body.seeds
    if isinstance(seeds, list):
        seeds = ",".join(str(seed) for seed in seeds)
    argv = [
        sys.executable, "-m", "simcore.cli", "concepts", "run",
        str(Path(run_dir, "brief.yaml")),
        "--ontologies", _ontologies_root(request),
        "--anchors", _anchors_root(request),
        "--out", str(_runs_dir(request)),
        "--run-id", run_id,
        "--n", str(body.n),
        "--horizon", str(body.horizon),
        "--tick-unit", body.tick_unit,
        "--budget", str(body.budget),
        "--channel", body.channel,
        "--seeds", str(seeds),
        "--elicits", body.elicits,
    ]
    if body.fake:
        argv.append("--fake")
    else:
        argv.extend(["--model", str(body.model), "--embed-model", str(body.embed_model)])
    versions = body.anchor_versions or _default_anchor_versions(_anchors_root(request))
    for version in versions:
        argv.extend(["--anchor-version", str(version)])
    argv.extend(_corpus_flags(body))
    # Only what was named travels: a study that names none of these runs exactly as it always did.
    for flag, value in (
        ("--population-seed", body.population_seed),
        ("--price-chat-in", body.price_chat_in),
        ("--price-chat-out", body.price_chat_out),
        ("--price-embed-in", body.price_embed_in),
        ("--validation", body.validation),
    ):
        if value is not None:
            argv.extend([flag, str(value)])
    return argv


def _corpus_flags(body: _CorpusChoices) -> list[str]:
    """`--shards` and `--sources`, when the study names them — the same flags the command line takes."""
    flags: list[str] = []
    if body.shards is not None:
        flags.extend(["--shards", ",".join(body.shards)])
    if body.sources is not None:
        flags.extend(["--sources", ",".join(body.sources)])
    return flags


def _ontologies_root(request: Request) -> str:
    """The ontologies a study resolves against: the configured directory, else the checkout's."""
    return request.app.state.ontology_dir or str(Path(request.app.state.engine_root, "ontologies"))


def _anchors_root(request: Request) -> str:
    return request.app.state.anchors_dir or str(Path(request.app.state.engine_root, "anchors"))


def _anchor_catalogue(anchors_dir: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Every frozen anchor version with its verdict, and the scale a study should default to.

    A version is a default only if its check passed and its file still hashes to what was checked: a
    changed statement is a new version, never an edit (ADR 0027). It used to default to `purchase_intent`
    `v1` outright, which fails its own check, so a study that named no version silently scored nothing.
    Verdicts are read from the check records beside the files; nothing here scores anything or names a path.
    """
    from simcore.elicitation import anchor_hash, load_anchor_version, read_check_record

    if anchors_dir is None or not Path(anchors_dir).is_dir():
        return [], []

    def order(version: str) -> tuple[int, str]:
        digits = re.sub(r"\D", "", version)
        return (int(digits) if digits else -1, version)

    listed: list[dict[str, Any]] = []
    defaults: list[str] = []
    for construct_dir in sorted(child for child in Path(anchors_dir).iterdir() if child.is_dir()):
        construct = construct_dir.name
        versions = sorted(
            (path.stem for path in construct_dir.glob("*.json") if not path.name.endswith(".check.json")),
            key=order,
        )
        usable: list[str] = []
        for version in versions:
            try:
                record = read_check_record(anchors_dir, construct, version)
            except Exception:
                record = None
            unchanged = None
            if record is not None:
                try:
                    unchanged = anchor_hash(load_anchor_version(Path(construct_dir, f"{version}.json"))) == record.anchor_hash
                except Exception:
                    unchanged = False
            passed = bool(record is not None and record.passed)
            listed.append({
                "construct": construct,
                "version": version,
                "anchor_set_id": record.anchor_set_id if record is not None else None,
                "embed_model_id": record.embed_model_id if record is not None else None,
                "checked": record is not None,
                "passed": passed,
                "unchanged_since_check": unchanged,
                "detail": record.detail if record is not None else "no check has been run on this version",
            })
            if passed and unchanged:
                usable.append(version)
        if usable:
            defaults.append(f"{construct}={usable[-1]}")
    return listed, defaults


def _default_anchor_versions(anchors_dir: str | None) -> list[str]:
    """The scale a study runs on when it names none: the newest version that passed its check."""
    return _anchor_catalogue(anchors_dir)[1]


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
    # A first start has no runs yet; the listing is empty, not an error.
    Path(runs_dir).mkdir(parents=True, exist_ok=True)
    app.state.runs_dir = str(runs_dir)
    app.state.ontology_dir = str(ontology_dir) if ontology_dir is not None else None
    app.state.briefs_dir = str(briefs_dir) if briefs_dir is not None else None
    app.state.anchors_dir = str(anchors_dir) if anchors_dir is not None else None
    app.state.engine_root = str(engine_root) if engine_root is not None else str(Path.cwd())
    app.state.corpus_dir = str(corpus_dir) if corpus_dir is not None else None
    app.state.coverage_lock = threading.Lock()
    app.state.coverage_job = {"thread": None, "error": None}
    app.state.matrix_lock = threading.Lock()
    app.state.matrix_job = {"thread": None, "error": None}
    app.state.embeddings_lock = threading.Lock()
    app.state.embeddings_job = {"thread": None, "error": None}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine_version": ENGINE_VERSION}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        """How a study may run: whether an endpoint is configured, never its key.

        Execution configuration stays in the server's environment — the setup
        screen reports whether an endpoint is configured and never asks for,
        accepts or displays a key in a browser.
        """
        return {
            "engine_version": ENGINE_VERSION,
            "endpoint_configured": _endpoint_configured(),
            "fake_available": True,
        }

    @app.get("/api/trust")
    def trust() -> dict[str, Any]:
        """The ladder a run's calibration sits on, and what a rung above the first requires.

        The levels and the floors are the engine's own constants, served so that the
        trust page states the same numbers the schema enforces rather than a copy of
        them. Nothing here can be set: a level above `uncalibrated` is earned by a
        `CalibrationRef` the engine validates, never chosen.
        """
        from simcore.schemas import MIN_DISTRIBUTION_SIMILARITY, MIN_RANK_ATTAINMENT, TrustLevel

        return {
            "levels": [level.value for level in TrustLevel],
            "floors": {
                "distribution_similarity": MIN_DISTRIBUTION_SIMILARITY,
                "rank_attainment": MIN_RANK_ATTAINMENT,
            },
        }

    @app.get("/api/anchors-checks")
    def anchors_checks(request: Request) -> dict[str, Any]:
        """Anchor checks a run wrote, oldest first: the mapping claim, never the simulation claim."""
        checks = []
        for child in sorted(_runs_dir(request).iterdir()):
            if child.is_dir() and child.name != _SCRATCH:
                stored = _read_json_silent(Path(child, "anchors-check.json"))
                if isinstance(stored, dict):
                    checks.append(stored)
        return {"checks": checks}

    @app.post("/api/briefs/validate")
    def validate_brief(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Author and validate a brief against the engine's own contracts.

        Returns the assumption ledger the brief assembles — what it states,
        what its claims assume, and what it leaves unstated — before a run
        can start.
        """
        from simcore.brief import assumptions_of

        brief_yaml = body.get("brief_yaml")
        if not isinstance(brief_yaml, str) or not brief_yaml.strip():
            raise HTTPException(status_code=422, detail="brief_yaml (string) is required")
        tmp = Path(_runs_dir(request), _SCRATCH)
        tmp.mkdir(parents=True, exist_ok=True)
        candidate = Path(tmp, "brief.yaml")
        candidate.write_text(brief_yaml, encoding="utf-8")
        evidence = body.get("evidence_json")
        sidecar = Path(tmp, "brief.yaml.evidence.json")
        if isinstance(evidence, dict):
            sidecar.write_text("\n".join([json.dumps(evidence, indent=2, sort_keys=True), ""]), encoding="utf-8")
        elif sidecar.exists():
            sidecar.unlink()
        try:
            pack = _load_pack(candidate, _ontologies_root(request))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        ledger = assumptions_of(pack)
        return {
            "valid": True,
            "product": pack.brief.product.name,
            "category": pack.brief.product.category,
            "ontology_version": pack.brief.ontology_version,
            "claims": [claim.id for claim in pack.brief.claims],
            "audiences": [audience.name for audience in pack.brief.audiences],
            "assumption_ledger": [
                {"text": item.text, "source": item.source.value} for item in ledger
            ],
        }

    @app.get("/api/runs")
    def list_runs(request: Request) -> dict[str, Any]:
        runs = []
        for child in sorted(_runs_dir(request).iterdir()):
            if child.is_dir() and child.name != _SCRATCH:
                entry = _run_entry(child, request)
                if entry is not None:
                    runs.append(entry)
        return {"runs": runs}

    @app.get("/api/workspace")
    def workspace(request: Request) -> dict[str, Any]:
        """The workspace summary: derived in `analysis` over registry entries.

        Studies run, spend against budget, personas simulated, reports written —
        read from entries rather than by walking partitions, so the interface
        displays no number without the shape that produced it. Which runs have
        written a report is a fact of the run directory, named to `analysis`
        rather than counted here.
        """
        runs_root = _runs_dir(request)
        children = [child for child in sorted(runs_root.iterdir()) if child.is_dir() and child.name != _SCRATCH]
        entries = [entry for entry in (_registry_model(child) for child in children) if entry is not None]
        wrote_report = {child.name for child in children if Path(child, "report.json").is_file()}
        return json.loads(workspace_summary(entries, report_run_ids=wrote_report).model_dump_json())

    @app.get("/api/runs/{run_id}")
    def run_detail(request: Request, run_id: str) -> dict[str, Any]:
        entry = _run_entry(_run_dir(request, run_id), request)
        if entry is None:
            raise _missing(f"no record of run {run_id}")
        return entry

    @app.post("/api/runs", status_code=202)
    def start_run(request: Request, body: StudyRequest) -> dict[str, Any]:
        """Start a study from the interface, running as a subprocess.

        The first study anyone runs is fake: no key, no corpus, no network, a
        real report in minutes. A real study pins its models here — they are
        study inputs, recorded and hashed — while the endpoint and the key stay
        in the server's environment: never hashed, never rendered, never accepted.
        """
        from simcore.cli._ids import mint_run_id

        if not body.fake and (not body.model or not body.embed_model):
            raise HTTPException(status_code=422, detail="a real study pins its models: model and embed_model")
        if not body.fake and not _endpoint_configured():
            raise HTTPException(
                status_code=409,
                detail="no inference endpoint is configured in the server's environment: "
                "run a fake study, or set SIMCORE_INFERENCE_BASE_URL where the server starts",
            )
        run_id = body.run_id or mint_run_id()
        run_dir = Path(_runs_dir(request), run_id)
        if run_dir.is_dir():
            lifecycle.adopt(run_dir)
        if lifecycle.is_live(run_id):
            raise HTTPException(status_code=409, detail=f"run {run_id} is already running")
        run_dir.mkdir(parents=True, exist_ok=True)
        # A brief is validated against the engine's own contracts before a run
        # can start — not after it fails halfway through its first draw. The
        # brief only lands in the run's directory once it is known to be sound.
        candidate = Path(run_dir, "brief.yaml")
        candidate.write_text(body.brief_yaml, encoding="utf-8")
        sidecar = Path(run_dir, "brief.yaml.evidence.json")
        if body.evidence_json is not None:
            sidecar.write_text(
                "\n".join([json.dumps(body.evidence_json, indent=2, sort_keys=True), ""]), encoding="utf-8"
            )
        try:
            _validate_brief(candidate, _ontologies_root(request))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        argv = _study_argv(request, run_id, body)
        lifecycle.write_launch_record(run_dir, {"argv": argv, "cwd": request.app.state.engine_root})
        try:
            lifecycle.launch(run_id, argv, request.app.state.engine_root, run_dir=run_dir)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"run_id": run_id}

    @app.post("/api/gate")
    def gate_brief(request: Request, body: GateRequest) -> dict[str, Any]:
        """Draw and gate a population for a brief, before any study is paid for.

        Runs the engine's own `coreset-gate` and serves the artefacts it wrote.
        A failing draw is the case the population page most needs to explain, so
        it answers with its gate report rather than with an error.
        """
        return _run_gate(request, body)

    @app.delete("/api/runs/{run_id}")
    def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
        """Stop a run, losing at most the tick in flight; the trace stays valid."""
        lifecycle.adopt(_run_dir(request, run_id))
        stopped = lifecycle.terminate(run_id)
        if stopped:
            lifecycle.mark_interrupted(Path(_runs_dir(request), run_id), run_id)
        entry = _run_entry(_run_dir(request, run_id), request)
        return {"run_id": run_id, "stopped": stopped, "status": (entry or {}).get("status")}

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(request: Request, run_id: str, body: ResumeRequest | None = None) -> dict[str, Any]:
        """Resume a cancelled run: a re-run with the same id, skipping finished worlds.

        The engine refuses a resume whose inputs moved since the run began. `force` goes past that once, on
        purpose: the run records what it was forced past, and the recorded launch is left as it was, so the
        next resume is not forced by habit.
        """
        run_dir = _run_dir(request, run_id)
        record = lifecycle.launch_record(run_dir)
        if record is None or not isinstance(record.get("argv"), list):
            raise HTTPException(status_code=409, detail=f"run {run_id} was not started here and names no relaunch")
        lifecycle.adopt(run_dir)
        if lifecycle.is_live(run_id):
            raise HTTPException(status_code=409, detail=f"run {run_id} is already running")
        try:
            argv = list(record["argv"])
            if body is not None and body.force and "--force" not in argv:
                argv.append("--force")
            lifecycle.launch(run_id, argv, str(record.get("cwd") or request.app.state.engine_root), run_dir=run_dir)
        except ValueError as exc:
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
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=100_000),
    ) -> dict[str, Any]:
        run_dir = _run_dir(request, run_id)
        store = _store(run_dir)
        try:
            asked = _event_filter(kind, persona_id, world_id, tick_from, tick_to)
            events = store.view(run_id).events(asked)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            raise _missing(f"no record of run {run_id}")
        dumped = [json.loads(event.model_dump_json()) for event in events]
        return {"events": _page(dumped, offset, limit), "total": len(dumped)}

    @app.get("/api/runs/{run_id}/resolve")
    def run_resolve(request: Request, run_id: str, trace_id: list[str] = Query()) -> dict[str, Any]:
        """Exactly the events named, wherever in the run they were recorded.

        A finding's evidence is drawn from the replicates of a scenario, so the ids
        it cites live in different worlds; a world's own `resolve` refuses ids that
        belong to a sibling. Absent ids still refuse — nothing is guessed.
        """
        view = _view(_store(_run_dir(request, run_id)), run_id, None)
        try:
            resolved = view.resolve(trace_id)
        except KeyError as exc:
            raise _missing(str(exc))
        return {"events": [json.loads(event.model_dump_json()) for event in resolved]}

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

    @app.get("/api/runs/{run_id}/worlds/{world_id}/turns/{event_id}/prompt")
    def turn_prompt(request: Request, run_id: str, world_id: str, event_id: str) -> dict[str, Any]:
        """One turn's prompt, reconstructed from the record and verified.

        Displays the messages only when their hash matches the turn's recorded
        hash; anything else says so and why. Prompts are served transiently —
        nothing here writes one anywhere.
        """
        from simcore.agent import Unreconstructible, reconstruct_turn

        run_dir = _run_dir(request, run_id)
        view = _view(_store(run_dir), run_id, world_id)
        try:
            resolved = view.resolve([event_id])
        except KeyError as exc:
            raise _missing(str(exc))
        event = resolved[0]
        if event.payload.kind != "turn" or event.persona_id is None:
            raise HTTPException(status_code=422, detail=f"{event_id} is not a turn")
        stored = _read_json_silent(Path(run_dir, "personas.json"))
        persona = _persona_named((stored or {}).get("personas", []), event.persona_id)
        if persona is None:
            raise HTTPException(
                status_code=422,
                detail="the turn's persona has no record in personas.json",
            )
        ontology = _ontology_named(_read_json_silent(Path(run_dir, "ontology.json")))
        persona_events = view.events(EventFilter.model_validate({"persona_ids": (event.persona_id,)}))
        texts = _stimulus_texts(view)
        rebuilt = reconstruct_turn(
            event.payload, event, persona=persona, ontology=ontology,
            persona_events=persona_events, stimulus_texts=texts,
        )
        if isinstance(rebuilt, Unreconstructible):
            raise HTTPException(status_code=422, detail=rebuilt.reason)
        return {
            "event_id": event_id,
            "shape": rebuilt.shape,
            "messages": [dict(message) for message in rebuilt.messages],
            "rejected_verified": rebuilt.rejected_verified,
        }

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
    def run_personas(
        request: Request,
        run_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=6, ge=1, le=1000),
    ) -> dict[str, Any]:
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
        if root is None or not _NAME.fullmatch(category) or not _NAME.fullmatch(version):
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
        if root is None or not _NAME.fullmatch(name):
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
        request: Request,
        query: str = "",
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=1000),
        mode: str = "words",
        sources: str = "",
        required: str = "",
    ) -> dict[str, Any]:
        """The corpus's own attributes in words people use: label, category,
        what each measures, how well each matches, how many people answered it
        and from which sources, and what requiring it would do to the pool.

        `mode=meaning` ranks by meaning with near-empty attributes sunk; until
        embeddings exist — and without an endpoint — search is by words, and
        the answer says so. Nothing here is a path.
        """
        from simcore.population import search_attributes
        from simcore.ports.embeddings import (
            build_embeddings as _build_embeddings,
        )
        from simcore.ports.embeddings import (
            codebook_digest,
            embed_model,
            load_embeddings,
        )
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        codebook = _codebook_or_refuse(request)
        corpus = _corpus_root(request)
        source = HfCoresetSource(cache_dir=corpus)
        matrix = load_matrix(source)
        if matrix is None:
            return {
                "attributes": [],
                "total": 0,
                "mode": "words",
                "meaning_available": False,
                "meaning_note": "counting who can be drawn — search returns once the matrix exists",
            }
        chosen = tuple(name for name in sources.split(",") if name) or matrix.sources
        needed = tuple(name for name in required.split(",") if name)
        model = embed_model()
        digest = codebook_digest(corpus)
        embeddings = load_embeddings(corpus, digest, model)
        if embeddings is None:
            with request.app.state.embeddings_lock:
                job = request.app.state.embeddings_job
                alive = job["thread"] is not None and job["thread"].is_alive()
                if not alive and job["error"] is None:
                    job["thread"] = threading.Thread(
                        target=_build_embeddings_job,
                        args=(request.app.state, str(corpus)),
                        name="attribute-embeddings",
                        daemon=True,
                    )
                    job["thread"].start()
        found = search_attributes(codebook, matrix, query, chosen, needed, mode, embeddings)
        entries = found["results"]
        meaning_note = "search by meaning is unavailable without an endpoint and embeddings — searching by words"
        if embeddings is not None:
            meaning_note = ""
        if embeddings is None and request.app.state.embeddings_job["error"] is None:
            meaning_note = "search by meaning is building — searching by words until it lands"
        return {
            "attributes": _page(entries, offset, limit),
            "total": len(entries),
            "mode": found["mode"],
            "meaning_available": embeddings is not None,
            "meaning_note": meaning_note,
        }

    @app.get("/api/corpus")
    def read_corpus(request: Request) -> dict[str, Any]:
        """What the corpus offers a study: which shards are cached, which sources exist.

        A study names the shards it draws from and the sources it admits, so the interface offers exactly
        what is there. A shard is its four-digit number and a source is its name; nothing here is a path.
        No corpus is a statement, not an error: the fake study needs none.
        """
        corpus = _corpus_root(request)
        if corpus is None:
            return {"available": False, "shards": [], "sources": {}, "measured_sources": []}
        manifest = _read_json_silent(Path(corpus, "manifest.json")) or {}
        cached = {path.name for path in Path(corpus, "data").glob("persona-1m-*.parquet")} if Path(corpus, "data").is_dir() else set()
        shards = []
        for entry in manifest.get("files", []):
            name = Path(str(entry.get("path", ""))).name
            match = re.fullmatch(r"persona-1m-(\d{4})\.parquet", name)
            if match:
                shards.append({
                    "id": match.group(1), "rows": entry.get("rows"), "bytes": entry.get("bytes"),
                    "cached": name in cached,
                })
        sources = {str(name): count for name, count in (manifest.get("sources") or {}).items()}
        return {
            "available": True,
            "shards": sorted(shards, key=lambda shard: shard["id"]),
            "sources": sources,
            # A persona may not have synthesized demographics, so a draw that reaches synthetic rows is
            # refused after it is built: the measured sources are the ones a study can actually admit.
            "measured_sources": sorted(name for name in sources if name != "synthetic"),
        }

    @app.get("/api/corpus/coverage")
    def read_corpus_coverage(request: Request, retry: bool = False) -> dict[str, Any]:
        """How populated each attribute is, per source, in the shards this machine holds.

        The count is made once, in the background, and saved beside the release; until it exists the
        answer is `building`, and the ontology builder shows it as it lands. Which attribute an audience
        is defined by decides whether a study can be drawn at all, and the codebook alone cannot say.
        """
        corpus = _corpus_root(request)
        if corpus is None:
            return {"available": False, "state": "no_corpus"}
        return _coverage(request.app.state, corpus, retry)

    @app.get("/api/anchors")
    def read_anchors(request: Request) -> dict[str, Any]:
        """Every frozen anchor version with its verdict, and the scale a study defaults to.

        A version that failed its check is listed and marked, never hidden: which scale a study runs on
        is a study input, and a person choosing one should see what its check found.
        """
        listed, defaults = _anchor_catalogue(_anchors_root(request))
        return {"anchors": listed, "defaults": defaults}

    @app.post("/api/ontologies/validate")
    def validate_ontology(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Check a draft against the corpus before it can become a version.

        A draft may be authored without the corpus present, but pinning one
        needs the codebook — without it the check refuses rather than guesses.
        """
        from simcore.brief._codebook import validate_against_codebook
        from simcore.schemas import CategoryOntology

        draft = body.get("ontology", body)
        try:
            ontology = CategoryOntology.model_validate(draft)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        codebook = _codebook_or_refuse(request)
        try:
            validate_against_codebook(ontology, codebook)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"valid": True, "category": ontology.category, "version": str(ontology.version)}

    @app.post("/api/ontologies", status_code=201)
    def save_ontology(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Save a validated draft as a new version, leaving every existing one alone.

        An ontology is hashed into every identity a study mints, so an edit is
        a new version rather than a changed file: past studies keep resolving
        to what they actually ran on.
        """
        from simcore.brief._codebook import validate_against_codebook
        from simcore.schemas import CategoryOntology

        root = request.app.state.ontology_dir
        if root is None:
            raise _missing("no ontology directory is configured")
        draft = body.get("ontology", body)
        try:
            ontology = CategoryOntology.model_validate(draft)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        codebook = _codebook_or_refuse(request)
        try:
            validate_against_codebook(ontology, codebook)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        dest = Path(root, ontology.category, f"{ontology.version}.json")
        if dest.exists():
            raise HTTPException(
                status_code=409,
                detail=f"{ontology.category}@{ontology.version} already exists: save as a new version",
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join([ontology.model_dump_json(indent=2), ""]), encoding="utf-8")
        return {"category": ontology.category, "version": str(ontology.version)}

    @app.post("/api/pool")
    def read_pool(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """The candidate pool: everyone in the chosen sources who carries every
        required attribute, and what each requirement removes — including when
        it removes a whole survey, named.

        Counting lives in the engine over the persona value matrix; this
        serialises it. A cold start builds the matrix in the background and
        answers `building` until it exists.
        """
        from simcore.population import describe_pool
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import build_matrix, load_matrix

        corpus = _corpus_root(request)
        if corpus is None:
            raise HTTPException(status_code=409, detail="no corpus is cached here, so there is nobody to count")
        wanted = body.get("sources")
        required = body.get("required") or []
        if wanted is not None and not isinstance(wanted, list):
            raise HTTPException(status_code=422, detail="sources names persona sources, like [\"gss\"]")
        if not isinstance(required, list):
            raise HTTPException(status_code=422, detail="required names attributes, like [\"age_bracket\"]")
        try:
            source = HfCoresetSource(cache_dir=corpus)
            matrix = load_matrix(source)
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            with request.app.state.matrix_lock:
                job = request.app.state.matrix_job
                alive = job["thread"] is not None and job["thread"].is_alive()
                if not alive:
                    if job["error"] is not None and body.get("retry"):
                        job["error"] = None
                    if job["error"] is None:
                        job["thread"] = threading.Thread(
                            target=_build_matrix_job,
                            args=(request.app.state, str(corpus)),
                            name="persona-matrix",
                            daemon=True,
                        )
                        job["thread"].start()
                error = job["error"]
            if error is not None and not body.get("retry"):
                raise HTTPException(status_code=409, detail=error)
            return {"state": "building"}
        try:
            pool = describe_pool(matrix, tuple(wanted) if wanted is not None else matrix.sources, tuple(str(name) for name in required))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        outcome = pool.to_json()
        outcome["state"] = "ready"
        return outcome

    @app.get("/api/codebook/{attribute}/values")
    def read_attribute_values(request: Request, attribute: str, sources: str = "", required: str = "") -> dict[str, Any]:
        """Every value of `attribute` with its count per source among the
        candidate pool — the value picker ticks these, never typed. Beneath it,
        "the corpus also asks this as" lists the other ways the corpus asks the
        same question with how many people answered each."""
        from simcore.population import alternatives, value_counts
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        if not _NAME.fullmatch(attribute):
            raise _missing(f"no record of attribute {attribute}")
        corpus = _corpus_root(request)
        if corpus is None:
            raise HTTPException(status_code=409, detail="no corpus is cached here, so there is nobody to count")
        try:
            source = HfCoresetSource(cache_dir=corpus)
            matrix = load_matrix(source)
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            return {"state": "building"}
        chosen = tuple(name for name in sources.split(",") if name) or matrix.sources
        needed = tuple(name for name in required.split(",") if name)
        codebook = _codebook_or_refuse(request)
        try:
            counts = value_counts(matrix, chosen, needed, attribute)
            other = alternatives(matrix, codebook, chosen, attribute)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"state": "ready", "id": attribute, "label": codebook.label(attribute), "values": counts, "also_asks": other}

    @app.get("/api/categories")
    def list_categories_route(request: Request) -> dict[str, Any]:
        """The existing categories a description may reuse — offered only when
        the codebook carries every attribute the category's latest ontology names."""
        from simcore.population import list_categories

        codebook = _codebook_or_refuse(request)
        return {"categories": list_categories(_ontologies_root(request), request.app.state.briefs_dir, codebook)}

    @app.post("/api/describe")
    def describe_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Read the description into groups, shared traits and topics, and say
        which category it seems to belong to. The reading is shown before any
        draft; nothing is drafted here."""
        from simcore.population import describe

        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="describe who you want to study")
        codebook = _codebook_or_refuse(request)
        try:
            return describe(_chat_json, text.strip(), _ontologies_root(request), request.app.state.briefs_dir, codebook)
        except Exception as failure:
            raise HTTPException(
                status_code=409,
                detail=f"the language model could not be reached ({type(failure).__name__}); drafting is unavailable",
            )

    @app.post("/api/draft")
    def draft_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """A confirmed category and a reading become audiences and an ontology
        draft. Each trait is matched among 20 candidates with counts in view;
        an attribute never offered, or a value outside its list, is refused."""
        from simcore.population import Reading, draft
        from simcore.ports.embeddings import codebook_digest, embed_model, load_embeddings
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        text = body.get("text") or ""
        reading_raw = body.get("reading") or {}
        category = body.get("category") or {}
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="describe who you want to study first")
        if not isinstance(category, dict) or category.get("id") is None:
            raise HTTPException(status_code=422, detail="confirm the category before anything is drafted")
        codebook = _codebook_or_refuse(request)
        corpus = _corpus_root(request)
        try:
            matrix = load_matrix(HfCoresetSource(cache_dir=corpus))
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            return {"state": "building"}
        embeddings = load_embeddings(corpus, codebook_digest(corpus), embed_model())
        if embeddings is None:
            raise HTTPException(
                status_code=409,
                detail="drafting is unavailable until search by meaning lands — it is building",
            )
        try:
            reading = _reading_of(reading_raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        def lookup(category_id: str):
            return _latest_ontology(_ontologies_root(request), category_id)

        wanted = body.get("sources")
        try:
            drafted = draft(
                _chat_json, text.strip(), reading, category,
                tuple(wanted) if wanted is not None else matrix.sources,
                matrix, codebook, embeddings, lookup,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as failure:
            raise HTTPException(
                status_code=409,
                detail=f"the language model could not be reached ({type(failure).__name__}); drafting is unavailable",
            )
        outcome = drafted.to_json()
        outcome["state"] = "ready"
        return outcome

    @app.post("/api/draft/fit")
    def fit_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Fit drafted audiences to their quotas in the open: each move of a
        costliest filter to a description is flagged with its counts for the
        person to accept or undo."""
        from simcore.population import fit_to_quotas
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        corpus = _corpus_root(request)
        if corpus is None:
            raise HTTPException(status_code=409, detail="no corpus is cached here, so there is nobody to count")
        try:
            matrix = load_matrix(HfCoresetSource(cache_dir=corpus))
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            return {"state": "building"}
        wanted = body.get("sources")
        required = body.get("required") or []
        audiences = body.get("audiences") or []
        study_size = body.get("study_size") or 200
        if not isinstance(study_size, int) or isinstance(study_size, bool):
            raise HTTPException(status_code=422, detail="study_size counts personas, like 200")
        try:
            fitted = fit_to_quotas(
                matrix,
                tuple(wanted) if wanted is not None else matrix.sources,
                tuple(str(name) for name in required),
                audiences,
                study_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"state": "ready", "audiences": fitted}

    @app.post("/api/draft/followup")
    def followup_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """A follow-up in the same box: naming a group adds it, naming none
        refines every existing audience. Never changes the category."""
        from simcore.population import apply_followup
        from simcore.ports.embeddings import codebook_digest, embed_model, load_embeddings
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        text = body.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="say what to add or change")
        codebook = _codebook_or_refuse(request)
        corpus = _corpus_root(request)
        try:
            matrix = load_matrix(HfCoresetSource(cache_dir=corpus))
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            return {"state": "building"}
        embeddings = load_embeddings(corpus, codebook_digest(corpus), embed_model())
        if embeddings is None:
            raise HTTPException(
                status_code=409,
                detail="follow-ups are unavailable until search by meaning lands — it is building",
            )
        audiences = body.get("audiences") or []
        wanted = body.get("sources")
        try:
            out = apply_followup(
                _chat_json, text.strip(), audiences,
                tuple(wanted) if wanted is not None else matrix.sources,
                matrix, codebook, embeddings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as failure:
            raise HTTPException(
                status_code=409,
                detail=f"the language model could not be reached ({type(failure).__name__})",
            )
        out["state"] = "ready"
        return out

    @app.post("/api/who/blockers")
    def blockers_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Exactly what still stands in the way of Continue, derived by the engine."""
        from simcore.population import continue_blockers

        return {"blockers": continue_blockers(
            body.get("category"),
            body.get("questions") or [],
            body.get("changes") or [],
            body.get("audiences") or [],
            body.get("previews") or [],
        )}

    @app.post("/api/audiences/preview")
    def preview_audiences_route(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Each audience's head count against its quota at the study size, its
        source mix, and what each filter costs. Counted by the engine over the
        persona value matrix; this serialises it."""
        from simcore.population import preview_audiences
        from simcore.ports.hf import HfCoresetSource
        from simcore.ports.matrix import load_matrix

        corpus = _corpus_root(request)
        if corpus is None:
            raise HTTPException(status_code=409, detail="no corpus is cached here, so there is nobody to count")
        try:
            source = HfCoresetSource(cache_dir=corpus)
            matrix = load_matrix(source)
        except Exception as failure:
            raise HTTPException(status_code=409, detail=_pool_failure(failure))
        if matrix is None:
            return {"state": "building"}
        wanted = body.get("sources")
        required = body.get("required") or []
        audiences = body.get("audiences") or []
        study_size = body.get("study_size") or 200
        if not isinstance(study_size, int) or isinstance(study_size, bool):
            raise HTTPException(status_code=422, detail="study_size counts personas, like 200")
        try:
            counts = preview_audiences(
                matrix,
                tuple(wanted) if wanted is not None else matrix.sources,
                tuple(str(name) for name in required),
                audiences,
                study_size,
            )
            ledger = assumption_entries(
                matrix,
                tuple(wanted) if wanted is not None else matrix.sources,
                tuple(str(name) for name in required),
                audiences,
                counts,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"state": "ready", "audiences": [count.to_json() for count in counts], "assumptions": ledger}

    @app.exception_handler(RequestValidationError)
    async def _refused(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """One refusal shape: `detail` is always a sentence a person can read.

        A request the engine's own contracts turn away says which field and why,
        in the same key a 404 or a 409 uses, rather than a list a browser must
        take apart.
        """
        lines = []
        for problem in exc.errors():
            where = ".".join(str(part) for part in problem["loc"][1:])
            lines.append(f"{where}: {problem['msg']}" if where else str(problem["msg"]))
        return JSONResponse(status_code=422, content={"detail": "\n".join(lines)})

    return app


def _coverage(state: Any, corpus: Path, retry: bool) -> dict[str, Any]:
    """The saved coverage count for the cached shards, or the state of the job making it."""
    from simcore.ports.coverage import coverage_table, count_coverage, load_coverage
    from simcore.ports.hf import HfCoresetSource

    data = Path(corpus, "data")
    paths = [f"data/{path.name}" for path in sorted(data.glob("persona-1m-*.parquet"))] if data.is_dir() else []
    if not paths:
        return {"available": False, "state": "no_shards"}
    try:
        source = HfCoresetSource(cache_dir=corpus, shards=paths)
        saved = load_coverage(source)
    except Exception as failure:
        return {"available": False, "state": "failed", "detail": _coverage_failure(failure)}
    if saved is not None:
        return {"available": True, "state": "ready", "totals": saved["totals"], "attributes": coverage_table(saved)}
    with state.coverage_lock:
        job = state.coverage_job
        if job["thread"] is not None and job["thread"].is_alive():
            return {"available": False, "state": "building"}
        if job["error"] is not None and not retry:
            return {"available": False, "state": "failed", "detail": job["error"]}

        def count() -> None:
            try:
                count_coverage(source)
            except Exception as failure:
                job["error"] = _coverage_failure(failure)

        job["error"] = None
        job["thread"] = threading.Thread(target=count, name="corpus-coverage", daemon=True)
        job["thread"].start()
    return {"available": False, "state": "building"}


def _build_embeddings_job(state: Any, corpus: str) -> None:
    """Embed every codebook attribute once, in the background, recording why it failed."""
    from simcore.ports.embeddings import build_embeddings, codebook_digest, embed_model

    try:
        path = Path(corpus)
        build_embeddings(path, codebook_digest(path), embed_model())
    except Exception as failure:
        state.embeddings_job["error"] = f"embeddings could not be built ({type(failure).__name__})"


def _chat_json(system: str, user: str, max_tokens: int) -> dict:
    """One JSON answer from the language model through the one OpenAI-compatible endpoint."""
    import json as _json
    import os
    import urllib.request

    configured = os.environ.get("SIMCORE_INFERENCE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    base = configured.rstrip("/") if configured else "http://127.0.0.1:4000/v1"
    model = os.environ.get("SIMCORE_CHAT_MODEL") or "amazon.nova-micro-v1:0"
    body = _json.dumps({
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions", data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        reply = _json.load(response)
    content = reply["choices"][0]["message"]["content"]
    found = re.search(r"\{.*\}", content, re.S)
    return _json.loads(found.group(0)) if found else {}


def _reading_of(raw: Any):
    """The confirmed reading as the engine's own type, or why it is refused."""
    from simcore.population import Group, Reading

    if not isinstance(raw, dict):
        raise ValueError("a reading names groups, shared traits and topics")
    groups = []
    for audience in raw.get("groups") or []:
        if not isinstance(audience, dict):
            raise ValueError("a reading names groups, shared traits and topics")
        share = audience.get("share")
        groups.append(Group(
            name=str(audience.get("name") or "audience"),
            share=share if isinstance(share, (int, float)) and share > 0 else None,
            traits=tuple(str(trait) for trait in audience.get("traits") or []),
        ))
    return Reading(
        product=raw.get("product"),
        groups=tuple(groups),
        everyone=tuple(str(trait) for trait in raw.get("everyone") or []),
        topics=tuple(str(topic) for topic in raw.get("topics") or []),
    )


def _latest_ontology(root: str, category_id: str):
    """The latest saved ontology version for a category, or nothing."""
    import json as _json

    folder = Path(root, category_id)
    if not _NAME.fullmatch(category_id) or not folder.is_dir():
        return None
    versions = sorted(folder.glob("*.json"))
    if not versions:
        return None
    try:
        return _json.loads(versions[-1].read_text(encoding="utf-8"))
    except ValueError:
        return None


def _pool_failure(failure: Exception) -> str:
    """Why a pool count failed, in words that name no path on the server."""
    from simcore.ports.hf import MissingShard, ShardMismatch

    if isinstance(failure, ShardMismatch):
        return "a cached shard does not match the release's manifest; fetch it again"
    if isinstance(failure, MissingShard):
        return "a shard the release names is not cached"
    return f"the count failed ({type(failure).__name__})"


def _build_matrix_job(state: Any, corpus: str) -> None:
    """Build the persona value matrix once, in the background, recording why it failed."""
    from simcore.ports.hf import HfCoresetSource
    from simcore.ports.matrix import build_matrix

    try:
        build_matrix(HfCoresetSource(cache_dir=Path(corpus)))
    except Exception as failure:
        state.matrix_job["error"] = _pool_failure(failure)


def _coverage_failure(failure: Exception) -> str:
    """Why a count failed, in words that name no path on the server."""
    from simcore.ports.hf import MissingShard, ShardMismatch

    if isinstance(failure, ShardMismatch):
        return "a cached shard does not match the release's manifest; fetch it again"
    if isinstance(failure, MissingShard):
        return "a shard the release names is not cached"
    return f"the count failed ({type(failure).__name__})"


def _corpus_root(request: Request) -> Path | None:
    """The cached corpus directory: the one configured, else the user's default cache. Never served."""
    candidates = []
    if request.app.state.corpus_dir is not None:
        candidates.append(Path(request.app.state.corpus_dir))
    try:
        from simcore.ports.hf import default_cache_dir

        candidates.append(Path(default_cache_dir()))
    except Exception:
        pass
    for candidate in candidates:
        if Path(candidate, "manifest.json").is_file() or Path(candidate, "persona_codes.schema.json").is_file():
            return candidate
    return None


def _codebook_or_refuse(request: Request):
    """The corpus's own codebook, or an honest refusal when no corpus is cached."""
    from simcore.ports.decoder import Codebook

    corpus = _corpus_root(request)
    candidate = Path(corpus, "persona_codes.schema.json") if corpus is not None else None
    if candidate is not None and candidate.is_file():
        return Codebook.from_json(candidate)
    raise HTTPException(
        status_code=409,
        detail="no corpus is cached here, so no draft can be pinned: author freely, "
        "then validate where the corpus is present",
    )


def _endpoint_configured() -> bool:
    """Whether the server's environment names an inference endpoint. Never its key."""
    import os

    return bool(os.environ.get("SIMCORE_INFERENCE_BASE_URL") or os.environ.get("OPENAI_BASE_URL"))


def _run_entry(run_dir: Path, request: Request | None = None) -> dict[str, Any] | None:
    """One registry entry's story: status, spend, worlds and what was written.

    Reads the run's own `result.json`, `report.json` and `gate-report.json` —
    the artefacts the CLI wrote — and serialises their fields. `result.json` is
    written last, so a run that has one is finished and a run that does not is
    still going or was stopped: its status, recorded cost and ticks closed come
    from the registry entry and the live views instead — the entry is the
    published cache of what the trace already says.
    """
    lifecycle.adopt(run_dir)
    result = _read_json_silent(Path(run_dir, "result.json"))
    gate = _read_json_silent(Path(run_dir, "gate-report.json"))
    report = _read_json_silent(Path(run_dir, "report.json"))
    hide = _hidden_prefixes(request)
    if result is not None and result.get("status") == "completed":
        return _finished_entry(run_dir, result, gate, report, hide)
    live = _live_entry(run_dir)
    if live is not None:
        return _running_entry(run_dir, live, gate, report, hide)
    if result is not None:
        return _finished_entry(run_dir, result, gate, report, hide)
    if gate is None and lifecycle.launch_record(run_dir) is None:
        return None
    # A study that was started here but has recorded nothing: either its process
    # is still building the population, or it died before it could record
    # anything — and the log says which, rather than the run never existing.
    starting = lifecycle.is_live(run_dir.name)
    return _finished_entry(
        run_dir,
        {"status": "running" if starting else "partial", "registry": {}, "outcomes": []},
        gate,
        report,
        hide,
    )


def _hidden_prefixes(request: Request | None) -> tuple[str, ...]:
    """Directory prefixes a log line must not carry to a browser."""
    if request is None:
        return ()
    roots = (request.app.state.runs_dir, request.app.state.engine_root)
    return tuple(sorted({str(Path(root).resolve()) for root in roots} | {str(root) for root in roots}, key=len, reverse=True))


def _is_fake(pins: dict[str, Any]) -> bool:
    """A fake run needs no key, no corpus and no network — and says so everywhere."""
    models = [
        pin.get("model_id") for pin in pins.values()
        if isinstance(pin, dict) and "model_id" in pin
    ]
    return bool(models) and all(str(model).startswith("fake/") for model in models)


def _why_it_stopped(run_dir: Path, hide: tuple[str, ...]) -> str | None:
    """The last thing a stopped study said, when it is not running and has no report."""
    if lifecycle.is_live(run_dir.name) or Path(run_dir, "report.json").is_file():
        return None
    return lifecycle.log_tail(run_dir, hide)


def _finished_entry(
    run_dir: Path, result: dict[str, Any], gate: Any, report: Any, hide: tuple[str, ...] = ()
) -> dict[str, Any]:
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
        "launch_error": _why_it_stopped(run_dir, hide),
    }


def _live_entry(run_dir: Path) -> dict[str, Any] | None:
    """The registry entry of a run with no `result.json` yet, if it was recorded."""
    try:
        entry = _store(run_dir).registry.entry(run_dir.name)
    except Exception:
        return None
    if entry is None:
        return None
    return json.loads(entry.model_dump_json())


def _running_entry(
    run_dir: Path, live: dict[str, Any], gate: Any, report: Any, hide: tuple[str, ...] = ()
) -> dict[str, Any]:
    config = live.get("config", {})
    trust = (report or {}).get("trust", {})
    pins = config.get("pins", {})
    going = lifecycle.is_live(run_dir.name)
    status = live.get("status", "running")
    if not going and status == "running" and lifecycle.launch_record(run_dir) is not None:
        # This server started the study and its process is gone, but the registry
        # still says running: it crashed or was killed mid-session, and the sweep
        # that would say so only runs at start. Its trace is valid up to its last
        # closed tick, which is what partial means and what a resume continues from.
        status = "partial"
    return {
        "run_id": run_dir.name,
        # A study whose process is alive and whose `result.json` is not yet on disk
        # is still working — building the report, or picking up after a resume —
        # whatever its registry entry last said: it is not finished until it says so.
        "status": "running" if going else status,
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
        "live": going,
        "launch_error": _why_it_stopped(run_dir, hide),
    }


def _live_progress(run_dir: Path, world_ids: list[str]) -> list[dict[str, Any]]:
    """Ticks closing, turns landing and the rung in force, per world, from live views.

    The counting is `analysis`'s (`world_progress`); this serialises what it derived.
    """
    try:
        store = _store(run_dir)
    except Exception:
        return []
    progress = []
    for world_id in world_ids:
        try:
            shape = world_progress(store.view(run_dir.name, world_id), world_id)
        except Exception:
            continue
        progress.append(json.loads(shape.model_dump_json()))
    return progress


def _run_gate(request: Request, body: GateRequest) -> dict[str, Any]:
    """Run `coreset-gate` on a brief and serve the artefacts it wrote, never its paths."""
    import subprocess
    import sys
    import tempfile

    from simcore.cli._ids import mint_run_id

    if not body.fake:
        if not body.model or not body.embed_model:
            raise HTTPException(
                status_code=422,
                detail="a real gate pins its models: model and embed_model, the same ones the study will run on",
            )
        if not _endpoint_configured():
            raise HTTPException(
                status_code=409,
                detail="no inference endpoint is configured in the server's environment: "
                "run a fake gate, or set SIMCORE_INFERENCE_BASE_URL where the server starts",
            )
    with tempfile.TemporaryDirectory(prefix="consumersim-brief-") as scratch:
        brief = Path(scratch, "brief.yaml")
        brief.write_text(body.brief_yaml, encoding="utf-8")
        if body.evidence_json is not None:
            Path(scratch, "brief.yaml.evidence.json").write_text(
                "\n".join([json.dumps(body.evidence_json, indent=2, sort_keys=True), ""]), encoding="utf-8"
            )
        try:
            _validate_brief(brief, _ontologies_root(request))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        run_id = mint_run_id()
        argv = [
            sys.executable, "-m", "simcore.cli", "coreset-gate",
            "--brief", str(brief),
            "--n", str(body.n),
            "--seed", str(body.seed),
            "--ontologies", _ontologies_root(request),
            "--out", str(_runs_dir(request)),
            "--run-id", run_id,
        ]
        if body.fake:
            argv.append("--fake")
        else:
            argv.extend(["--model", str(body.model), "--embed-model", str(body.embed_model)])
        argv.extend(_corpus_flags(body))
        try:
            done = subprocess.run(
                argv, cwd=request.app.state.engine_root, capture_output=True, text=True, timeout=240
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="the population gate took longer than four minutes")
    run_dir = Path(_runs_dir(request), run_id)
    gate = _read_json_silent(Path(run_dir, "gate-report.json"))
    manifest = _read_json_silent(Path(run_dir, "manifest.json"))
    refusal = None
    if gate is None:
        hide = _hidden_prefixes(request)
        lines = [line for line in (done.stderr or done.stdout).splitlines() if line.strip()]
        refusal = lines[-1] if lines else "the gate wrote no report"
        for prefix in hide:
            refusal = refusal.replace(prefix, "…")
    return {
        "code": done.returncode,
        "run_id": run_id if gate is not None else None,
        "gate": gate,
        "manifest": manifest,
        "refusal": refusal,
    }


def _read_json_silent(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
