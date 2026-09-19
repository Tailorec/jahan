"""The conditioning effect, measured against a real model (M6 phase 3).

Two arms over the same personas, the same stimulus, the same question, the same pinned scale
and the same seeds. The only difference is what the persona block says:

  conditioned    — the block the ontology selects, describing that person
  unconditioned  — one non-informative sentence, identical for everyone

The block is replaced through `PersonaBlockCache.block_for`, the seam the runner already owns,
so nothing in the engine is modified and both arms travel the same path. The block stays
non-empty because a turn cannot proceed unconditioned (the invariant M6 exists to own); the
third arm below shows that refusal on the real path, and costs nothing because it never
dispatches.

The literature reports that unconditioned personas answer more optimistically and with a
narrower spread. That is what this measures.

Run from the repository root with a proxy serving the pinned models.
"""

from __future__ import annotations

import json
import resource
import statistics
import sys
import types
from pathlib import Path

resource.setrlimit(resource.RLIMIT_AS, (int(7e9), int(7e9)))

from simcore.agent import AgentConfig, PersonaBlockCache, turns  # noqa: E402
from simcore.agent._prompt import hash_text  # noqa: E402
from simcore.cli._study import prepare_study  # noqa: E402
from simcore.schemas import CompletedTurn, PartitionHeader, TurnJob  # noqa: E402
from simcore.world import World, WorldConfig  # noqa: E402

HERE = Path(__file__).resolve().parent
PERSONAS = int(sys.argv[1]) if len(sys.argv) > 1 else 150
UNCONDITIONED_BLOCK = "You are a person."


class ConstantBlocks(PersonaBlockCache):
    """Every persona told the same thing: the unconditioned arm's whole difference."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def block_for(self, persona, ontology):  # noqa: ANN001 - mirrors the cache it replaces
        return self._text, hash_text(self._text)


def study_args(**overrides):
    args = {
        "fake": False, "coreset_fixture": None, "population_seed": 4021,
        "model": "amazon.nova-micro-v1:0", "embed_model": "amazon.titan-embed-text-v2:0",
        "price_chat_in": 0.035, "price_chat_out": 0.14, "price_embed_in": 0.02, "cache": None,
        "shards": "0000,0004,0005", "sources": "wiki,gss,amazon,stackoverflow",
        "anchor_version": ["purchase_intent=v2"], "elicits": "purchase",
        "tick_unit": "day", "horizon": 2,
    }
    args.update(overrides)
    return types.SimpleNamespace(**args)


def top_two_box(pmf) -> float:
    return float(pmf[3] + pmf[4])


def expected_rating(pmf) -> float:
    return float(sum((index + 1) * value for index, value in enumerate(pmf)))


def measure(name: str, outcomes, jobs) -> dict:
    """What an arm answered: the distribution over personas, not one persona's answer."""
    scored = [o for o in outcomes if isinstance(o, CompletedTurn) and o.turn.reaction.intent is not None]
    ttbs = [top_two_box(o.turn.reaction.intent.pmf) for o in scored]
    ratings = [expected_rating(o.turn.reaction.intent.pmf) for o in scored]
    verbatims = [o.turn.reaction.verbatim for o in scored if o.turn.reaction.verbatim]
    failures = [o for o in outcomes if not isinstance(o, CompletedTurn)]
    return {
        "arm": name,
        "jobs": len(jobs),
        "scored": len(scored),
        "failed": len(failures),
        "failure_kinds": sorted({getattr(o, "kind").value for o in failures}) if failures else [],
        "mean_top_two_box": round(statistics.fmean(ttbs), 4) if ttbs else None,
        "sd_top_two_box": round(statistics.pstdev(ttbs), 4) if len(ttbs) > 1 else None,
        "mean_expected_rating": round(statistics.fmean(ratings), 4) if ratings else None,
        "sd_expected_rating": round(statistics.pstdev(ratings), 4) if len(ratings) > 1 else None,
        "distinct_answers": len({tuple(round(v, 6) for v in o.turn.reaction.intent.pmf) for o in scored}),
        "distinct_verbatims": len(set(verbatims)),
        "verbatim_sample": verbatims[:3],
    }


def main() -> None:
    args = study_args()
    handles = prepare_study(
        brief_path=Path("examples/protein_water_persona1m.yaml"),
        ontologies_dir=Path("ontologies"), anchors_dir=Path("anchors"),
        out_dir=HERE / "scratch", run_id=None, n=500, population_seed=4021,
        scenarios=None, seeds=[4021], budget=5.0, args=args,
    )
    scenario = handles.config.scenarios[0]
    header = PartitionHeader.model_validate({
        "contract_version": handles.config.contract_version if hasattr(handles.config, "contract_version") else "1.0.0",
        "config": handles.config.model_dump(mode="json"),
        "pack": handles.pack.model_dump(mode="json"),
        "population": handles.population.manifest.model_dump(mode="json"),
        "scenario": scenario.model_dump(mode="json"),
        "replicate_seed": 4021,
    })
    world = World(header, population=handles.population, config=WorldConfig(platform="survey_room"))
    # `reset` opens the world and publishes its stimuli; personas are shown them from tick one.
    opening = world.reset()
    delta = world.step(1, [])
    published = {s.stimulus_id: s.text for s in (*opening.published, *delta.published)}
    personas = {p.persona_id: p for p in handles.population.personas}

    presentations = sorted(delta.presentations, key=lambda p: p.impression.persona_id)[:PERSONAS]
    print(f"published {len(published)} stimuli; presentations at tick 1: "
          f"{len(delta.presentations)}, using {len(presentations)}")

    def build_jobs() -> list[TurnJob]:
        jobs = []
        for presentation in presentations:
            pid = presentation.impression.persona_id
            persona = personas[pid]
            jobs.append(TurnJob.model_validate({
                "persona": persona.model_dump(mode="json"),
                "state": {"persona_id": pid, "beliefs": persona.baseline_beliefs.model_dump(mode="json")},
                "presentation": presentation.model_dump(mode="json"),
                "task": "purchase",
            }))
        return jobs

    results = []
    for name, blocks in (("conditioned", PersonaBlockCache()),
                         ("unconditioned", ConstantBlocks(UNCONDITIONED_BLOCK))):
        jobs = build_jobs()
        outcomes = turns(
            jobs, chat=handles.chat, config=handles.agent_config, ontology=handles.pack.ontology,
            blocks=blocks, embed=handles.embed, stimulus_texts=published,
        )
        summary = measure(name, outcomes, jobs)
        results.append(summary)
        print(f"{name}: scored {summary['scored']}/{summary['jobs']} "
              f"mean ttb {summary['mean_top_two_box']} sd {summary['sd_top_two_box']} "
              f"distinct answers {summary['distinct_answers']}")

    # The invariant itself, on the real path: an empty block refuses before any call is made.
    refused = turns(build_jobs()[:3], chat=handles.chat, config=handles.agent_config,
                    ontology=handles.pack.ontology, blocks=ConstantBlocks(""),
                    embed=handles.embed, stimulus_texts=published)
    refusal = {
        "jobs": len(refused),
        "completed": sum(1 for o in refused if isinstance(o, CompletedTurn)),
        "kinds": sorted({getattr(o, "kind").value for o in refused if not isinstance(o, CompletedTurn)}),
    }
    print(f"empty block: {refusal}")

    conditioned, unconditioned = results[0], results[1]
    report = {
        "personas": len(presentations),
        "model": args.model,
        "embed_model": args.embed_model,
        "anchor_version": "purchase_intent/v2",
        "population_hash": handles.population.manifest.population_hash,
        "unconditioned_block": UNCONDITIONED_BLOCK,
        "arms": results,
        "empty_block_refusal": refusal,
        "difference": {
            "top_two_box": round((unconditioned["mean_top_two_box"] or 0) - (conditioned["mean_top_two_box"] or 0), 4),
            "expected_rating": round((unconditioned["mean_expected_rating"] or 0) - (conditioned["mean_expected_rating"] or 0), 4),
            "sd_ratio_unconditioned_over_conditioned": (
                round((unconditioned["sd_top_two_box"] or 0) / conditioned["sd_top_two_box"], 4)
                if conditioned["sd_top_two_box"] else None
            ),
        },
    }
    (HERE / "conditioning.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["difference"], indent=2))


if __name__ == "__main__":
    main()
