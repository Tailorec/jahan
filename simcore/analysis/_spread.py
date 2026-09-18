"""A scenario's spread: one summary over its worlds' digests.

`spread` gathers a scenario's worlds, keeping each seed's values beside the spread
between them — the yardstick every anomaly threshold is measured against. The spread is
computed between worlds, never within one. Comparing digests whose tick units differ is
refused, as are digests from different scenarios. A cell whose worlds ran at different
degradation rungs is marked rather than quietly averaged (ADR 0037).
"""

from collections.abc import Sequence

from simcore.schemas import OutcomeDigest, ScenarioSummary


def spread(worlds: Sequence[tuple[int, str, OutcomeDigest]]) -> ScenarioSummary:
    """Aggregate one scenario's digests: `(seed, world_id, digest)` per world.

    The scenario hash and tick unit come from the digests themselves, so worlds from
    different scenarios or with differing tick units are refused where they are gathered.
    """
    entries = list(worlds)
    if not entries:
        raise ValueError("a scenario summary aggregates at least one world")
    first = entries[0][2]
    scenario_hash, tick_unit = first.scenario_hash, first.tick_unit
    for seed, world_id, digest in entries:
        if digest.scenario_hash != scenario_hash:
            raise ValueError(
                f"world {world_id} digests scenario {digest.scenario_hash}, not {scenario_hash}: "
                "a scenario summary gathers one scenario's worlds"
            )
        if digest.tick_unit is not tick_unit:
            raise ValueError(
                f"world {world_id} ran in {digest.tick_unit.value} ticks, not {tick_unit.value}: "
                "digests with differing tick units are not comparable"
            )
    return ScenarioSummary.model_validate({
        "scenario_hash": scenario_hash,
        "tick_unit": tick_unit.value,
        "entries": [
            {"seed": seed, "world_id": world_id, "digest": digest.model_dump(mode="json")}
            for seed, world_id, digest in entries
        ],
    })
