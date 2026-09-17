# Adapted from OASIS (https://github.com/camel-ai/oasis, Apache-2.0):
# `clock.py` (tick semantics). Upstream advances a shared clock; here each
# world carries its own declared tick unit and horizon, activation is a seeded
# Bernoulli draw per persona per tick, and the straggler case is the lowest
# tick among live worlds — no second time vocabulary.

"""When personas act and when things happen to them.

A scenario declares its `tick_unit` and `horizon_ticks`, and the unit travels
with the world so a report can label an axis truthfully. Activation is a
seeded Bernoulli draw per persona per tick from involvement × a rhythm curve
keyed to the tick unit. Interventions are expressed in ticks and compose
rather than overwrite.
"""

from collections.abc import Mapping, Sequence

from ._seeds import rng_for

# Share of each hour's personas awake: quiet at night, peaking midday.
HOUR_RHYTHM: tuple[float, ...] = (
    0.15, 0.10, 0.08, 0.08, 0.10, 0.20,  # 0-5
    0.40, 0.60, 0.75, 0.85, 0.90, 0.95,  # 6-11
    1.00, 1.00, 0.95, 0.90, 0.85, 0.80,  # 12-17
    0.75, 0.70, 0.60, 0.50, 0.35, 0.25,  # 18-23
)

# Share of each weekday's personas awake: weekdays full, weekends quieter.
DAY_RHYTHM: tuple[float, ...] = (0.55, 1.0, 1.0, 1.0, 1.0, 1.0, 0.60)

# A week-tick study moves slowly enough that every tick wakes everyone awake to be.
WEEK_RHYTHM: tuple[float, ...] = (1.0,)


def rhythm_at(tick_unit: str, tick: int, overrides: Mapping[str, float] | None = None) -> float:
    """The rhythm multiplier for this tick: a per-unit override, else the unit's curve."""
    if overrides and tick_unit in overrides:
        return overrides[tick_unit]
    if tick_unit == "hour":
        return HOUR_RHYTHM[tick % 24]
    if tick_unit == "day":
        return DAY_RHYTHM[tick % 7]
    return 1.0


def activation_probability(involvement: float, tick_unit: str, tick: int, overrides=None) -> float:
    """One persona's chance of acting this tick: involvement × the rhythm curve, capped at one."""
    return min(1.0, max(0.0, involvement) * rhythm_at(tick_unit, tick, overrides))


def activated_personas(
    persona_ids: Sequence[str],
    probabilities: Mapping[str, float],
    world_seed: int,
    tick: int,
) -> list[str]:
    """The personas acting this tick: one seeded Bernoulli draw each, in id order.

    The stream derives from (world seed, tick, "activation") alone, so a rerun
    under the same seed activates the same personas on the same ticks, and
    adding a later draw cannot shift this one.
    """
    rng = rng_for(world_seed, tick, "activation")
    return [pid for pid in sorted(persona_ids) if rng.random() < probabilities.get(pid, 1.0)]


def straggler_tick(ticks: Sequence[int]) -> int:
    """The lowest tick among live worlds — the straggler case needs no other word."""
    if not ticks:
        raise ValueError("no live worlds to take the lowest tick of")
    return min(ticks)


__all__ = [
    "DAY_RHYTHM",
    "HOUR_RHYTHM",
    "WEEK_RHYTHM",
    "activated_personas",
    "activation_probability",
    "rhythm_at",
    "straggler_tick",
]
