"""Regenerate the study M10 reconciles against, offline and deterministically.

A small protein-water study — synthetic population, stub survey world, stub agent with
half its turns scored for purchase intent — run through the real `runner` and the real
trace store, then digested end to end by `simcore.analysis`. Every number below is
recomputed from the trace by `digest`, never gathered beside it.

Run: `uv run python docs/evaluations/m10-analysis/regen_study.py` (no network, no keys).
Outputs (committed): `partitions/world-<id>.json`, `population.json`, `digest-report.json`.

Caveats, stated plainly: the chat and embedding models are stubs, so the report's
turn counts, action mix, belief movement and word-of-mouth reach demonstrate derivation,
not a measurement; the intent masses are recorded stub distributions, not elicitation
output, so adoption is a plumbing check rather than a finding. The trust level stays
`UNCALIBRATED`.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

N_PERSONAS = 40
POPULATION_SEED = 4021
SEEDS = [4021, 917731]
EMBED_PIN = "fake/embed-1"

_SSR_SETS = [
    (0.05, 0.10, 0.20, 0.30, 0.35),
    (0.06, 0.10, 0.19, 0.30, 0.35),
    (0.04, 0.11, 0.20, 0.30, 0.35),
    (0.05, 0.09, 0.21, 0.30, 0.35),
    (0.05, 0.10, 0.20, 0.31, 0.34),
    (0.05, 0.10, 0.20, 0.29, 0.36),
]
_SSR_SIMS = [
    (0.55, 0.60, 0.70, 0.80, 0.85),
    (0.56, 0.60, 0.69, 0.80, 0.85),
    (0.54, 0.61, 0.70, 0.80, 0.85),
    (0.55, 0.59, 0.71, 0.80, 0.85),
    (0.55, 0.60, 0.70, 0.81, 0.84),
    (0.55, 0.60, 0.70, 0.79, 0.86),
]


def _ulid(n: int) -> str:
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    digits = []
    for _ in range(26):
        n, remainder = divmod(n, 32)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


def _ssr(verbatim: str, n: int) -> dict:
    shift = round((n % 3) * 0.02, 4)
    sets = [tuple(round(v + (shift if i == 3 else -shift if i == 4 else 0.0), 4) for i, v in enumerate(s))
            for s in _SSR_SETS]
    return {
        "response_text": verbatim,
        "per_set_pmfs": sets,
        "per_set_similarities": [list(s) for s in _SSR_SIMS],
        "construct_id": "purchase_intent",
        "category": "beverage_protein",
        "anchor_set_id": "purchase-intent-v1",
        "anchor_version": "1.0.0",
        "embed_model_id": EMBED_PIN,
        "temperature": 1.0,
        "epsilon": 0.0,
    }


class SurveyWorld:
    """Survey room: tick 0 publishes the concept, later ticks present it to every persona."""

    def __init__(self, header, stimulus_text: str = "Clear protein water with 20g protein") -> None:
        from simcore.schemas import Stimulus

        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({
            "stimulus_id": f"st-{_ulid(11)}", "tick": 0, "kind": "concept", "text": stimulus_text})

    def reset(self):
        from simcore.schemas import WorldDelta

        return WorldDelta.model_validate(
            {"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate({
                "impression_id": f"im-{_ulid(500 + tick * 1000 + idx)}",
                "persona_id": pid, "channel": "survey_room", "tick": tick,
                "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}],
            })
            view = View.model_validate(
                {"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            presentations.append(Presentation.model_validate(
                {"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate(
            {"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _agent(jobs) -> tuple:
    from simcore.schemas import CompletedTurn, Turn

    outcomes = []
    for job in jobs:
        impression = job.presentation.impression
        tick, pid = impression.tick, impression.persona_id
        n = tick * 1000 + len(outcomes)
        subject = next(iter(impression.stimulus_ids))
        scored = int(pid[-1], 36) % 2 == 0
        verbatim = "I would try it after training" if scored else "Not for me, too pricey"
        reaction: dict = {
            "reaction_id": f"rc-{_ulid(900 + n)}",
            "subject_stimulus_id": subject,
            "action": "answer",
            "verbatim": verbatim,
            "belief_change": {"dimensions": {"value": 0.1 if scored else -0.05}, "claim_credence": {"C1": 0.1}},
        }
        if scored:
            reaction["intent"] = _ssr(verbatim, n)
        else:
            reaction["elicitation_failure"] = {
                "kind": "numeric_answer", "detail": "the response carried a rating-like number",
                "response_text": verbatim, "construct_id": "purchase_intent",
            }
        turn = Turn.model_validate({
            "impression": impression.model_dump(mode="json"),
            "view": job.presentation.view.model_dump(mode="json"),
            "reaction": reaction,
        })
        outcomes.append(CompletedTurn.model_validate({
            "turn": turn.model_dump(mode="json"),
            "template_id": "persona_turn",
            "prompt_hash": "ab" * 32,
            "persona_block_hash": "cd" * 32,
            "belief_change": {"dimensions": {"value": 0.1 if scored else -0.05}, "claim_credence": {"C1": 0.1}},
            "costs": [],
        }))
    return tuple(outcomes)


def run_study(trace_dir: Path):
    from simcore.brief import load_brief
    from simcore.population import build
    from simcore.ports.fake import FakeChat
    from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
    from simcore.runner import run
    from simcore.schemas import SCHEMA_VERSION, PartitionHeader, RunConfig, Scenario, canonical_hash
    from simcore.trace import TraceStore

    pack = load_brief(ROOT / "examples" / "protein_water.yaml", ROOT / "ontologies")
    shape = SyntheticShape(
        {
            "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
            "sex": AttributeShape(("female", "male")),
            "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
            "diet_protein_focus": AttributeShape(("low", "medium", "high")),
        },
        rows=4000,
    )
    population = build(pack, N_PERSONAS, POPULATION_SEED,
                       coreset=SyntheticCoresetSource(shape, seed=11), inference=FakeChat()).population
    scenario = Scenario.model_validate({
        "variant": {"variant_id": "v1baseline", "name": "Baseline", "description": "Baseline concept",
                    "emphasized_claims": ["C1"]},
        "price": {"amount": 2.49, "currency": "USD"},
        "audience_weights": {"gym_regulars": 0.6, "protein_dieters": 0.4},
        "tick_unit": "day",
        "horizon_ticks": 3,
        "interventions": [],
    })
    config = RunConfig.model_validate({
        "run_id": "run-00000000000000000000000001",
        "pins": {"tier_a": "fake/tier-a-1", "tier_b": "fake/tier-b-1", "embed": EMBED_PIN},
        "budget": {"max_cost": 20.0, "currency": "USD"},
        "brief_hash": canonical_hash(pack.brief),
        "ontology_hash": canonical_hash(pack.ontology),
        "population_hash": population.population_hash,
        "graph_hash": population.graph.graph_hash if population.graph is not None else None,
        "scenarios": [scenario.model_dump(mode="json")],
        "seeds": SEEDS,
        "template_hashes": {"persona_turn": "ab" * 32},
        "anchor_set_hashes": {"purchase-intent-v1": "ef" * 32},
    })
    import shutil

    # The trace dir is script-owned scratch: set ordering in JSON serialisation is not
    # stable across processes, so a rerun starts fresh rather than resuming half-identical state.
    if trace_dir.exists():
        shutil.rmtree(trace_dir)
    store = TraceStore(trace_dir)
    for seed in config.seeds:
        header = PartitionHeader.model_validate({
            "contract_version": SCHEMA_VERSION,
            "config": config.model_dump(mode="json"),
            "pack": pack.model_dump(mode="json"),
            "population": population.manifest.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
            "replicate_seed": seed,
        })
        store.create_world(config.run_id, header)
    result = run(config, pack=pack, population=population, trace=store, registry=store.registry,
                 world_factory=SurveyWorld, agent_fn=_agent)
    assert result.status.value == "completed", result.status
    return store, config, pack, population, scenario


def analyse(store, config, pack, population, scenario) -> dict:
    from simcore.analysis import (
        cluster_objections,
        detect_anomalies,
        digest,
        findings,
        spread,
        trust_statement,
    )
    from simcore.ports.fake import FakeEmbed
    from simcore.schemas import EventFilter, TracePartition, canonical_hash
    from simcore.trace.finalize import read_finalized_events

    scenario_hash = canonical_hash(scenario)
    pin = config.pins.embed.model_id
    worlds = []
    for seed, wid in zip(config.seeds, store.registry.entry(config.run_id).world_ids):
        view = store.view(config.run_id, wid)
        events = view.events(EventFilter())
        turns = [e for e in events if e.payload.kind == "turn"]
        beside = {
            "turns": len(turns),
            "actions": dict(sorted(Counter(e.payload.turn.reaction.action.value for e in turns).items())),
            "scored": sum(1 for e in turns if e.payload.turn.reaction.intent is not None),
            "wom": sum(e.count for e in view.edges()),
        }
        result = digest(view, scenario=scenario, population=population, seed=seed, pinned_embed_model=pin)
        assert result.scenario_hash == scenario_hash and result.world_id == wid and result.seed == seed
        assert result.turn_count == beside["turns"]
        assert dict(result.action_mix) == beside["actions"]
        assert result.turn_count - result.turns_without_intent == beside["scored"]
        assert result.wom_deliveries == beside["wom"]
        if result.audience_pmfs:
            hand = sum(result.audience_shares[n] * (result.audience_pmfs[n][3] + result.audience_pmfs[n][4])
                       for n in result.audience_pmfs)
            assert abs(result.adoption - hand) < 1e-9
        worlds.append((seed, wid, result, beside, view))

    summary = spread([result for _, _, result, _, _ in worlds])
    report_worlds = []
    for seed, wid, result, beside, view in worlds:
        found = findings(view, embed=FakeEmbed(model_id=pin), pinned_embed_model=pin, seed=seed)
        for finding in found:
            view.resolve(tuple(finding.evidence_trace_ids))
        detected = detect_anomalies(view, digest=result, replicate_spread=summary.adoption_spread)
        clusters = cluster_objections(view, embed=FakeEmbed(model_id=pin), pinned_embed_model=pin)
        report_worlds.append({
            "seed": seed, "world_id": wid, "beside_trace": beside,
            "digest": json.loads(result.model_dump_json()),
            "findings": [json.loads(f.model_dump_json()) for f in found],
            "clusters": [json.loads(c.model_dump_json()) for c in clusters],
            "anomalies": [json.loads(a.model_dump_json()) for a in detected.anomalies],
            "unmeasured": [json.loads(u.model_dump_json()) for u in detected.unmeasured],
        })
    return {
        "run_id": config.run_id,
        "scenario_hash": scenario_hash,
        "worlds": report_worlds,
        "spread": json.loads(summary.model_dump_json()),
        "trust": json.loads(trust_statement().model_dump_json()),
    }


def main() -> None:
    from simcore.schemas import TracePartition

    trace_dir = HERE / "trace"
    store, config, pack, population, scenario = run_study(trace_dir)
    digest_report = analyse(store, config, pack, population, scenario)

    partitions_dir = HERE / "partitions"
    partitions_dir.mkdir(exist_ok=True)
    for seed, wid in zip(config.seeds, store.registry.entry(config.run_id).world_ids):
        from simcore.trace.finalize import read_finalized_events

        partition = TracePartition.model_validate({
            "header": {
                "contract_version": "1.0.0",
                "config": config.model_dump(mode="json"),
                "pack": pack.model_dump(mode="json"),
                "population": population.manifest.model_dump(mode="json"),
                "scenario": scenario.model_dump(mode="json"),
                "replicate_seed": seed,
            },
            "events": [e.model_dump(mode="json") for e in read_finalized_events(trace_dir, config.run_id, wid)],
        })
        assert partition.header.world_id == wid
        (partitions_dir / f"world-{wid}.json").write_text(partition.model_dump_json())
    (HERE / "population.json").write_text(population.model_dump_json())
    (HERE / "digest-report.json").write_text(json.dumps(digest_report, indent=2, sort_keys=True))

    for world in digest_report["worlds"]:
        d = world["digest"]
        print(f"seed {world['seed']} world {world['world_id']}: "
              f"turns={d['turn_count']} scored={world['beside_trace']['scored']} "
              f"adoption={d['adoption']} findings={len(world['findings'])} "
              f"anomalies={len(world['anomalies'])} unmeasured={len(world['unmeasured'])}")
    spread = digest_report["spread"]
    print(f"spread={spread['adoption_spread']} "
          f"rung_mixed={spread['rung_mixed']} "
          f"trust={digest_report['trust']['level']}")


if __name__ == "__main__":
    main()
