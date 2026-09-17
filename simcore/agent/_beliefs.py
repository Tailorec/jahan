"""Beliefs and reflection: how a persona changes, and how experience consolidates.

Belief deltas apply across the closed dimension set and per claim, so a flip on a single
claim is visible even when aggregate belief barely moves. Reflection fires on a
per-persona cadence jittered from the run seed, or whenever the turn's largest move
exceeds the threshold across dimensions and claims together. It produces a further
belief change plus one to three consolidated memories of high importance, and the
runner carries the result forward through `advance_state`, which caps memories without
discarding the highest-importance items.
"""

from __future__ import annotations

import hashlib
import re

from simcore.schemas import (
    BeliefChange,
    Beliefs,
    BeliefDim,
    CompletedTurn,
    MemoryEvent,
    MemorySource,
    PersonaState,
)

from ._memory import belief_magnitude

CONSOLIDATED_IMPORTANCE = 0.85
MAX_CONSOLIDATED = 3


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def apply_change(beliefs: Beliefs, change: BeliefChange) -> Beliefs:
    """Beliefs moved by a delta, across dimensions and per claim; only moved entries appear."""
    dimensions = dict(beliefs.dimensions)
    for dim, delta in change.dimensions.items():
        dimensions[dim] = _clamp(dimensions[dim] + delta)
    credence = dict(beliefs.claim_credence)
    for claim, delta in change.claim_credence.items():
        credence[claim] = _clamp(credence[claim] + delta)
    return Beliefs(dimensions=dimensions, claim_credence=credence)


def combine(first: BeliefChange, second: BeliefChange) -> BeliefChange:
    """Two changes as one: the turn's move plus reflection's revision."""
    dimensions: dict[BeliefDim, float] = dict(first.dimensions)
    for dim, delta in second.dimensions.items():
        dimensions[dim] = dimensions.get(dim, 0.0) + delta
    credence: dict[str, float] = dict(first.claim_credence)
    for claim, delta in second.claim_credence.items():
        credence[claim] = credence.get(claim, 0.0) + delta
    return BeliefChange(dimensions=dimensions, claim_credence=credence)


def reflection_interval_for(persona_id: str, run_seed: int, *, base: int = 6, jitter: int = 2) -> int:
    """The persona's reflection cadence, derived from the run seed and nothing else.

    A rerun reflects on the same ticks; adding another draw elsewhere cannot shift it,
    because the derivation names its own purpose.
    """
    digest = hashlib.sha256(f"reflection-cadence|{run_seed}|{persona_id}".encode("utf-8")).digest()
    return base - jitter + digest[0] % (2 * jitter + 1)


def reflection_due(
    state: PersonaState,
    change: BeliefChange,
    *,
    run_seed: int,
    base: int = 6,
    jitter: int = 2,
    threshold: float = 0.3,
) -> bool:
    """Reflection fires at the jittered cadence, or on a sharp move — and not otherwise."""
    if max_abs_change(change) > threshold:
        return True
    interval = reflection_interval_for(state.persona_id, run_seed, base=base, jitter=jitter)
    return state.turns_since_reflection + 1 >= interval


def split_summary(summary: str) -> tuple[str, ...]:
    """One consolidated memory per sentence, one to three in all."""
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", summary) if part.strip()]
    return tuple(sentences[:MAX_CONSOLIDATED]) or ("On reflection, recent experience holds.",)


def enforce_cap(memories: tuple[MemoryEvent, ...], cap: int) -> tuple[MemoryEvent, ...]:
    """Memories capped without discarding the highest-importance items."""
    if len(memories) <= cap:
        return memories
    ranked = sorted(memories, key=lambda memory: (memory.importance, memory.tick), reverse=True)
    kept = set(memory.memory_id for memory in ranked[:cap])
    return tuple(memory for memory in memories if memory.memory_id in kept)


def advance_state(
    state: PersonaState, outcome: CompletedTurn, tick: int, *, memory_cap: int
) -> PersonaState:
    """The state the runner carries forward: beliefs moved, memories appended and capped.

    A turn that consolidated by reflection resets the reflection counters; any other turn
    advances them. Whether reflection fired is read from the outcome's own memories, so no
    extra channel crosses the boundary.
    """
    beliefs = apply_change(state.beliefs, outcome.belief_change)
    memories = enforce_cap(tuple(state.memories) + tuple(outcome.memories), memory_cap)
    if any(memory.source is MemorySource.REFLECTION for memory in outcome.memories):
        return state.model_copy(
            update={"beliefs": beliefs, "memories": memories, "last_reflection_tick": tick, "turns_since_reflection": 0}
        )
    return state.model_copy(
        update={"beliefs": beliefs, "memories": memories, "turns_since_reflection": state.turns_since_reflection + 1}
    )


def max_abs_change(change: BeliefChange) -> float:
    """The largest single move, across dimensions and claims together."""
    candidates = [abs(value) for value in change.dimensions.values()]
    candidates.extend(abs(value) for value in change.claim_credence.values())
    return max(candidates) if candidates else 0.0
