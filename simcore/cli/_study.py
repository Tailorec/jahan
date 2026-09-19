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
    trace_summary,
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
        # What each stimulus says, gathered as it is written. The agent shows a persona the
        # concept itself, so the texts have to be to hand every tick; reading the whole record
        # back to find them again costs the record's size on every batch.
        self.published: dict[str, str] = {}

    def write(self, events) -> None:
        self._store.write(events)
        for event in events:
            if event.payload.kind == "stimulus_published":
                self.published[event.payload.stimulus.stimulus_id] = event.payload.stimulus.text

    def prime_published(self) -> None:
        """What earlier ticks published, for a run this process is resuming rather than starting."""
        try:
            world_ids = self._store.world_ids(self._run_id)
        except Exception:  # a run with no record yet has published nothing
            return
        for world_id in world_ids:
            for event in self.events_for(world_id):
                if event.payload.kind == "stimulus_published":
                    self.published[event.payload.stimulus.stimulus_id] = event.payload.stimulus.text

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
    elicits: str = "reaction",
) -> Scenario:
    """The study's baseline scenario: the whole proposition at the brief's price.

    The variant emphasizes every claim the brief makes — the concept presents the
    product, not a slice of it — and the audiences run at the shares the brief declares.

    `elicits` is what an activated persona is asked. A concept test exists to ask purchase
    intent, and the default asks for a reaction: the first real study pinned a passing scale
    and then asked 897 personas what they would do, so not one turn was scored for intent.
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
        "elicits": elicits,
    })
    check_scenario_against_brief(scenario, pack.brief)
    return scenario


def anchor_pins(
    pack: BriefPack, anchors_dir: Path, *, embed_pin: str, chosen: dict[str, str] | None = None
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Pin every anchor set the ontology names by content hash, and the versions the
    check lets through for scoring.

    Returns `(set_hashes, set_ids, versions, hashes)`: every set the ontology names by set id,
    the set and version each construct scores on, and — by set id again — the hashes a scorer
    resolves against. A set with no frozen version file, or several,
    refuses: the study must say which scale it runs on. A version whose check failed —
    every version until one passes — stays pinned but unscored, so intent goes
    unmeasured and the verbatim is kept with its failure (ADR 0029, ADR 0032).

    `chosen` is how a study says which one, per construct. A superseded version stays on
    disk as the evidence of what failed, so the moment a second version exists every study
    needs a way to name the scale it runs on."""
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
        if len(candidates) > 1 and (chosen or {}).get(construct) is None:
            raise GateFailure(
                f"the ontology names anchor set {set_id!r} but {construct} holds several versions "
                f"({', '.join(path.stem for path in candidates)}): the study must say which one, "
                f"with --anchor-version {construct}=<version>"
            )
        named = (chosen or {}).get(construct)
        if named is not None:
            version_file = anchors_dir / construct / f"{named}.json"
            if not version_file.is_file():
                raise GateFailure(
                    f"the study names anchor version {named!r} for {construct}, but "
                    f"{version_file} does not exist"
                )
        else:
            version_file = candidates[0]
        set_hashes[set_id] = anchor_hash(load_anchor_version(version_file))
        try:
            record = assert_pinnable(set_id, construct, version_file.stem, anchors_dir, embed_model_id=embed_pin)
        except ValueError:
            continue
        set_ids[construct] = record.anchor_set_id
        versions[construct] = record.version
        # Keyed by anchor set id, because that is how the scorer looks them up: `resolve_anchors`
        # takes `RunConfig.anchor_set_hashes` — set id to content hash — and `_pinned` asks whether
        # the construct's set id is among them. Keyed by construct, a scale that passed its check
        # pinned cleanly and then failed to score a single turn.
        hashes[record.anchor_set_id] = record.anchor_hash
    return set_hashes, set_ids, versions, hashes


def assemble_backend(pack: BriefPack, args) -> tuple:
    """The inference ports, coreset and pins the study runs on: fake or real, never mixed."""
    if args.fake and args.coreset_fixture is not None:
        raise ValueError("--fake and --coreset-fixture both name the corpus: pass exactly one")
    if args.fake:
        chat, embed, coreset = fake_backend(pack, seed=args.population_seed)
        return chat, embed, coreset, fake_pins(), FAKE_EMBED
    if args.coreset_fixture is not None:
        from simcore.ports.fixture import FixtureCoresetSource

        chat, embed, _ = fake_backend(pack, seed=args.population_seed)
        return chat, embed, FixtureCoresetSource.from_json(args.coreset_fixture), fake_pins(), FAKE_EMBED
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
    shards = shards_from(args) or (
        [entry["path"] for entry in json.loads(manifest_path.read_text()).get("files", [])]
        if manifest_path.is_file()
        else None
    )
    coreset = HfCoresetSource(cache_dir=cache, shards=shards)
    return client, client, coreset, pins, args.embed_model


def sources_from(args) -> frozenset[str] | None:
    """`--sources wiki,gss`, as the sources a study admits. Nothing named admits every source.

    The release carries synthetic rows beside the measured ones, and a persona may not have
    synthesized demographic or psychographic fields — so a draw that reaches them is refused by
    the `Population` contract once the whole draw has been built. A source is admitted
    deliberately (`PopulationParameters.admissible_sources`), and this is how a study says it."""
    from simcore.schemas.persona import KNOWN_PERSONA_SOURCES

    raw = getattr(args, "sources", None)
    if raw is None:
        return None
    named = {item.strip() for item in str(raw).split(",") if item.strip()}
    if not named:
        raise GateFailure("--sources takes at least one persona source, like --sources wiki,gss")
    unknown = sorted(named - KNOWN_PERSONA_SOURCES)
    if unknown:
        raise GateFailure(
            f"unknown persona source {', '.join(unknown)}; the release documents "
            f"{', '.join(sorted(KNOWN_PERSONA_SOURCES))}"
        )
    return frozenset(named)


def shards_from(args) -> list[str] | None:
    """`--shards 0000,0004`, as manifest paths. Nothing named means every shard the manifest lists.

    The release is ten shards of a hundred thousand personas each and a draw reads a fraction of
    one, so a study that does not need them all should not wait on gigabytes it will never read.
    Naming them explicitly keeps the draw reproducible, where "whatever is cached" would make it
    depend on the machine it ran on."""
    raw = getattr(args, "shards", None)
    if raw is None:
        return None
    named = [item.strip() for item in str(raw).split(",") if item.strip()]
    if not named:
        raise GateFailure("--shards takes at least one shard, like --shards 0000,0004")
    return [item if "/" in item else f"data/persona-1m-{item}.parquet" for item in named]


def anchor_versions_from(args) -> dict[str, str]:
    """`--anchor-version construct=version`, as a mapping. A study says which scale it runs on."""
    chosen: dict[str, str] = {}
    for item in getattr(args, "anchor_version", None) or ():
        construct, _, version = str(item).partition("=")
        if not construct or not version:
            raise GateFailure(f"--anchor-version takes construct=version, got {item!r}")
        chosen[construct] = version
    return chosen


def gate_and_build(
    pack: BriefPack, *, n: int, population_seed: int, chat: object, coreset: object, run_dir: Path,
    sources: frozenset[str] | None = None
) -> Population:
    """Assess the draw before anything is spent, then build the population.

    The gate report is written as the study earns it, so a failed gate leaves the
    report that explains it. Returns the population; a failing draw raises.
    """
    from simcore.schemas import GateReport, PopulationParameters

    parameters = PopulationParameters(admissible_sources=sources) if sources else PopulationParameters()
    gate_report: GateReport = assess(pack, n, population_seed, coreset=coreset, parameters=parameters)
    (run_dir / "gate-report.json").write_text(gate_report.model_dump_json(indent=2) + "\n")
    if not gate_report.overall:
        failed = sorted(result.attribute for result in gate_report.results if not result.passed)
        raise GateFailure(f"the sample failed its distribution gates: {failed}")
    built = build(pack, n, population_seed, coreset=coreset, inference=chat, parameters=parameters)
    population = built.population
    (run_dir / "manifest.json").write_text(population.manifest.model_dump_json(indent=2) + "\n")
    return population


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
                elicits=getattr(args, "elicits", None) or "reaction",
            )
        ]
    run_id = run_id or mint_run_id()
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    chat, embed, coreset, pins, embed_pin = assemble_backend(pack, args)
    population = gate_and_build(pack, n=n, population_seed=population_seed, chat=chat, coreset=coreset,
                                run_dir=run_dir, sources=sources_from(args))

    set_hashes, set_ids, versions, hashes = anchor_pins(
        pack, anchors_dir, embed_pin=embed_pin, chosen=anchor_versions_from(args))
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


def run_study(handles: StudyHandles, *, channel: str, max_workers: int = 1, force: bool = False) -> RunResult:
    """Run every world of the configuration to its horizon, recording the trace.

    A resume whose inputs moved refuses unless forced; forcing is recorded in the
    registry rather than only in the process that forced it.
    """
    store = handles.store
    trace = StoreTrace(store, handles.run_dir / "trace", handles.run_id)
    trace.prime_published()
    blocks = PersonaBlockCache()

    def world_factory(header):
        store.create_world(handles.run_id, header)
        return World(header, population=handles.population, config=WorldConfig(platform=channel))

    def agent_fn(jobs):
        return agent_turns(
            jobs,
            chat=handles.chat,
            config=handles.agent_config,
            ontology=handles.pack.ontology,
            blocks=blocks,
            embed=handles.embed,
            stimulus_texts=trace.published,
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
        force=force,
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
        # Cluster once and hand the result to `findings`: the same verbatims embedded twice
        # is the same answer at twice the price.
        clusters = cluster_objections(cell["view"], embed=handles.embed, pinned_embed_model=handles.embed_pin,
                                      world_id=world_id)
        found = findings(cell["view"], embed=handles.embed, pinned_embed_model=handles.embed_pin,
                         seed=cell["seed"], world_id=world_id, clusters=clusters)
        detected = detect_anomalies(cell["view"], digest=cell["digest"], replicate_spread=summary.belief_move_spread)
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


def write_trace_summary(handles: StudyHandles, result: RunResult) -> dict:
    """Write `trace-summary.json` over every world that has any record.

    A finished run's worlds answer from their finalized record, a paused run's
    from its live one — a live view shows every closed tick and nothing more, so
    a paused run writes what it has. The summary joins the five shapes and nothing
    else; the CLI derives nothing.
    """
    views = {}
    for outcome in result.outcomes:
        try:
            views[outcome.world_id] = handles.store.view(handles.run_id, outcome.world_id)
        except Exception:
            continue
    summary = trace_summary(views, run_id=handles.run_id)
    (handles.run_dir / "trace-summary.json").write_text(summary.model_dump_json(indent=2) + "\n")
    return json.loads(summary.model_dump_json())


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
        forced_inputs=tuple(entry.forced_inputs),
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
