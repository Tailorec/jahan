"""One study end to end, shared by `concepts run` and `sweep run`.

Load the brief, gate the draw before anything is spent, build the population, run every
world of the configuration under one budget, derive digests, findings, clusters and
anomalies from the record, render the report, and write the artefacts into the
run-named directory. The CLI derives nothing: every number it writes came from a module
that owns it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from simcore.agent import AgentConfig, PersonaBlockCache
from simcore.agent import turns as agent_turns
from simcore.analysis import (
    cluster_objections,
    detect_anomalies,
    digest,
    findings,
    spread,
    trust_statement,
)
from simcore.brief import load_brief
from simcore.elicitation import anchor_hash, assert_pinnable, load_anchor_version
from simcore.population import assess, build
from simcore.report import ReportPack, render
from simcore.runner import ENGINE_VERSION, run
from simcore.schemas import (
    BriefPack,
    BudgetExhausted,
    DegradationRung,
    GateFailure,
    OutcomeDigest,
    Population,
    RunConfig,
    RunResult,
    Scenario,
    WorldStatus,
    check_scenario_against_brief,
    derive_world_id,
)
from simcore.schemas.base import canonical_hash
from simcore.schemas.errors import SimError
from simcore.trace import TraceStore, UnknownWorldError
from simcore.trace.finalize import read_finalized_events
from simcore.world import World, WorldConfig

from ._fake import FAKE_EMBED, fake_backend, fake_pins
from ._ids import mint_run_id
from ._templates import template_hashes

DEFAULT_VALIDATION = (
    "Each finding above names the real-world check that would falsify it; "
    "run those checks before acting on this report."
)


@dataclass
class StudyHandles:
    """Everything a study carries: the record, the population and the runnable pieces."""

    run_id: str
    run_dir: Path
    store: TraceStore
    pack: BriefPack
    population: Population
    config: RunConfig
    chat: object
    embed: object
    embed_pin: str
    agent_config: AgentConfig


class StoreTrace:
    """The on-disk store behind the runner's trace seam, plus resume reads.

    The runner writes through `write`/`finalize` and replays through `events_for`/
    `all_events`. Live worlds answer from their live record; finalized ones answer
    from their lasting one, so re-running a finished cell replays it instead of
    redoing it. A world with no record at all has not started, so it answers empty.
    """

    def __init__(self, store: TraceStore, root: Path, run_id: str) -> None:
        self._store, self._root, self._run_id = store, Path(root), run_id

    def write(self, events) -> None:
        self._store.write(events)

    def finalize(self, world_id: str):
        return self._store.finalize(world_id)

    def events_for(self, world_id: str):
        if self._store.is_finalized(self._run_id, world_id):
            return read_finalized_events(self._root, self._run_id, world_id)
        try:
            return self._store.read_live(self._run_id, world_id)
        except UnknownWorldError:
            return ()

    def all_events(self):
        out: list = []
        for world_id in self._store.world_ids(self._run_id):
            out.extend(self.events_for(world_id))
        return tuple(out)


def assemble_scenario(
    pack: BriefPack,
    *,
    variant_id: str,
    name: str,
    description: str,
    tick_unit: str = "day",
    horizon_ticks: int = 4,
) -> Scenario:
    """The study's baseline scenario: the whole proposition at the brief's price.

    The variant emphasizes every claim the brief makes — the concept presents the
    product, not a slice of it — and the audiences run at the shares the brief declares.
    """
    weights = pack.brief.audience_shares
    if weights is None:
        raise GateFailure(
            "the brief declares no audience shares and the scenario states no weights: "
            "a run configuration cannot inherit what was never declared"
        )
    scenario = Scenario.model_validate({
        "variant": {
            "variant_id": variant_id,
            "name": name,
            "description": description,
            "emphasized_claims": [claim.id for claim in pack.brief.claims],
        },
        "price": pack.brief.price.model_dump(mode="json"),
        "audience_weights": dict(weights),
        "tick_unit": tick_unit,
        "horizon_ticks": horizon_ticks,
        "interventions": [],
    })
    check_scenario_against_brief(scenario, pack.brief)
    return scenario


def anchor_pins(
    pack: BriefPack, anchors_dir: Path, *, embed_pin: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Pin every anchor set the ontology names by content hash, and the versions the
    check lets through for scoring. A set with no frozen version file, or several,
    refuses: the study must say which scale it runs on. A version whose check failed —
    every version until one passes — stays pinned but unscored, so intent goes
    unmeasured and the verbatim is kept with its failure (ADR 0029, ADR 0032)."""
    set_hashes: dict[str, str] = {}
    set_ids: dict[str, str] = {}
    versions: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for construct, set_id in sorted(pack.ontology.anchor_sets.items()):
        candidates = (
            sorted(
                path
                for path in (anchors_dir / construct).glob("*.json")
                if not path.name.endswith(".check.json")
            )
            if (anchors_dir / construct).is_dir()
            else []
        )
        if not candidates:
            raise GateFailure(
                f"the ontology names anchor set {set_id!r} but {anchors_dir / construct} holds no frozen version"
            )
        if len(candidates) > 1:
            raise GateFailure(
                f"the ontology names anchor set {set_id!r} but {construct} holds several versions "
                f"({', '.join(path.stem for path in candidates)}): the study must say which one"
            )
        version_file = candidates[0]
        set_hashes[set_id] = anchor_hash(load_anchor_version(version_file))
        try:
            record = assert_pinnable(set_id, construct, version_file.stem, anchors_dir, embed_model_id=embed_pin)
        except ValueError:
            continue
        set_ids[construct] = record.anchor_set_id
        versions[construct] = record.version
        hashes[construct] = record.anchor_hash
    return set_hashes, set_ids, versions, hashes


def assemble_backend(pack: BriefPack, args) -> tuple:
    """The inference ports, coreset and pins the study runs on: fake or real, never mixed."""
    if args.fake:
        chat, embed, coreset = fake_backend(pack, seed=args.population_seed)
        return chat, embed, coreset, fake_pins(), FAKE_EMBED
    from simcore.inference import ExecutionSettings, InferenceClient
    from simcore.ports.hf import HfCoresetSource, default_cache_dir
    from simcore.schemas import ModelPins

    if not args.model or not args.embed_model:
        raise GateFailure("a real study pins its models: pass --model and --embed-model (or run --fake)")

    def _pin(model_id: str, price: dict | None) -> dict:
        pin: dict = {"model_id": model_id, "serves": [model_id]}
        if price is not None:
            pin["price"] = price
        return pin

    chat_price = (
        {"input_per_million": args.price_chat_in, "output_per_million": args.price_chat_out}
        if args.price_chat_in is not None and args.price_chat_out is not None
        else None
    )
    embed_price = (
        {"input_per_million": args.price_embed_in, "output_per_million": 0.0}
        if args.price_embed_in is not None
        else None
    )
    pins = {
        "tier_a": _pin(args.model, chat_price),
        "tier_b": _pin(args.model, chat_price),
        "embed": _pin(args.embed_model, embed_price),
    }
    client = InferenceClient(ModelPins.model_validate(pins), ExecutionSettings.from_environment())
    cache = args.cache or default_cache_dir()
    manifest_path = cache / "manifest.json"
    shards = (
        [entry["path"] for entry in json.loads(manifest_path.read_text()).get("files", [])]
        if manifest_path.is_file()
        else None
    )
    coreset = HfCoresetSource(cache_dir=cache, shards=shards)
    return client, client, coreset, pins, args.embed_model


def prepare_study(
    *,
    brief_path: Path,
    ontologies_dir: Path,
    anchors_dir: Path,
    out_dir: Path,
    run_id: str | None,
    n: int,
    population_seed: int,
    scenarios: list[Scenario] | None,
    seeds: list[int],
    budget: float,
    args,
) -> StudyHandles:
    """Load, gate, build and configure — everything before the first tick. The gate report
    and the manifest are written as the study earns them, so a failed gate leaves the
    report that explains it."""
    pack = load_brief(brief_path, ontologies_dir)
    if scenarios is None:
        scenarios = [
            assemble_scenario(
                pack,
                variant_id="baseline",
                name=pack.brief.product.name,
                description=pack.brief.product.description,
                tick_unit=args.tick_unit,
                horizon_ticks=args.horizon,
            )
        ]
    run_id = run_id or mint_run_id()
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    chat, embed, coreset, pins, embed_pin = assemble_backend(pack, args)

    gate_report = assess(pack, n, population_seed, coreset=coreset)
    (run_dir / "gate-report.json").write_text(gate_report.model_dump_json(indent=2) + "\n")
    if not gate_report.overall:
        failed = sorted(result.attribute for result in gate_report.results if not result.passed)
        raise GateFailure(f"the sample failed its distribution gates: {failed}")

    built = build(pack, n, population_seed, coreset=coreset, inference=chat)
    population = built.population
    (run_dir / "manifest.json").write_text(population.manifest.model_dump_json(indent=2) + "\n")

    set_hashes, set_ids, versions, hashes = anchor_pins(pack, anchors_dir, embed_pin=embed_pin)
    config = RunConfig.model_validate({
        "run_id": run_id,
        "pins": pins,
        "budget": {"max_cost": budget, "currency": "USD"},
        "brief_hash": canonical_hash(pack.brief),
        "ontology_hash": canonical_hash(pack.ontology),
        "population_hash": population.manifest.population_hash,
        "graph_hash": population.manifest.graph_hash,
        "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
        "seeds": seeds,
        "template_hashes": template_hashes(),
        "anchor_set_hashes": set_hashes,
    })
    agent_config = AgentConfig(
        run_seed=population_seed,
        horizon_ticks=max(scenario.horizon_ticks for scenario in scenarios),
        anchor_set_ids=set_ids,
        anchor_versions=versions,
        anchor_hashes=hashes,
        anchors_dir=str(anchors_dir),
        category=pack.brief.product.category,
    )
    store = TraceStore(run_dir / "trace")
    return StudyHandles(
        run_id=run_id,
        run_dir=run_dir,
        store=store,
        pack=pack,
        population=population,
        config=config,
        chat=chat,
        embed=embed,
        embed_pin=embed_pin,
        agent_config=agent_config,
    )


def run_study(handles: StudyHandles, *, channel: str, max_workers: int = 1) -> RunResult:
    """Run every world of the configuration to its horizon, recording the trace."""
    store = handles.store
    trace = StoreTrace(store, handles.run_dir / "trace", handles.run_id)
    blocks = PersonaBlockCache()

    def world_factory(header):
        store.create_world(handles.run_id, header)
        return World(header, population=handles.population, config=WorldConfig(platform=channel))

    def agent_fn(jobs):
        published: dict[str, str] = {}
        for world_id in store.world_ids(handles.run_id):
            for event in trace.events_for(world_id):
                if event.payload.kind == "stimulus_published":
                    published[event.payload.stimulus.stimulus_id] = event.payload.stimulus.text
        return agent_turns(
            jobs,
            chat=handles.chat,
            config=handles.agent_config,
            ontology=handles.pack.ontology,
            blocks=blocks,
            embed=handles.embed,
            stimulus_texts=published,
        )

    return run(
        handles.config,
        pack=handles.pack,
        population=handles.population,
        trace=trace,
        registry=store.registry,
        world_factory=world_factory,
        agent_fn=agent_fn,
        max_workers=max_workers,
    )


def analyze_study(handles: StudyHandles, result: RunResult) -> dict:
    """Derive digests, findings, clusters and anomalies from the record, per world.

    Only worlds that reached their horizon are read: a paused world has no whole record
    to derive from, and its artefacts are the trace itself.
    """
    store, config = handles.store, handles.config
    completed = {outcome.world_id for outcome in result.outcomes if outcome.status is WorldStatus.COMPLETED}
    digests: list[OutcomeDigest] = []
    cells: dict[str, dict] = {}
    for scenario in config.scenarios:
        for seed in config.seeds:
            world_id = derive_world_id(scenario, seed, config.population_hash)
            if world_id not in completed:
                continue
            view = store.view(config.run_id, world_id)
            outcome = digest(
                view,
                scenario=scenario,
                population=handles.population,
                seed=seed,
                pinned_embed_model=handles.embed_pin,
            )
            digests.append(outcome)
            cells[world_id] = {"scenario": scenario, "seed": seed, "view": view, "digest": outcome}
    summaries = {}
    for scenario in config.scenarios:
        scenario_cells = [cell["digest"] for cell in cells.values() if cell["scenario"] == scenario]
        if scenario_cells:
            summaries[canonical_hash(scenario)] = spread(scenario_cells)
    worlds = {}
    for world_id, cell in cells.items():
        summary = summaries[canonical_hash(cell["scenario"])]
        found = findings(cell["view"], embed=handles.embed, pinned_embed_model=handles.embed_pin, seed=cell["seed"])
        detected = detect_anomalies(cell["view"], digest=cell["digest"], replicate_spread=summary.belief_move_spread)
        clusters = cluster_objections(cell["view"], embed=handles.embed, pinned_embed_model=handles.embed_pin)
        worlds[world_id] = {
            "scenario": cell["scenario"],
            "seed": cell["seed"],
            "digest": cell["digest"],
            "findings": found,
            "anomalies": detected.anomalies,
            "unmeasured": detected.unmeasured,
            "clusters": clusters,
        }
    return {"digests": digests, "worlds": worlds, "summaries": summaries}


def write_report(handles: StudyHandles, analysis: dict, *, validation: str) -> dict:
    """Render the report over the completed worlds and write the run's documents."""
    entry = handles.store.registry.entry(handles.run_id)
    assert entry is not None
    all_findings = [finding for cell in analysis["worlds"].values() for finding in cell["findings"]]
    all_anomalies = [anomaly for cell in analysis["worlds"].values() for anomaly in cell["anomalies"]]
    all_clusters = [cluster for cell in analysis["worlds"].values() for cluster in cell["clusters"]]
    pack = ReportPack(
        config=handles.config,
        trust=trust_statement(),
        brief_pack=handles.pack,
        validation=validation,
        engine_commit=ENGINE_VERSION,
        anomalies=tuple(all_anomalies),
        clusters=tuple(all_clusters),
        forced_from=tuple(entry.forced_from),
    )
    rendered = render(tuple(all_findings), tuple(analysis["digests"]), pack)
    (handles.run_dir / "report.md").write_text(rendered.markdown)
    (handles.run_dir / "report.json").write_text(json.dumps(rendered.data, indent=2, sort_keys=True) + "\n")
    (handles.run_dir / "digest.json").write_text(
        json.dumps(
            {
                "run_id": handles.run_id,
                "digests": [item.model_dump(mode="json") for item in analysis["digests"]],
                "summaries": {
                    scenario_hash: summary.model_dump(mode="json")
                    for scenario_hash, summary in analysis["summaries"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return rendered.data


def check_budget(result: RunResult) -> None:
    """Turn an unfinished run into the exception its exit code comes from.

    Worlds paused at the budget's pause rung are an exhausted budget: their completed
    siblings' artefacts are already in place, so raising keeps nothing back. Worlds that
    stopped any other way are a defect, not a verdict.
    """
    paused = sorted(outcome.world_id for outcome in result.outcomes if DegradationRung.PAUSE in outcome.rungs)
    if paused:
        raise BudgetExhausted(f"the budget ran out with worlds paused: {', '.join(paused)}")
    failed = sorted(
        outcome.world_id for outcome in result.outcomes if outcome.status is not WorldStatus.COMPLETED
    )
    if failed:
        raise SimError(f"worlds stopped without completing: {', '.join(failed)}")
