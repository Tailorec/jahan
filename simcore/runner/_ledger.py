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


def mean_call_cost(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> float | None:
    """Mean cost of the calls that came with a price, or nothing when none did."""
    priced = [float(e.payload.cost) for e in events if e.payload.kind == "cost" and e.payload.cost is not None]
    if not priced:
        return None
    return sum(priced) / len(priced)


def mean_tick_cost(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> float:
    """Mean spend per closed tick, priced calls and unpriced alike, or zero before any closed."""
    closed_ticks = {e.tick for e in events if e.payload.kind == "tick_closed"}
    if not closed_ticks:
        return 0.0
    return priced_spend(events) / len(closed_ticks)


def priced_spend(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> float:
    """Recorded spend with every unpriced call charged at the mean of the priced ones.

    A cost nobody quoted stays `UNKNOWN` in the record — it never becomes zero — but a budget
    that treats it as zero is not enforced: a run whose gateway reported no prices spent its
    whole horizon without a rung firing. Here an unpriced call costs what a priced one did.
    """
    known, unpriced = ledger_sum(events)
    if not unpriced:
        return known
    rate = mean_call_cost(events)
    if rate is None:
        return known
    return known + unpriced * rate


def unpriceable(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> bool:
    """Whether calls were billed with no price anywhere to charge them at.

    With nothing quoted there is no figure to enforce a budget against, so a run stops rather
    than spending against a ceiling it cannot measure.
    """
    known, unpriced = ledger_sum(events)
    return unpriced > 0 and mean_call_cost(events) is None


def pessimistic_figure(events: tuple[TraceEvent, ...] | list[TraceEvent], discarded_ticks: int) -> float:
    """The figure the ladder tests: spend with unpriced calls charged, plus an estimate for
    each discarded tick, whose own spend is unknown but not zero (ADR 0033)."""
    return priced_spend(events) + discarded_ticks * mean_tick_cost(events)
