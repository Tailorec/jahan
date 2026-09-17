"""State round-trip: rebuilding what the run carried from the trace alone.

The runner checkpoints the state that crossed the boundary; replaying the run's
recorded events must rebuild the same state, memory for memory and belief for belief.
Snapshots are authoritative for beliefs, memory records for recollections (re-embedded
from their descriptions, since the trace keeps what was remembered and not the vector
it was indexed by), and reflection records for the counters. Turn records fill the gaps
between snapshots. Events of other personas, and payloads that carry no state, are
skipped — replay is scoped to one persona, like retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from simcore.schemas import (
    Beliefs,
    BeliefSnapshot,
    MemoryEvent,
    MemoryRecorded,
    PersonaState,
    ReflectionRecorded,
    TraceEvent,
    TurnRecorded,
)

from ._beliefs import apply_change


def rebuild_state(
    persona_id: str,
    baseline: Beliefs,
    events: Sequence[TraceEvent],
    *,
    embed=None,
) -> PersonaState:
    """The persona's state as its recorded events describe it, oldest first."""
    beliefs = baseline
    memories: list[MemoryEvent] = []
    seen: set[str] = set()
    last_reflection_tick = 0
    turns_since_reflection = 0
    for event in sorted(events, key=lambda event: event.seq):
        if event.persona_id != persona_id:
            continue
        payload = event.payload
        if isinstance(payload, MemoryRecorded):
            remembered = payload.memory
            if remembered.memory_id in seen:
                continue
            seen.add(remembered.memory_id)
            memories.append(_reindex(remembered, embed))
        elif isinstance(payload, BeliefSnapshot):
            beliefs = payload.beliefs
        elif isinstance(payload, TurnRecorded):
            beliefs = apply_change(beliefs, payload.turn.reaction.belief_change)
            turns_since_reflection += 1
        elif isinstance(payload, ReflectionRecorded):
            last_reflection_tick = event.tick
            turns_since_reflection = 0
    return PersonaState(
        persona_id=persona_id,
        beliefs=beliefs,
        memories=tuple(memories),
        last_reflection_tick=last_reflection_tick,
        turns_since_reflection=turns_since_reflection,
    )


def _reindex(remembered: MemoryEvent, embed) -> MemoryEvent:
    """Live state carries the embedding retrieval scores against; the trace does not.

    Rebuilt from the description through the same port, so identical descriptions
    re-index identically.
    """
    if embed is None:
        return remembered
    result = embed.embed([remembered.description])
    return remembered.model_copy(
        update={
            "embedding": tuple(float(value) for value in np.asarray(result.vectors[0], dtype=np.float64)),
            "embed_model_id": result.served_model_id or result.model_id,
        }
    )


def states_equal(first: PersonaState, second: PersonaState) -> bool:
    """Memory for memory and belief for belief, including the reflection counters."""
    return first == second
