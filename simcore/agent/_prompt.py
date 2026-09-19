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

def offered_actions(channel: object | None = None) -> tuple[str, ...]:
    """The actions a persona may choose on this channel, plus ignoring what it saw.

    A channel that does not support an action rejects it, and the rejection changes no state —
    the world owns affordances. Offering the whole enum regardless is how the first real study
    spent 895 of its 897 turns on actions a survey room discards: it affords `answer` alone, and
    625 personas asked a peer. Ignoring always lands, so it is always offered.
    """
    from simcore.schemas import CHANNEL_AFFORDANCES, ActionKind, Channel

    if channel is None:
        return tuple(sorted(action.value for action in ActionKind))
    afforded = set(CHANNEL_AFFORDANCES[Channel(channel)]) | {ActionKind.IGNORE}
    return tuple(sorted(action.value for action in afforded))


def reaction_question(channel: object | None = None) -> str:
    """The frozen question for a plain reaction turn, offering what this channel can land.

    It asks what the persona does, and never for a number.
    """
    # No path here requests a score: intent is elicited as words and scored by `elicitation`.
    return (
        "You saw the above. Reply with a JSON object with keys "
        "'subject_stimulus_id' (one stimulus id shown above), 'action' (one of "
        f"{', '.join(offered_actions(channel))}) and 'verbatim' (what you say, when the action "
        "produces text) and 'belief_deltas' (how this changed your views, if at all: an object "
        "with 'dimensions' mapping any of value, fit, trust to a move in -1..1, and "
        "'claim_credence' mapping claim ids like C1 to a move in -1..1; leave out what did not "
        "move). Answer in your own words, as yourself, and keep the verbatim to one or two brief "
        "sentences — a longer answer is cut off at the token ceiling and arrives unreadable."
    )


# Every action, for a turn whose channel is not known; the question's shape is asserted over it.
REACTION_QUESTION = reaction_question()


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
