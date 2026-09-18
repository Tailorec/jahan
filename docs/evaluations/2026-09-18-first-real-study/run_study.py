"""The first whole study on a real model: brief to recorded trace, nothing faked.

Every module in the chain runs for real — `brief` loads the pack, `population` samples Stack
Overflow rows and completes sparse fields through the model, `world` decides who sees what,
`agent` answers as each persona, `inference` bills every call, `runner` drives the ticks inside
a budget and `trace` records it and finalizes it. The only substitutions are the ones the
design already states: purchase intent is not scored, because no anchor version passes its
check (ADR 0029, ADR 0032).

    SIMCORE_INFERENCE_BASE_URL=http://127.0.0.1:4000/v1 \
      python docs/evaluations/2026-09-18-first-real-study/run_study.py --personas 40 --ticks 4 --out report.json

Prices are the AWS Pricing API's us-east-1 standard on-demand rates on 2026-09-18, per million
tokens: Ministral 3 8B $0.15 in / $0.15 out, Titan Text Embeddings v2 $0.02 in.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from simcore.agent import AgentConfig, PersonaBlockCache
from simcore.agent import turns as agent_turns
from simcore.brief import load_brief
from simcore.elicitation import anchor_hash, load_anchor_version
from simcore.inference import ExecutionSettings, InferenceClient
from simcore.population import build
from simcore.ports.hf import HfCoresetSource, MissingShard, default_cache_dir
from simcore.runner import run
from simcore.schemas import (
    Completion,
    DistributionThresholds,
    PopulationParameters,
    RunConfig,
    TracePartition,
    VerbatimGrouping,
    canonical_hash,
)
from simcore.trace import TraceStore
from simcore.world import World, WorldConfig

ROOT = Path(__file__).resolve().parents[3]
REPO = "MatrAIx2026/MatrAIx_Persona_1M_Public_Release"
SOURCES = ("stackoverflow",)
CHAT = "mistral.ministral-3-8b-instruct"
EMBED = "amazon.titan-embed-text-v2:0"
# Per million tokens, AWS Pricing API, us-east-1 standard on-demand, 2026-09-18.
PRICES = {CHAT: (0.15, 0.15), EMBED: (0.02, 0.0)}


def shards_holding(cache: Path) -> list[str]:
    """Which cached shards carry Stack Overflow rows, read from each shard's own `source` column."""
    import pyarrow.parquet as pq

    manifest = json.loads((cache / "manifest.json").read_text())
    found = []
    for entry in manifest["files"]:
        path = cache / entry["path"]
        if path.is_file() and set(SOURCES) & set(pq.read_table(path, columns=["source"])["source"].to_pylist()):
            found.append(entry["path"])
    return found


class Metered:
    """The real client, wrapped to meter what the run spent per role — the trace records the
    same costs, and these totals are the cross-check on them."""

    def __init__(self, client: InferenceClient) -> None:
        self.client = client
        self.tokens: Counter = Counter()
        self.calls: Counter = Counter()
        self.failures: Counter = Counter()

    @property
    def served_models(self):
        return self.client.served_models

    @property
    def pins(self):
        return self.client.pins

    def complete(self, requests):
        outcomes = self.client.complete(requests)
        for outcome in outcomes:
            self.calls["chat"] += 1
            billed = (outcome.cost, *outcome.discarded_costs) if isinstance(outcome, Completion) else outcome.costs
            for cost in billed:
                self.tokens[f"{cost.role.value}_in"] += cost.input_tokens
                self.tokens[f"{cost.role.value}_out"] += cost.output_tokens
            if not isinstance(outcome, Completion):
                self.failures[outcome.kind.value] += 1
        return outcomes

    def embed(self, texts):
        result = self.client.embed(texts)
        self.calls["embed"] += 1
        for cost in result.costs:
            self.tokens["embed_in"] += cost.input_tokens
        return result

    @property
    def model_id(self):
        return self.client.model_id

    def spend(self) -> float:
        chat_in, chat_out = PRICES[CHAT]
        embed_in, _ = PRICES[EMBED]
        chat = (self.tokens["tier_a_in"] + self.tokens["tier_b_in"]) * chat_in
        chat += (self.tokens["tier_a_out"] + self.tokens["tier_b_out"]) * chat_out
        return round((chat + self.tokens["embed_in"] * embed_in) / 1e6, 6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personas", type=int, default=40)
    parser.add_argument("--ticks", type=int, default=4)
    parser.add_argument("--seed", type=int, default=4021)
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--channel", default="survey_room")
    parser.add_argument("--trace-root", type=Path, default=Path("/tmp/consumersim-real-study"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    cache = default_cache_dir(REPO)
    shards = shards_holding(cache)
    if not shards:
        raise MissingShard(f"no cached shard carries {list(SOURCES)}; fetch the release into {cache}")

    pack = load_brief(ROOT / "examples" / "code_review_ai.yaml", ROOT / "ontologies")
    coreset = HfCoresetSource(cache_dir=cache, shards=shards, sources=SOURCES)

    pins = {
        "tier_a": {"model_id": CHAT, "serves": [CHAT], "price": {"input_per_million": 0.15, "output_per_million": 0.15}},
        "tier_b": {"model_id": CHAT, "serves": [CHAT], "price": {"input_per_million": 0.15, "output_per_million": 0.15}},
        "embed": {"model_id": EMBED, "serves": [EMBED], "price": {"input_per_million": 0.02, "output_per_million": 0.0}},
    }
    from simcore.schemas import ModelPins

    client = InferenceClient(ModelPins.model_validate(pins), ExecutionSettings.from_environment())
    metered = Metered(client)

    started = time.time()
    parameters = PopulationParameters(
        distribution_gates=DistributionThresholds(significance_level=0.001, similarity_threshold=0.6)
    )
    built = build(pack, args.personas, args.seed, coreset=coreset, inference=metered, embed=metered, parameters=parameters)
    population = built.population
    build_seconds = round(time.time() - started, 1)

    variant = {
        "variant_id": "codepilot_base",
        "name": pack.brief.product.name,
        "description": pack.brief.product.description,
        "emphasized_claims": [claim.id for claim in pack.brief.claims[:1]],
    }
    scenario = {
        "variant": variant,
        "price": pack.brief.price.model_dump(mode="json"),
        "audience_weights": {audience.name: weight for audience, weight in _weights(pack)},
        "tick_unit": "day",
        "horizon_ticks": args.ticks,
        "interventions": [],
        "exposure_budget": 3,
    }
    config = RunConfig.model_validate(
        {
            "run_id": f"run-{'0' * 24}1a",
            "pins": pins,
            "budget": {"max_cost": args.budget, "currency": "USD"},
            "brief_hash": canonical_hash(pack.brief),
            "ontology_hash": canonical_hash(pack.ontology),
            "population_hash": population.manifest.population_hash,
            "graph_hash": population.manifest.graph_hash,
            "scenarios": [scenario],
            "seeds": [args.seed],
            "template_hashes": {"persona_turn": "ab" * 32, "persona_turn_strict": "cd" * 32, "persona_reflection": "ef" * 32, "persona_probe": "12" * 32},
            # The header refuses a partition whose ontology names an anchor set the run does not
            # pin, so the pin is stated. Scoring is still refused: the version's check failed, and
            # the gate reads that record rather than this pin (ADR 0029), so intent goes unscored
            # and the verbatim is kept with its failure (ADR 0032). That is the path under test.
            "anchor_set_hashes": {
                pack.ontology.anchor_sets["purchase_intent"]: anchor_hash(
                    load_anchor_version(ROOT / "anchors" / "purchase_intent" / "v1.json")
                )
            },
        }
    )

    store = TraceStore(args.trace_root)
    headers: dict = {}
    blocks = PersonaBlockCache()
    agent_config = AgentConfig(
        run_seed=args.seed,
        horizon_ticks=args.ticks,
        template_id="persona_turn",
        probe_share=0.1,
        probe_every_ticks=2,
    )

    class Sink:
        def write(self, events):
            self.store_write(events)

        def __init__(self, store, run_id):
            self._store, self._run_id = store, run_id

        def store_write(self, events):
            self._store.write(events)

        def finalize(self, world_id):
            self._store.finalize(world_id)

        def events_for(self, world_id):
            try:
                return self._store.read_live(self._run_id, world_id)
            except Exception:
                return ()

        def all_events(self):
            out = []
            for world_id in self._store.world_ids(self._run_id):
                out.extend(self.events_for(world_id))
            return tuple(out)

    def world_factory(header):
        headers[header.world_id] = header
        store.create_world(config.run_id, header)
        return World(header, population=population, config=WorldConfig(platform=args.channel))

    def agent_fn(jobs, plan=None):
        return agent_turns(jobs, chat=metered, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=metered)

    ran = time.time()
    result = run(
        config,
        pack=pack,
        population=population,
        trace=Sink(store, config.run_id),
        registry=store.registry,
        world_factory=world_factory,
        agent_fn=agent_fn,
    )
    run_seconds = round(time.time() - ran, 1)

    world_id = result.outcomes[0].world_id
    view = store.view(config.run_id, world_id)
    events = view.events(__import__("simcore.schemas", fromlist=["EventFilter"]).EventFilter())
    recorded = store.read_live(config.run_id, world_id)
    partition = TracePartition.model_validate(
        {"header": headers[world_id].model_dump(mode="json"), "events": [event.model_dump(mode="json") for event in recorded]}
    )
    entry = store.registry.entry(config.run_id)
    kinds = Counter(event.payload.kind for event in events)
    verbatims = [record for group in view.verbatims(VerbatimGrouping.PERSONA) for record in group.records]
    intents = [
        event.payload.turn.reaction.intent
        for event in events
        if event.payload.kind == "turn" and event.payload.turn.reaction.intent is not None
    ]
    unscored = [
        event.payload.turn.reaction.elicitation_failure
        for event in events
        if event.payload.kind == "turn" and getattr(event.payload.turn.reaction, "elicitation_failure", None) is not None
    ]

    report = {
        "study": "code-review AI on Stack Overflow rows",
        "chat_model": CHAT,
        "embed_model": EMBED,
        "served": {role: sorted(models) for role, models in metered.served_models.items()},
        "personas": len(population.personas),
        "source_mix": dict(population.gate_report.source_mix),
        "gate_evidence": population.gate_report.evidence.value,
        "gates_overall": population.gate_report.overall,
        "ticks": args.ticks,
        "channel": args.channel,
        "run_status": result.status.value,
        "world_outcomes": [
            {"world": outcome.world_id, "status": outcome.status.value, "last_closed_tick": outcome.last_closed_tick, "rungs": list(outcome.rungs)}
            for outcome in result.outcomes
        ],
        "events_recorded": len(recorded),
        "events_visible": len(events),
        "event_kinds": dict(kinds),
        "partition_validates": len(partition.events),
        "finalized_parquet": (args.trace_root / "runs" / config.run_id / world_id / "events.parquet").exists(),
        "verbatims": len(verbatims),
        "verbatim_sample": [record.text for record in verbatims[:5]],
        "intents_scored": len(intents),
        "intents_unscored": len(unscored),
        "unscored_reason": unscored[0].kind.value if unscored else None,
        "probes": sum(1 for event in events if event.payload.kind == "probe"),
        "probe_disagreement": _probe_rate(events),
        "beliefs_points_first_persona": [point.tick for point in view.beliefs(sorted(p.persona_id for p in population.personas)[0]).points],
        "calls": dict(metered.calls),
        "tokens": dict(metered.tokens),
        "failures": dict(metered.failures),
        "registry": {
            "status": entry.status.value,
            "recorded_cost": entry.recorded_cost,
            "discarded_ticks": entry.discarded_ticks,
            "engine_version": entry.engine_version,
        },
        "spend_usd_metered": metered.spend(),
        "seconds": {"population_build": build_seconds, "study_run": run_seconds},
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


def _weights(pack):
    for audience in pack.brief.audiences:
        yield audience, audience.share


def _probe_rate(events) -> float | None:
    results = [event.payload.result for event in events if event.payload.kind == "probe"]
    answered = [answer for result in results for answer in result.answers if answer.answered]
    if not answered:
        return None
    return round(sum(not answer.agreed for answer in answered) / len(answered), 3)


if __name__ == "__main__":
    main()
