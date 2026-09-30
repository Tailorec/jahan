"""How far one world has got: ticks closed, turns landed per channel, waves answered, the rung in force.

A running study is watched through this shape, so the web layer serialises it and
counts nothing. It reads the record only through `events`, the same way whether the
world is still being written or already finalized.
"""

from __future__ import annotations

from collections import Counter

from simcore.schemas import EventFilter, FrozenDict, NonNegativeInt, SimBaseModel


class WorldProgress(SimBaseModel):
    """One world's progress as its record stands now."""

    world_id: str
    last_closed_tick: NonNegativeInt | None = None
    turns: NonNegativeInt = 0
    rungs: tuple[str, ...] = ()
    # Turns per channel, the survey room being the waves' own; and the ticks whose wave was answered.
    turns_by_channel: FrozenDict[str, NonNegativeInt] = FrozenDict({})
    waves_answered: tuple[NonNegativeInt, ...] = ()


def world_progress(view: object, world_id: str) -> WorldProgress:
    """Ticks closed, turns landed per channel, waves answered and the rungs that fired, for one world."""
    closed = view.events(EventFilter.model_validate({"kinds": ("tick_closed",)}))  # type: ignore[attr-defined]
    turns = view.events(EventFilter.model_validate({"kinds": ("turn",)}))  # type: ignore[attr-defined]
    degraded = view.events(EventFilter.model_validate({"kinds": ("degraded",)}))  # type: ignore[attr-defined]
    return WorldProgress(
        world_id=world_id,
        last_closed_tick=max((event.tick for event in closed), default=None),
        turns=len(turns),
        rungs=tuple(sorted({str(event.payload.rung) for event in degraded})),
        turns_by_channel=dict(sorted(Counter(str(event.payload.turn.impression.channel) for event in turns).items())),
        waves_answered=tuple(sorted({event.tick for event in turns if event.payload.turn.impression.channel == "survey_room"})),
    )


__all__ = ["WorldProgress", "world_progress"]
