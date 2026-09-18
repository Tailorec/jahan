"""Context assembly under a token budget, per tier.

Order of assembly: the persona block, current beliefs, retrieved memories, the
impression and its view, then the frozen question. When the budget binds, memories drop
before beliefs and beliefs before the persona block — which is never dropped. A budget
that would drop the persona block fails the turn instead of sending an unconditioned
persona to the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CHARACTERS_PER_TOKEN = 4


class ContextBudgetExceeded(Exception):
    """The tier's budget cannot hold the persona block, impression and question."""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARACTERS_PER_TOKEN)


@dataclass(frozen=True)
class AssembledContext:
    persona_block: str
    persona_block_hash: str
    beliefs_text: str
    memory_texts: tuple[str, ...]
    dropped_memories: int
    dropped_beliefs: bool
    messages: tuple[dict[str, str], ...]


def render_shown(impression, view, stimulus_texts=None) -> list[dict]:
    """What the persona is looking at, in the order it was shown.

    Each entry carries the stimulus's own text, the id so a reaction can name its subject, and
    the public counts beside it. The prompt used to carry `impression` and `view` as serialized
    JSON instead, so a real persona was shown ids and a `contexts` field and reacted to the
    engine's plumbing — commenting on its own trust score and asking what `contexts` was for.
    """
    texts = dict(stimulus_texts or {})
    entries = []
    for exposure in impression.exposures:
        context = view.contexts.get(exposure.stimulus_id)
        entry: dict = {"stimulus_id": exposure.stimulus_id}
        text = texts.get(exposure.stimulus_id)
        if text:
            entry["says"] = text
        if context is not None:
            counts = {
                name: value
                for name, value in (
                    ("likes", context.likes), ("reposts", context.reposts), ("replies", context.replies),
                    ("upvotes", context.upvotes), ("downvotes", context.downvotes),
                )
                if value
            }
            if counts:
                entry["others"] = counts
            if context.via_persona_id is not None:
                entry["heard_from_someone_you_know"] = True
            elif context.tie_strength is not None:
                entry["from_someone_you_know"] = round(float(context.tie_strength), 2)
        entries.append(entry)
    return entries


def render_beliefs(dimensions: dict[str, float], claim_credence: dict[str, float]) -> str:
    dims = ", ".join(f"{name}={value:.2f}" for name, value in sorted(dimensions.items()))
    claims = ", ".join(f"{name}={value:.2f}" for name, value in sorted(claim_credence.items()))
    return f"Your current views (0-1): {dims}. Your credence in each claim (0-1): {claims}."


def assemble(
    *,
    persona_block: str,
    persona_block_hash: str,
    beliefs_text: str,
    memory_texts: tuple[str, ...],
    shown: list[dict] | tuple[dict, ...],
    question: str,
    budget: int,
) -> AssembledContext:
    """Fit the context to the tier's budget, dropping memories before beliefs."""
    if _wire_size(persona_block, "", (), shown, question) > budget:
        raise ContextBudgetExceeded(
            "the tier's budget cannot hold the persona block, impression and question; "
            "the block is never dropped, so the turn fails instead"
        )
    kept_memories = list(memory_texts)
    # Memories arrive best-first (retrieval rank, then recency), so the tail — the least
    # useful memory in context — is what goes when the budget binds.
    while kept_memories and _wire_size(persona_block, beliefs_text, kept_memories, shown, question) > budget:
        kept_memories.pop()
    dropped_memories = len(memory_texts) - len(kept_memories)
    dropped_beliefs = False
    if _wire_size(persona_block, beliefs_text, kept_memories, shown, question) > budget:
        beliefs_text, dropped_beliefs = "", True
    messages = (
        {"role": "system", "content": persona_block},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "beliefs": beliefs_text,
                    "memories": list(kept_memories),
                    "shown": list(shown),
                    "question": question,
                }
            ),
        },
    )
    if estimate_tokens(messages[0]["content"] + messages[1]["content"]) > budget:
        raise ContextBudgetExceeded(
            "the tier's budget cannot hold the persona block, impression and question; "
            "the block is never dropped, so the turn fails instead"
        )
    return AssembledContext(
        persona_block=persona_block,
        persona_block_hash=persona_block_hash,
        beliefs_text=beliefs_text,
        memory_texts=tuple(kept_memories),
        dropped_memories=dropped_memories,
        dropped_beliefs=dropped_beliefs,
        messages=messages,
    )


def _wire_size(block: str, beliefs: str, memories: list[str] | tuple[str, ...], shown, question: str) -> int:
    """The assembled prompt as the endpoint prices it: the block plus the user JSON."""
    user = json.dumps(
        {
            "beliefs": beliefs,
            "memories": list(memories),
            "shown": list(shown),
            "question": question,
        }
    )
    return estimate_tokens(block + user)
