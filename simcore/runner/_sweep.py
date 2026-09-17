"""Sweep: many worlds, one run, one budget.

A grid of scenarios and replicate seeds expands into worlds whose ids
derive from the scenario, the seed and the population hash (ADR 0005), so
the same grid run twice addresses the same cells. Worlds run in parallel,
one process each in production (threads in boundary tests, same boundary),
against a shared ledger. A cell that ran at a different rung is marked by
its outcome's rungs, so the comparison is never drawn silently. Resuming a
sweep re-runs only the cells that had not completed.
"""

from __future__ import annotations

from simcore.schemas import RunConfig, Scenario, derive_world_id


def expand_sweep(config: RunConfig) -> list[tuple[Scenario, int, str]]:
    """One cell per scenario and replicate seed, with derived world ids."""
    return [
        (scenario, seed, derive_world_id(scenario, seed, config.population_hash))
        for scenario in config.scenarios
        for seed in config.seeds
    ]
