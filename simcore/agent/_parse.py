"""Parsing a completion into reaction parts, per task type.

Phase 2 parses the plain reaction shape. Phase 6 moves unparseable output and
references to stimuli never shown onto the one-retry guardrail path; until then an
answer the turn cannot use is a recorded call failure, never a silent gap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from simcore.schemas import ActionKind, BeliefChange, BeliefDim

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

_CLAIM_PATTERN = re.compile(r"^C[1-9][0-9]*$")
_DIMENSIONS = {dim.value for dim in BeliefDim}


@dataclass(frozen=True)
class ParsedReaction:
    subject_stimulus_id: str
    action: ActionKind
    verbatim: str | None
    # Tier B only: the model rates the memory's importance inside the call already being
    # made, so importance adds no call of its own. Absent on tier A, where the rule decides.
    importance: float | None = None
    # What the turn moved, across the closed dimension set and per claim.
    belief_change: BeliefChange = field(default_factory=BeliefChange)


@dataclass(frozen=True)
class ParsedReflection:
    belief_change: BeliefChange
    summary: str


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
    change = _belief_change(raw.get("belief_deltas"))
    return ParsedReaction(subject_stimulus_id=subject.strip(), action=action, verbatim=verbatim, importance=importance, belief_change=change)


def parse_reflection(text: str) -> ParsedReflection:
    """Parse a reflection response into a further belief change and a consolidation summary."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError(f"the reflection is not parseable JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"the reflection is a {type(raw).__name__}, not an object")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("the reflection consolidates nothing: its summary is empty")
    return ParsedReflection(belief_change=_belief_change(raw), summary=summary.strip())


def _belief_change(raw: object) -> BeliefChange:
    """Deltas across the closed dimension set and per claim; only moved entries appear."""
    if raw is None:
        return BeliefChange()
    if not isinstance(raw, dict):
        raise ValueError("belief deltas are an object with dimensions and claim credences")
    dimensions = _deltas(raw.get("dimensions"), _DIMENSIONS, "dimension")
    claims = _deltas(raw.get("claim_credence"), None, "claim")
    return BeliefChange(dimensions=dimensions, claim_credence=claims)


def _deltas(raw: object, vocabulary: set[str] | None, kind: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"belief {kind} deltas are an object when present")
    moves = {}
    for name, delta in raw.items():
        if vocabulary is not None and name not in vocabulary:
            raise ValueError(f"{name!r} is not one of the closed belief dimensions {sorted(vocabulary)}")
        if vocabulary is None and (not isinstance(name, str) or not _CLAIM_PATTERN.match(name)):
            raise ValueError(f"{name!r} is not a claim of the brief")
        try:
            value = float(delta)
        except (TypeError, ValueError):
            raise ValueError(f"the belief move on {name!r} is not a number") from None
        if not -1.0 <= value <= 1.0:
            raise ValueError(f"the belief move on {name!r} is outside -1..1")
        if value != 0.0:
            moves[name] = value
    return moves
