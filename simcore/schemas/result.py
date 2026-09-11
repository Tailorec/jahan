"""The result domain: what a run returns — the registry entry that reproduces it and one outcome per world."""

from collections import Counter
from typing import Self

from pydantic import Field, model_validator

from .base import NonNegativeInt, SimBaseModel
from .enums import DegradationRung, RUNG_ORDER, WorldStatus
from .run import WorldId
from .trace import RunRegistryEntry


class WorldOutcome(SimBaseModel):
    """What became of one world: whether it reached its horizon, the last tick it closed, and the degradation
    rungs it went through. A world that never started closed no tick and applied no rung."""

    world_id: WorldId
    status: WorldStatus
    last_closed_tick: NonNegativeInt | None = None
    rungs: tuple[DegradationRung, ...] = ()

    @model_validator(mode="after")
    def _a_world_that_never_started_did_nothing(self) -> Self:
        if self.status is WorldStatus.NOT_STARTED and (self.last_closed_tick is not None or self.rungs):
            raise ValueError(f"world {self.world_id} never started, so it closed no tick and applied no rung")
        return self

    @model_validator(mode="after")
    def _rungs_escalate(self) -> Self:
        for previous, rung in zip(self.rungs, self.rungs[1:]):
            if RUNG_ORDER.index(rung) <= RUNG_ORDER.index(previous):
                raise ValueError(f"world {self.world_id} applies {rung.value} after {previous.value}; degradation only escalates")
        return self


class RunResult(SimBaseModel):
    """What a run returns: the registry entry replay needs and one outcome per world it configured. The run's
    outcomes are exactly the worlds its configuration names.

    A sweep is a plan expanded into an ordinary run, so this is what a sweep returns too."""

    registry: RunRegistryEntry
    outcomes: tuple[WorldOutcome, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _outcomes_are_exactly_the_runs_worlds(self) -> Self:
        repeated = sorted(world for world, count in Counter(o.world_id for o in self.outcomes).items() if count > 1)
        if repeated:
            raise ValueError(f"worlds reported more than once: {repeated}")
        registered = set(self.registry.world_ids)
        reported = {outcome.world_id for outcome in self.outcomes}
        if reported != registered:
            missing, unknown = sorted(registered - reported), sorted(reported - registered)
            raise ValueError(f"a run reports every world it configured and no other: missing {missing}, unknown {unknown}")
        return self
