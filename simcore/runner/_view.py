"""Reading a finished run back: the fixed set of questions over the record.

Nothing else can be asked, and nothing that reads it can reach past it. At
this boundary the view runs over the in-memory sink; the real Parquet view
arrives with `trace` (M9) through the same protocol.
"""

from __future__ import annotations

from simcore.schemas import (
    BeliefHistory,
    BeliefPoint,
    EventFilter,
    TraceEdge,
    TraceEvent,
    VerbatimGroup,
    VerbatimGrouping,
    VerbatimRecord,
)


class RunnerTraceView:
    """A typed, closed read over one world's recorded events."""

    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self._events = tuple(sorted(events, key=lambda e: e.seq))

    def events(self, asked: EventFilter) -> tuple[TraceEvent, ...]:
        out = self._events
        if asked.ticks is not None:
            out = tuple(e for e in out if asked.ticks[0] <= e.tick <= asked.ticks[1])
        if asked.persona_ids:
            wanted = set(asked.persona_ids)
            out = tuple(e for e in out if e.persona_id in wanted)
        if asked.kinds:
            wanted = set(asked.kinds)
            out = tuple(e for e in out if e.payload.kind in wanted)
        return out

    def beliefs(self, persona_id: str) -> BeliefHistory:
        points: list[BeliefPoint] = []
        for event in self._events:
            if event.persona_id != persona_id:
                continue
            if event.payload.kind == "belief_snapshot":
                points.append(BeliefPoint(tick=event.tick, beliefs=event.payload.beliefs))
        return BeliefHistory(persona_id=persona_id, points=tuple(points))

    def edges(self) -> tuple[TraceEdge, ...]:
        return ()

    def verbatims(self, grouping: VerbatimGrouping) -> tuple[VerbatimGroup, ...]:
        records: list[VerbatimRecord] = []
        for event in self._events:
            if event.payload.kind != "turn":
                continue
            verbatim = event.payload.turn.reaction.verbatim
            if verbatim is None:
                continue
            records.append(
                VerbatimRecord(
                    event_id=event.event_id,
                    persona_id=event.persona_id,  # type: ignore[arg-type]
                    tick=event.tick,
                    subject_stimulus_id=event.payload.turn.reaction.subject_stimulus_id,
                    action=event.payload.turn.reaction.action,
                    text=verbatim,
                )
            )
        groups: dict[str, list[VerbatimRecord]] = {}
        for record in records:
            key = str(record.tick) if grouping is VerbatimGrouping.TICK else record.persona_id
            groups.setdefault(key, []).append(record)
        return tuple(VerbatimGroup(grouping=grouping, key=key, records=tuple(items)) for key, items in sorted(groups.items()))

    def resolve(self, trace_ids) -> tuple[TraceEvent, ...]:
        wanted = list(trace_ids)
        by_id = {e.event_id: e for e in self._events}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            raise KeyError(f"unknown trace ids: {missing}")
        return tuple(by_id[i] for i in wanted)
