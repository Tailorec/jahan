"""The cost ledger: what a run has spent, derived rather than remembered.

The ledger sums the `cost` events the run recorded, including what failed
calls billed; an unknown cost stays unknown and never becomes zero. On
resume it is rebuilt by summing. A discarded tick's spend is unknown but not
zero, so the figure the ladder tests is pessimistic: recorded spend plus, for
each discarded tick, the mean cost of the ticks that completed.
"""

from __future__ import annotations

from simcore.schemas import TraceEvent


def ledger_sum(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> tuple[float, int]:
    """Known spend and how many costs are unknown. Unknown never becomes zero."""
    known = 0.0
    unknown = 0
    for event in events:
        payload = event.payload
        if payload.kind != "cost":
            continue
        if payload.cost is None:
            unknown += 1
        else:
            known += float(payload.cost)
    return known, unknown


def mean_tick_cost(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> float:
    """Mean recorded cost per closed tick, or zero when nothing closed yet."""
    closed_ticks = {e.tick for e in events if e.payload.kind == "tick_closed"}
    if not closed_ticks:
        return 0.0
    known, _ = ledger_sum(events)
    return known / len(closed_ticks)


def pessimistic_figure(events: tuple[TraceEvent, ...] | list[TraceEvent], discarded_ticks: int) -> float:
    """The figure the ladder tests: recorded spend plus an estimate per discarded tick."""
    known, _ = ledger_sum(events)
    return known + discarded_ticks * mean_tick_cost(events)
