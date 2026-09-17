"""Replay and resume: a world is rebuilt from its header and its recorded turns.

Resume and the determinism check are the same mechanism. Replaying the
recorded turns from `reset` must reproduce every recorded delta exactly —
field for field — so a resumed run is the same run, and a divergence fails
loudly naming the first tick and field that differ. Internal checkpoints may
speed replay up; they are never a contract. Replay needs nothing but the
header and the recorded turns (the population the header pins travels with
the run and is verified against it).
"""

from collections.abc import Mapping, Sequence
import json

from pydantic_core import to_jsonable_python

from simcore.schemas import PartitionHeader, Population, SimBaseModel, Turn, WorldDelta, canonical_json

from .env import World, WorldConfig


class ReplayDivergence(ValueError):
    """A replay that did not reproduce its recorded delta, naming tick and field."""

    def __init__(self, tick: int, field: str, recorded: str, replayed: str) -> None:
        super().__init__(
            f"replay diverged at tick {tick}: {field} differs "
            f"(recorded {recorded}, replayed {replayed})"
        )
        self.tick = tick
        self.field = field


def run(
    header: PartitionHeader,
    turns_by_tick: Mapping[int, Sequence[Turn]],
    population: Population | None = None,
    config: WorldConfig | None = None,
) -> list[WorldDelta]:
    """Fresh deltas from a header and recorded turns: `reset`, then `step` per tick.

    Turns are keyed by the tick they were recorded at; the step for tick `t`
    takes the turns recorded at `t - 1`, so replaying keys `1..T` reproduces
    the deltas for ticks `0..T`.
    """
    world = World(header, population=population, config=config)
    deltas = [world.reset()]
    if not turns_by_tick:
        return deltas
    for tick in range(1, max(turns_by_tick) + 1):
        deltas.append(world.step(tick, list(turns_by_tick.get(tick - 1, []))))
    return deltas


def check_replay(
    recorded: Sequence[WorldDelta],
    header: PartitionHeader,
    turns_by_tick: Mapping[int, Sequence[Turn]],
    population: Population | None = None,
    config: WorldConfig | None = None,
) -> None:
    """Replay and demand every recorded delta back exactly; fail loudly otherwise."""
    replayed = run(header, turns_by_tick, population=population, config=config)
    if len(replayed) != len(recorded):
        raise ReplayDivergence(
            min(len(recorded), len(replayed)), "delta_count", str(len(recorded)), str(len(replayed))
        )
    for expected, actual in zip(recorded, replayed, strict=True):
        _demand_equal(expected, actual)


def resume(
    header: PartitionHeader,
    turns_by_tick: Mapping[int, Sequence[Turn]],
    through_tick: int,
    population: Population | None = None,
    config: WorldConfig | None = None,
) -> World:
    """A live world rebuilt by replaying turns up to `through_tick`, ready to continue."""
    world = World(header, population=population, config=config)
    world.reset()
    for tick in range(1, through_tick + 1):
        world.step(tick, list(turns_by_tick.get(tick - 1, [])))
    return world


def _field_json(value: object) -> str:
    """Canonical JSON for a delta field: models hash by their own canonical form."""
    if isinstance(value, SimBaseModel):
        return canonical_json(value)
    return json.dumps(to_jsonable_python(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _demand_equal(recorded: WorldDelta, replayed: WorldDelta) -> None:
    """Field-by-field equality, naming the first field that differs."""
    tick = recorded.tick
    if replayed.tick != tick:
        raise ReplayDivergence(tick, "tick", str(recorded.tick), str(replayed.tick))
    for field in ("published", "interventions", "dropped", "presentations"):
        expected = _field_json(getattr(recorded, field))
        actual = _field_json(getattr(replayed, field))
        if expected != actual:
            raise ReplayDivergence(tick, field, expected, actual)


__all__ = ["ReplayDivergence", "check_replay", "resume", "run"]
