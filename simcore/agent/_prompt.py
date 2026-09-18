"""Prompt assembly: the persona block, the impression, and the frozen question.

The persona block is assembled here and nowhere else — it is the conditioning invariant
the module exists to own. Phase 3 replaces the renderer with the ontology-selected,
cached version and adds the token budget; this phase settles the shape: one prompt per
persona, carrying that persona alone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

# The frozen question for a plain reaction turn. It asks what the persona does, never
# for a number: no code path asks a model for a rating.
REACTION_QUESTION = (
    "You saw the above. Reply with a JSON object with keys "
    "'subject_stimulus_id' (one stimulus id shown above), 'action' (one of answer, "
    "post, comment, like, repost, quote, follow, buy, ask_peer, reject, complain, "
    "reply, upvote, downvote, ignore) and 'verbatim' (what you say, when the action "
    "produces text) and 'belief_deltas' (how this changed your views, if at all: an object with "
    "'dimensions' mapping any of value, fit, trust to a move in -1..1, and 'claim_credence' "
    "mapping claim ids like C1 to a move in -1..1; leave out what did not move). Answer in your "
    "own words, as yourself, and keep the verbatim to one or two brief sentences — a longer "
    "answer is cut off at the token ceiling and arrives unreadable."
)


def render_persona_block(conditioning: Mapping[str, object], attributes: Mapping[str, object]) -> str:
    """The persona as the model is told about itself, one attribute per line."""
    lines = ["You are the following person:"]
    for name in sorted(conditioning):
        lines.append(f"- {name}: {conditioning[name]}")
    for name in sorted(attributes):
        lines.append(f"- {name}: {attributes[name]}")
    return "\n".join(lines)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assemble_prompt(persona_block: str, impression_json: str, view_json: str, question: str) -> str:
    return (
        f"{persona_block}\n\n"
        f"What you were shown:\n{impression_json}\n\n"
        f"The public context around it:\n{view_json}\n\n"
        f"{question}"
    )


def prompt_messages(persona_block: str, impression_json: str, view_json: str, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": persona_block},
        {"role": "user", "content": json.dumps({"impression": impression_json, "view": view_json, "question": question})},
    ]


def prompt_hash(messages: list[dict[str, str]]) -> str:
    return hash_text(json.dumps(messages, sort_keys=True))
