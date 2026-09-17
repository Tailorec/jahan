"""Resume from the record: state comes from the trace, never a second copy.

Personas are rebuilt from memory events, belief snapshots and turns via
`agent.rebuild_state`; worlds by `reset` and replaying recorded turns to the
last closed tick; the ledger by summing (Phase 4). A checkpoint, if present,
is validated against the record and discarded when it disagrees. Completed
ticks are never re-run.
"""

from __future__ import annotations

from simcore.agent import rebuild_state
from simcore.schemas import PersonaState, Population, TraceEvent, Turn


def last_closed_tick(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> int:
    """The last tick with a `tick_closed` event, or -1 when nothing closed yet."""
    closed = [e.tick for e in events if e.payload.kind == "tick_closed"]
    return max(closed) if closed else -1


def next_seq(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> int:
    """The next free sequence number: one past the highest held, or 0."""
    if not events:
        return 0
    return max(e.seq for e in events) + 1


def turns_by_tick(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> dict[int, list[Turn]]:
    """Recorded turns keyed by the tick they were recorded at."""
    out: dict[int, list[Turn]] = {}
    for event in sorted(events, key=lambda e: e.seq):
        if event.payload.kind == "turn":
            out.setdefault(event.tick, []).append(event.payload.turn)
    return out


def rebuild_persona_states(
    population: Population,
    events: tuple[TraceEvent, ...] | list[TraceEvent],
    memory_cap: int = 50,
) -> dict[str, PersonaState]:
    """One persona's carried state, rebuilt from the trace alone."""
    states: dict[str, PersonaState] = {}
    for persona in population.personas:
        states[persona.persona_id] = rebuild_state(
            persona.persona_id, persona.baseline_beliefs, tuple(events), memory_cap=memory_cap
        )
    return states


def validate_checkpoint(checkpoint: dict | None, rebuilt: dict[str, PersonaState], expected_seq: int) -> bool:
    """A checkpoint agrees with the record, or it is discarded.

    The checkpoint caches `states` and the `next_seq` it was taken at. Any
    disagreement — wrong seq, missing persona, unequal state — discards it.
    """
    if checkpoint is None:
        return False
    try:
        if int(checkpoint.get("next_seq", -1)) != expected_seq:
            return False
        cached = checkpoint.get("states", {})
        if set(cached) != set(rebuilt):
            return False
        return all(cached[pid] == rebuilt[pid] for pid in rebuilt)
    except (AttributeError, TypeError, ValueError):
        return False
