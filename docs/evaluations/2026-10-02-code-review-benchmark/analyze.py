"""Compare the concept test's simulated purchase intent with Stack Overflow respondents' real answer.

Truth: `ai_task_code_review`, read from the corpus by each persona's row with the engine's own decoder; graded
measured when the survey recorded it, extracted when a model inferred it from other answers. Never shown to a
persona. Yardstick: a demographic baseline that predicts the truth from attributes the personas *did* see, built
only from Stack Overflow rows outside the sample.

Usage: python analyze.py <run_id>   (from sim_engine/, with its .venv)
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from simcore.ports.hf import HfCoresetSource, default_cache_dir
from simcore.schemas import EventFilter, FieldOrigin
from simcore.trace import TraceStore

TRUTH = "ai_task_code_review"
# Using it now ranks above planning to; mostly above partly. "Not applicable" says nothing about intent.
RANK = {
    "Currently mostly AI-assisted": 5, "Currently partially AI-assisted": 4,
    "Plans mostly AI use": 3, "Plans partial AI use": 2, "Does not plan AI use": 1,
}
CELLS = (("age_bracket", "years_experience", "dev_role_archetype"), ("age_bracket", "years_experience"), ("years_experience",))
GROUPS = ("age_bracket", "years_experience", "region", "dev_role_archetype", "seniority", "demo_employment_status")


def simulated(run_dir: Path, run_id: str) -> dict[str, np.ndarray]:
    view = TraceStore(run_dir / "trace").view(run_id)
    pmfs = {}
    for event in view.events(EventFilter(kinds=("turn",))):
        turn = event.payload.turn
        if turn.impression.channel == "survey_room" and turn.reaction.intent is not None:
            pmfs[event.persona_id] = np.asarray(turn.reaction.intent.pmf, dtype=float)
    return pmfs


def main(run_id: str) -> None:
    run_dir = Path("runs") / run_id
    pmfs = simulated(run_dir, run_id)
    corpus = HfCoresetSource(cache_dir=default_cache_dir(), sources=["stackoverflow"])
    sample_rows = {pid.removeprefix("p-"): pid for pid in pmfs}
    decoded = {row.row_id: row for row in corpus.rows(sample_rows)}

    # The baseline's pool: every other Stack Overflow row with a measured answer, at most 30,000.
    pool_ids = [r for r in corpus.matching({}, present=[TRUTH, *CELLS[0]], sources=["stackoverflow"]) if r not in decoded]
    random.Random(4021).shuffle(pool_ids)
    pool = [row for row in corpus.rows(pool_ids[:30000])
            if row.values.get(TRUTH) in RANK and row.tiers.get(TRUTH, FieldOrigin.MEASURED) is FieldOrigin.MEASURED]
    means = [defaultdict(list) for _ in CELLS]
    for row in pool:
        for k, cell in enumerate(CELLS):
            means[k][tuple(row.values.get(a) for a in cell)].append(RANK[row.values[TRUTH]])
    overall = float(np.mean([RANK[r.values[TRUTH]] for r in pool]))

    def baseline(row) -> float:
        for k, cell in enumerate(CELLS):
            hits = means[k].get(tuple(row.values.get(a) for a in cell), [])
            if len(hits) >= 20:
                return float(np.mean(hits))
        return overall

    records = []
    for row_id, row in decoded.items():
        value = row.values.get(TRUTH)
        if value not in RANK:
            continue
        pmf = pmfs[sample_rows[row_id]]
        records.append({
            "measured": row.tiers.get(TRUTH, FieldOrigin.MEASURED) is FieldOrigin.MEASURED,
            "truth": RANK[value], "uses_now": RANK[value] >= 4,
            "sim_mean": float(np.dot(pmf, np.arange(1, len(pmf) + 1))), "sim_top2": float(pmf[-2:].sum()),
            "baseline": baseline(row), **{g: row.values.get(g) for g in GROUPS},
        })

    out = {"run_id": run_id, "personas_scored": len(pmfs), "with_truth": len(records), "pool_rows": len(pool)}
    for label, subset in (("measured", [r for r in records if r["measured"]]), ("all", records)):
        truth = [r["truth"] for r in subset]
        out[label] = {
            "n": len(subset),
            "spearman_sim": spearmanr([r["sim_mean"] for r in subset], truth).statistic,
            "spearman_baseline": spearmanr([r["baseline"] for r in subset], truth).statistic,
            "real_uses_now": float(np.mean([r["uses_now"] for r in subset])),
            "sim_top2": float(np.mean([r["sim_top2"] for r in subset])),
        }
    measured = [r for r in records if r["measured"]]
    out["groups"] = {}
    for g in GROUPS:
        cells = defaultdict(list)
        for r in measured:
            cells[r[g]].append(r)
        rows = [(k, len(v), float(np.mean([x["uses_now"] for x in v])), float(np.mean([x["sim_top2"] for x in v])))
                for k, v in cells.items() if k is not None and len(v) >= 15]
        out["groups"][g] = {
            "cells": [{"value": k, "n": n, "real_uses_now": real, "sim_top2": sim} for k, n, real, sim in sorted(rows, key=lambda x: -x[1])],
            "spearman_across_cells": spearmanr([x[2] for x in rows], [x[3] for x in rows]).statistic if len(rows) >= 3 else None,
        }
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1])
