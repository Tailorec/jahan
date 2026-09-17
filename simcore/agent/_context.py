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
    impression_json: str,
    view_json: str,
    question: str,
    budget: int,
) -> AssembledContext:
    """Fit the context to the tier's budget, dropping memories before beliefs."""
    if _wire_size(persona_block, "", (), impression_json, view_json, question) > budget:
        raise ContextBudgetExceeded(
            "the tier's budget cannot hold the persona block, impression and question; "
            "the block is never dropped, so the turn fails instead"
        )
    kept_memories = list(memory_texts)
    while kept_memories and _wire_size(persona_block, beliefs_text, kept_memories, impression_json, view_json, question) > budget:
        kept_memories.pop(0)
    dropped_memories = len(memory_texts) - len(kept_memories)
    dropped_beliefs = False
    if _wire_size(persona_block, beliefs_text, kept_memories, impression_json, view_json, question) > budget:
        beliefs_text, dropped_beliefs = "", True
    messages = (
        {"role": "system", "content": persona_block},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "beliefs": beliefs_text,
                    "memories": list(kept_memories),
                    "impression": impression_json,
                    "view": view_json,
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


def _wire_size(block: str, beliefs: str, memories: list[str] | tuple[str, ...], impression: str, view: str, question: str) -> int:
    """The assembled prompt as the endpoint prices it: the block plus the user JSON."""
    user = json.dumps(
        {
            "beliefs": beliefs,
            "memories": list(memories),
            "impression": impression,
            "view": view,
            "question": question,
        }
    )
    return estimate_tokens(block + user)
