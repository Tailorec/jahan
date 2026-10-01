"""Prompt reconstruction: the exact messages a turn sent, rebuilt and verified.

A prompt is reconstructed and verified, never stored (ADR 0046): the turn
record carries the template that rendered it and the hashes of its parts and
of the prompt, and reconstruction re-renders every part from the record — the
persona block from the population's own records, beliefs from snapshots and
turns, memories by id, the shown stimuli from the impression and view — then
displays the messages only when their hash matches the turn's recorded hash.
Anything that cannot be rebuilt says so and why, rather than showing an
approximation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from simcore.elicitation import question_text
from simcore.schemas import Beliefs, CategoryOntology, Persona, TraceEvent
from simcore.schemas.trace import TurnRecorded

from ._beliefs import apply_change
from ._context import assemble, render_beliefs, render_shown
from ._guard import allowed_stimuli, strict_question
from ._intent import PURCHASE_CONSTRUCT
from ._prompt import (
    hash_text,
    intent_question,
    prompt_hash,
    reaction_question,
    render_persona_block,
)
from ._render import render_block

# A budget that never binds: reconstruction tests the unbound hypothesis, and
# a turn whose context budget dropped memories cannot be rebuilt from the
# record — tier budgets are execution configuration, never recorded — so it
# reports why instead of guessing which memories were kept.
_UNBOUND_BUDGET = 10**12


@dataclass(frozen=True)
class ReconstructedPrompt:
    """The messages a turn sent, byte-identical to what the endpoint received."""

    messages: tuple[dict[str, str], ...]
    shape: str  # "reaction" or "purchase_intent", with ":retry" when accepted on retry
    rejected_verified: bool


@dataclass(frozen=True)
class Unreconstructible:
    """Why a prompt cannot be shown: a part is missing or nothing matches the hash."""

    reason: str


def reconstruct_turn(
    record: TurnRecorded,
    event: TraceEvent,
    *,
    persona: Persona,
    ontology: CategoryOntology | None,
    persona_events: tuple[TraceEvent, ...] | list[TraceEvent],
    stimulus_texts: dict[str, str],
    wire_hashes: Callable[[list[dict[str, str]]], Iterable[str]] | None = None,
) -> ReconstructedPrompt | Unreconstructible:
    """Rebuild a turn's prompt from the record and verify it against its hash.

    A real endpoint records the hash of the whole request it received — model, sampling budget and
    messages — so `wire_hashes` names what those would be for the run's pins; the messages-only hash
    is what the fake port records."""
    hashes = _hasher(wire_hashes)
    block = _persona_block(record, persona, ontology)
    if block is None:
        return Unreconstructible(
            "the persona block re-rendered from the population's records does not match "
            "the turn's recorded block hash: the persona or the ontology moved since the run"
        )
    beliefs = _beliefs_before(persona_events, event)
    if beliefs is None:
        return Unreconstructible(
            "no belief baseline precedes this turn: without a snapshot the turn's "
            "beliefs have nothing to move from"
        )
    memories = _memories(record, persona_events)
    if memories is None:
        return Unreconstructible(
            "a memory this turn recalled is not in the record: prompts cite memories by id"
        )
    texts = _shown_texts(record, stimulus_texts)
    if texts is None:
        return Unreconstructible(
            "a stimulus this turn was shown has no published text in the record"
        )
    shown = render_shown(record.turn.impression, record.turn.view, stimulus_texts)
    beliefs_text = render_beliefs(
        {dimension.value: value for dimension, value in beliefs.dimensions.items()},
        dict(beliefs.claim_credence),
    )
    channel = record.turn.impression.channel
    bases = (
        ("reaction", reaction_question(channel)),
        ("purchase_intent", intent_question(question_text(PURCHASE_CONSTRUCT), channel)),
    )
    if record.rejected_prompt_hashes:
        outcome = _match_retry(record, block, beliefs_text, memories, shown, bases, hashes)
    else:
        outcome = _match_first(record, block, beliefs_text, memories, shown, bases, hashes)
    if outcome is None:
        return Unreconstructible(
            "no question shape rebuilds the recorded prompt hash: the turn may have run "
            "under a template version this engine no longer carries, or its context "
            "budget dropped memories the record cannot name"
        )
    return outcome


def _persona_block(
    record: TurnRecorded, persona: Persona, ontology: CategoryOntology | None
) -> str | None:
    """The persona block, through whichever renderer the run used — the hash decides."""
    if ontology is not None:
        rendered = render_block(persona, ontology)
        if hash_text(rendered) == record.persona_block_hash:
            return rendered
    bare = render_persona_block(persona.conditioning, persona.attributes)
    if hash_text(bare) == record.persona_block_hash:
        return bare
    return None


def _change_of(event: TraceEvent):
    kind = event.payload.kind
    if kind == "turn":
        return event.payload.turn.reaction.belief_change
    if kind == "reflection":
        return event.payload.change
    return None


def _beliefs_before(
    persona_events: tuple[TraceEvent, ...] | list[TraceEvent], event: TraceEvent
) -> Beliefs | None:
    """What the persona believed when this turn started: snapshots moved by the
    turns and reflections between, in record order, stopping at this turn."""
    current: Beliefs | None = None
    # A tick runs its channel turns together from the tick's opening state, then its survey wave
    # from the state they left: a channel turn starts before any of its tick's turns moved anything.
    survey = event.payload.turn.impression.channel == "survey_room"
    for other in sorted(persona_events, key=lambda e: (e.tick, e.seq)):
        if (other.tick, other.seq) >= (event.tick, event.seq):
            break
        if not survey and other.tick == event.tick and other.payload.kind == "turn":
            break
        kind = other.payload.kind
        if kind == "belief_snapshot":
            current = other.payload.beliefs
        elif kind in ("turn", "reflection") and current is not None:
            if kind == "turn" and other.payload.turn.impression.channel == "survey_room":
                continue  # a wave only reads: its answer moved no belief (as `replay` rebuilds state)
            change = _change_of(other)
            if change is not None and (change.dimensions or change.claim_credence):
                current = apply_change(current, change)
    return current


def _memories(
    record: TurnRecorded, persona_events: tuple[TraceEvent, ...] | list[TraceEvent]
) -> tuple[str, ...] | None:
    """Recalled memories as the prompt carried them, in recall order."""
    by_id = {}
    for event in persona_events:
        if event.payload.kind == "memory":
            by_id[event.payload.memory.memory_id] = event.payload.memory
    texts = []
    for memory_id in record.memory_ids:
        memory = by_id.get(memory_id)
        if memory is None:
            return None
        texts.append(f"[tick {memory.tick}] {memory.description}")
    return tuple(texts)


def _shown_texts(record: TurnRecorded, stimulus_texts: dict[str, str]) -> dict[str, str] | None:
    """Every shown stimulus needs its published text: the prompt carried words, not ids."""
    missing = sorted(
        {exposure.stimulus_id for exposure in record.turn.impression.exposures}
        - set(stimulus_texts)
    )
    if missing:
        return None
    return stimulus_texts


def _assemble(block: str, beliefs_text: str, memories: tuple[str, ...], shown, question: str):
    return assemble(
        persona_block=block,
        persona_block_hash=hash_text(block),
        beliefs_text=beliefs_text,
        memory_texts=memories,
        shown=shown,
        question=question,
        budget=_UNBOUND_BUDGET,
    )


def _hasher(wire_hashes):
    def hashes(messages) -> set[str]:
        listed = [dict(message) for message in messages]
        return {prompt_hash(listed), *(wire_hashes(listed) if wire_hashes is not None else ())}

    return hashes


def _match_first(record, block, beliefs_text, memories, shown, bases, hashes):
    for shape, question in bases:
        messages = _assemble(block, beliefs_text, memories, shown, question).messages
        if record.prompt_hash in hashes(messages):
            return ReconstructedPrompt(messages=messages, shape=shape, rejected_verified=False)
    return None


def _match_retry(record, block, beliefs_text, memories, shown, bases, hashes):
    noticed = {
        exposure.stimulus_id for exposure in record.turn.impression.exposures if exposure.seen
    }
    retrieved = tuple(
        text.split("] ", 1)[1] if "] " in text else text for text in memories
    )
    shown_ids = {exposure.stimulus_id for exposure in record.turn.impression.exposures}
    allowed = noticed or allowed_stimuli(shown_ids, retrieved)
    for shape, question in bases:
        strict = strict_question(question, allowed)
        messages = _assemble(block, beliefs_text, memories, shown, strict).messages
        if record.prompt_hash in hashes(messages):
            rejected_verified = any(
                rejected in hashes(_assemble(block, beliefs_text, memories, shown, q).messages)
                for q in (question for _, question in bases)
                for rejected in record.rejected_prompt_hashes
            )
            return ReconstructedPrompt(
                messages=messages, shape=f"{shape}:retry", rejected_verified=rejected_verified
            )
    return None


__all__ = ["ReconstructedPrompt", "Unreconstructible", "reconstruct_turn"]
