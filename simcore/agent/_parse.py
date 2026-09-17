"""Parsing a completion into reaction parts, per task type.

Phase 2 parses the plain reaction shape. Phase 6 moves unparseable output and
references to stimuli never shown onto the one-retry guardrail path; until then an
answer the turn cannot use is a recorded call failure, never a silent gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from simcore.schemas import ActionKind

TEXT_ACTIONS = frozenset(
    {
        ActionKind.ANSWER,
        ActionKind.POST,
        ActionKind.COMMENT,
        ActionKind.REPLY,
        ActionKind.QUOTE,
        ActionKind.COMPLAIN,
        ActionKind.ASK_PEER,
    }
)


@dataclass(frozen=True)
class ParsedReaction:
    subject_stimulus_id: str
    action: ActionKind
    verbatim: str | None
    # Tier B only: the model rates the memory's importance inside the call already being
    # made, so importance adds no call of its own. Absent on tier A, where the rule decides.
    importance: float | None = None


def parse_reaction(text: str) -> ParsedReaction:
    """Parse a completion's JSON into the reaction it proposes."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError(f"the response is not parseable JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"the response is a {type(raw).__name__}, not an object")
    try:
        action = ActionKind(str(raw.get("action", "")).strip().lower())
    except ValueError:
        raise ValueError(f"the response names no known action: {raw.get('action')!r}") from None
    subject = raw.get("subject_stimulus_id")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("the response names no subject stimulus")
    verbatim = raw.get("verbatim")
    if verbatim is not None and not isinstance(verbatim, str):
        raise ValueError("the response's verbatim is not text")
    if verbatim is not None and not verbatim.strip():
        verbatim = None
    if action in TEXT_ACTIONS and verbatim is None:
        raise ValueError(f"a {action.value} produces text, so it needs a verbatim")
    importance = raw.get("importance")
    if importance is not None:
        try:
            importance = float(importance)
        except (TypeError, ValueError):
            raise ValueError("the response's importance is not a number") from None
        if not 0.0 <= importance <= 1.0:
            raise ValueError(f"the response's importance {importance} is outside 0-1")
    return ParsedReaction(subject_stimulus_id=subject.strip(), action=action, verbatim=verbatim, importance=importance)
