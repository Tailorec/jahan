"""Read a finished education-savings study back out of its recorded trace, and test the expectation that
was written down before the run.

Every number here is computed from the run's own events and personas by this script; none of it is an engine
output beyond the recorded per-turn purchase-intent distributions. The engine's own digest is quoted beside it.

    uv run python docs/evaluations/2026-09-20-education-savings/analyse.py runs/<run_id>

Expectation, fixed before the run (see examples/education_savings_app_persona1m.yaml):
  1. parents_of_young_kids show the highest stated purchase intent of the three audiences  (confident)
  2. early_career versus retirees: no directional prediction                               (exploratory)
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from simcore.schemas import EventFilter
from simcore.trace import TraceStore

LIFE_STAGE_AUDIENCE = {
    "Parent of young kids": "parents_of_young_kids",
    "Early career": "early_career",
    "Retirement": "retirees",
}
AUDIENCES = ("parents_of_young_kids", "early_career", "retirees")
BOOTSTRAPS = 4000
SEED = 20260920


def top_two_box(pmf) -> float:
    return float(pmf[3] + pmf[4])


def expected_rating(pmf) -> float:
    return float(sum((index + 1) * mass for index, mass in enumerate(pmf)))


def interval(values: list[float], rng: random.Random) -> tuple[float, float, float]:
    """Mean and a 95% percentile bootstrap interval, resampling personas."""
    n = len(values)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(BOOTSTRAPS))
    return statistics.fmean(values), means[int(0.025 * BOOTSTRAPS)], means[int(0.975 * BOOTSTRAPS) - 1]


def difference(a: list[float], b: list[float], rng: random.Random) -> tuple[float, float, float]:
    """Mean(a) - mean(b), with a bootstrap interval resampling each group's personas independently."""
    if not a or not b:
        return float("nan"), float("nan"), float("nan")
    diffs = sorted(
        statistics.fmean(rng.choices(a, k=len(a))) - statistics.fmean(rng.choices(b, k=len(b)))
        for _ in range(BOOTSTRAPS)
    )
    return statistics.fmean(a) - statistics.fmean(b), diffs[int(0.025 * BOOTSTRAPS)], diffs[int(0.975 * BOOTSTRAPS) - 1]


def main(run_dir: Path) -> None:
    rng = random.Random(SEED)
    personas = {p["persona_id"]: p for p in json.loads((run_dir / "personas.json").read_text())["personas"]}
    audience_of = {
        pid: LIFE_STAGE_AUDIENCE.get(p["conditioning"].get("life_stage")) for pid, p in personas.items()
    }
    population = Counter(audience_of.values())

    store = TraceStore(run_dir / "trace")
    run_id = run_dir.name
    worlds = list(store.world_ids(run_id))

    # answers[world][audience][persona] -> list of (top_two_box, expected_rating, verbatim)
    answers: dict[str, dict[str, dict[str, list]]] = {}
    unscored: Counter = Counter()
    for world in worlds:
        view = store.view(run_id, world)
        per_audience: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for event in view.events(EventFilter()):
            if event.payload.kind != "turn":
                continue
            reaction = event.payload.turn.reaction
            audience = audience_of.get(event.persona_id)
            if reaction.intent is None:
                unscored[world] += 1
                continue
            per_audience[audience][event.persona_id].append(
                (top_two_box(reaction.intent.pmf), expected_rating(reaction.intent.pmf), reaction.verbatim)
            )
        answers[world] = per_audience

    results: dict = {"run_id": run_id, "worlds": worlds, "population_by_audience": dict(population),
                     "unscored_turns": dict(unscored), "per_world": {}, "pooled": {}}

    def persona_means(per_persona: dict[str, list], column: int) -> list[float]:
        return [statistics.fmean(row[column] for row in rows) for rows in per_persona.values()]

    for world in worlds:
        block = {}
        for audience in AUDIENCES:
            per_persona = answers[world].get(audience, {})
            ttb = persona_means(per_persona, 0)
            mean, low, high = interval(ttb, rng)
            block[audience] = {
                "personas_answering": len(per_persona),
                "of_population": population.get(audience, 0),
                "turns": sum(len(rows) for rows in per_persona.values()),
                "mean_top_two_box": round(mean, 4), "ci95": [round(low, 4), round(high, 4)],
                "mean_expected_rating": round(statistics.fmean(persona_means(per_persona, 1)), 4) if per_persona else None,
            }
        parents = persona_means(answers[world].get("parents_of_young_kids", {}), 0)
        for other in ("early_career", "retirees"):
            d, low, high = difference(parents, persona_means(answers[world].get(other, {}), 0), rng)
            block[f"parents_minus_{other}"] = {"difference": round(d, 4), "ci95": [round(low, 4), round(high, 4)]}
        results["per_world"][world] = block

    # Pooled across both worlds: each persona's mean over every answer it gave in any world.
    pooled_rows: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for world in worlds:
        for audience, per_persona in answers[world].items():
            for pid, rows in per_persona.items():
                pooled_rows[audience][pid].extend(rows)
    for audience in AUDIENCES:
        ttb = persona_means(pooled_rows.get(audience, {}), 0)
        mean, low, high = interval(ttb, rng)
        verbatims = [row[2] for rows in pooled_rows.get(audience, {}).values() for row in rows if row[2]]
        sources = Counter(personas[pid]["source"] for pid in pooled_rows.get(audience, {}))
        results["pooled"][audience] = {
            "personas_answering": len(pooled_rows.get(audience, {})),
            "mean_top_two_box": round(mean, 4), "ci95": [round(low, 4), round(high, 4)],
            "distinct_verbatims": len(set(verbatims)), "verbatims": len(verbatims),
            "respondent_sources": dict(sources),
            "verbatim_sample": verbatims[:3],
        }
    parents = persona_means(pooled_rows.get("parents_of_young_kids", {}), 0)
    for other in ("early_career", "retirees"):
        d, low, high = difference(parents, persona_means(pooled_rows.get(other, {}), 0), rng)
        results["pooled"][f"parents_minus_{other}"] = {"difference": round(d, 4), "ci95": [round(low, 4), round(high, 4)]}

    # Does the expectation hold in each world, and pooled?
    def holds(block: dict) -> bool:
        return all(block[f"parents_minus_{o}"]["ci95"][0] > 0 for o in ("early_career", "retirees"))

    results["expectation_1_parents_highest"] = {
        "per_world": {w: holds(results["per_world"][w]) for w in worlds},
        "pooled": holds(results["pooled"]),
    }

    out = Path(__file__).resolve().parent / "results.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")

    print(f"run {run_id} · worlds {worlds} · unscored turns {dict(unscored)}")
    print(f"population by audience: {dict(population)}")
    for world in worlds:
        print(f"\nworld {world}")
        for audience in AUDIENCES:
            b = results["per_world"][world][audience]
            print(f"  {audience:22s} answered {b['personas_answering']:3d}/{b['of_population']:3d} personas, "
                  f"{b['turns']:3d} turns   top-two-box {b['mean_top_two_box']:.3f}  95% CI {b['ci95']}")
        for other in ("early_career", "retirees"):
            d = results["per_world"][world][f"parents_minus_{other}"]
            print(f"  parents - {other:13s} {d['difference']:+.3f}  95% CI {d['ci95']}")
    print("\npooled across worlds")
    for audience in AUDIENCES:
        b = results["pooled"][audience]
        print(f"  {audience:22s} {b['personas_answering']:3d} personas  top-two-box {b['mean_top_two_box']:.3f}  "
              f"95% CI {b['ci95']}  distinct verbatims {b['distinct_verbatims']}/{b['verbatims']}  sources {b['respondent_sources']}")
    print(f"\nexpectation 1 (parents highest): {results['expectation_1_parents_highest']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
