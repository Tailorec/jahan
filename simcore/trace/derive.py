"""The one implementation of every derived shape.

`beliefs` and `edges` are computed here and nowhere else (ADR 0034): the SQLite view, the
Parquet view and finalization all call into this module, so the live and finalized paths
cannot disagree. Filtering, verbatims and resolution live here too, for the same reason —
one question, one implementation.
"""

from collections.abc import Iterable, Mapping, Sequence

from simcore.schemas import (
    ActionKind,
    BeliefChange,
    BeliefHistory,
    BeliefPoint,
    Beliefs,
    EventFilter,
    ExposureReason,
    TraceEdge,
    TraceEvent,
    VerbatimGroup,
    VerbatimGrouping,
    VerbatimRecord,
)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def apply_change(beliefs: Beliefs, change: BeliefChange) -> Beliefs:
    """Beliefs moved by one change, clamped back into the unit interval."""
    dimensions = {dim: _clamp(beliefs.dimensions[dim] + change.dimensions.get(dim, 0.0)) for dim in beliefs.dimensions}
    credence = dict(beliefs.claim_credence)
    for claim, delta in change.claim_credence.items():
        credence[claim] = _clamp(credence.get(claim, 0.5) + delta)
    return Beliefs.model_validate({"dimensions": dimensions, "claim_credence": credence})


def _change_of(event: TraceEvent) -> BeliefChange | None:
    kind = event.payload.kind
    if kind == "turn":
        return event.payload.turn.reaction.belief_change  # type: ignore[union-attr]
    if kind == "reflection":
        return event.payload.change  # type: ignore[union-attr]
    return None


def derive_beliefs(events: Sequence[TraceEvent], persona_id: str) -> BeliefHistory:
    """One persona's belief history, oldest first, from its snapshots and the turns between.

    A snapshot anchors the history; turns and reflections move it. Turns before the first
    snapshot have no baseline to move from, so they narrow nothing and are not shown.
    Only this persona's records are read.
    """
    ordered = sorted((e for e in events if e.persona_id == persona_id), key=lambda e: (e.tick, e.seq))
    current: Beliefs | None = None
    points: dict[int, Beliefs] = {}
    for event in ordered:
        kind = event.payload.kind
        if kind == "belief_snapshot":
            current = event.payload.beliefs  # type: ignore[union-attr]
            points[event.tick] = current
        elif (change := _change_of(event)) is not None and current is not None:
            if not change.dimensions and not change.claim_credence:
                continue
            current = apply_change(current, change)
            points[event.tick] = current
    return BeliefHistory(
        persona_id=persona_id,  # type: ignore[arg-type]
        points=tuple(BeliefPoint(tick=tick, beliefs=beliefs) for tick, beliefs in sorted(points.items())),
    )


def _stimulus_authors(events: Iterable[TraceEvent]) -> dict[str, str | None]:
    authors: dict[str, str | None] = {}
    for event in events:
        if event.payload.kind == "stimulus_published":
            stimulus = event.payload.stimulus  # type: ignore[union-attr]
            authors[stimulus.stimulus_id] = stimulus.author
    return authors


def derive_edges(events: Sequence[TraceEvent]) -> tuple[TraceEdge, ...]:
    """One row per pair, channel and direction, with count and last tick.

    An edge is a word-of-mouth delivery the viewer's turn records: each exposure carried
    with reason ``wom`` counts from the stimulus's author to the viewer on the turn's
    channel. A ``follow`` reaction counts the same way toward the subject's author.
    """
    authors = _stimulus_authors(events)
    counts: dict[tuple[str, str, str], list[int]] = {}
    for event in sorted(events, key=lambda e: e.seq):
        if event.payload.kind != "turn" or event.persona_id is None:
            continue
        turn = event.payload.turn  # type: ignore[union-attr]
        viewer = event.persona_id
        seen: set[str] = set()
        for exposure in turn.impression.exposures:
            if exposure.reason is not ExposureReason.WOM:
                continue
            author = authors.get(exposure.stimulus_id)
            if author is None or author == viewer or author in seen:
                continue
            seen.add(author)
            key = (author, viewer, turn.impression.channel.value)
            counts.setdefault(key, [0, 0])
            counts[key][0] += 1
            counts[key][1] = event.tick
        if turn.reaction.action is ActionKind.FOLLOW:
            author = authors.get(turn.reaction.subject_stimulus_id)
            if author is not None and author != viewer and author not in seen:
                key = (author, viewer, turn.impression.channel.value)
                counts.setdefault(key, [0, 0])
                counts[key][0] += 1
                counts[key][1] = event.tick
    return tuple(
        TraceEdge.model_validate({"u": u, "v": v, "channel": channel, "count": count, "last_tick": last})
        for (u, v, channel), (count, last) in sorted(counts.items())
    )


def _claim_of(events: Iterable[TraceEvent]) -> dict[str, str | None]:
    claims: dict[str, str | None] = {}
    for event in events:
        if event.payload.kind == "stimulus_published":
            stimulus = event.payload.stimulus  # type: ignore[union-attr]
            claims[stimulus.stimulus_id] = stimulus.claim_id
    return claims


def derive_verbatims(events: Sequence[TraceEvent], grouping: VerbatimGrouping) -> tuple[VerbatimGroup, ...]:
    """What personas said, gathered under the keys of the grouping asked for."""
    claims = _claim_of(events)
    records: list[VerbatimRecord] = []
    for event in sorted(events, key=lambda e: e.seq):
        if event.payload.kind != "turn" or event.persona_id is None:
            continue
        reaction = event.payload.turn.reaction  # type: ignore[union-attr]
        if reaction.verbatim is None:
            continue
        records.append(
            VerbatimRecord.model_validate(
                {
                    "event_id": event.event_id,
                    "persona_id": event.persona_id,
                    "tick": event.tick,
                    "subject_stimulus_id": reaction.subject_stimulus_id,
                    "action": reaction.action.value,
                    "text": reaction.verbatim,
                    "claim_id": claims.get(reaction.subject_stimulus_id),
                }
            )
        )
    buckets: dict[str, list[VerbatimRecord]] = {}
    for record in records:
        if grouping is VerbatimGrouping.PERSONA:
            key = record.persona_id
        elif grouping is VerbatimGrouping.TICK:
            key = str(record.tick)
        elif grouping is VerbatimGrouping.SUBJECT:
            key = record.subject_stimulus_id
        else:
            if record.claim_id is None:
                continue
            key = record.claim_id
        buckets.setdefault(key, []).append(record)
    return tuple(
        VerbatimGroup(grouping=grouping, key=key, records=tuple(items))  # type: ignore[arg-type]
        for key, items in sorted(buckets.items())
    )


def filter_events(events: Sequence[TraceEvent], asked: EventFilter) -> tuple[TraceEvent, ...]:
    """The events the filter asks for, ordered by `(persona_id, tick, seq)`."""
    kinds = set(asked.kinds)
    personas = set(asked.persona_ids)
    kept = [
        event
        for event in events
        if (asked.ticks is None or asked.ticks[0] <= event.tick <= asked.ticks[1])
        and (not personas or event.persona_id in personas)
        and (not kinds or event.payload.kind in kinds)
    ]
    return tuple(sorted(kept, key=lambda e: (e.persona_id or "", e.tick, e.seq)))


def resolve_events(events: Sequence[TraceEvent], trace_ids: Iterable[str]) -> tuple[TraceEvent, ...]:
    """Exactly the events named, in the order asked; absent ids raise."""
    by_id = {event.event_id: event for event in events}
    resolved: list[TraceEvent] = []
    missing: list[str] = []
    for trace_id in trace_ids:
        event = by_id.get(trace_id)
        if event is None:
            missing.append(trace_id)
        else:
            resolved.append(event)
    if missing:
        raise KeyError(f"no events for trace ids: {sorted(missing)}")
    return tuple(resolved)


def closed_ticks(events: Sequence[TraceEvent]) -> set[int]:
    """Ticks whose `tick_closed` is on record; a live view shows these and nothing else."""
    return {event.tick for event in events if event.payload.kind == "tick_closed"}


def visible_events(events: Sequence[TraceEvent]) -> tuple[TraceEvent, ...]:
    """Every closed tick whole: events of a tick without its `tick_closed` are not shown."""
    closed = closed_ticks(events)
    return tuple(event for event in events if event.tick in closed)
