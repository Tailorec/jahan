"""How far one world has got: ticks closed, turns landed, the rung in force.

A running study is watched through this shape, so the web layer serialises it and
counts nothing. It reads the record only through `events`, the same way whether the
world is still being written or already finalized.
"""

from __future__ import annotations

from simcore.schemas import EventFilter, NonNegativeInt, SimBaseModel


class WorldProgress(SimBaseModel):
    """One world's progress as its record stands now."""

    world_id: str
    last_closed_tick: NonNegativeInt | None = None
    turns: NonNegativeInt = 0
    rungs: tuple[str, ...] = ()


def world_progress(view: object, world_id: str) -> WorldProgress:
    """Ticks closed, turns landed and the degradation rungs that fired, for one world."""
    closed = view.events(EventFilter.model_validate({"kinds": ("tick_closed",)}))  # type: ignore[attr-defined]
    turns = view.events(EventFilter.model_validate({"kinds": ("turn",)}))  # type: ignore[attr-defined]
    degraded = view.events(EventFilter.model_validate({"kinds": ("degraded",)}))  # type: ignore[attr-defined]
    return WorldProgress(
        world_id=world_id,
        last_closed_tick=max((event.tick for event in closed), default=None),
        turns=len(turns),
        rungs=tuple(sorted({str(event.payload.rung) for event in degraded})),
    )


__all__ = ["WorldProgress", "world_progress"]
