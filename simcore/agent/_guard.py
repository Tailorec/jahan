"""Guardrails: what happens when the model invents.

Two rules only, and this module is their only home — a scan over the package asserts no
third rule exists. A response referring to a stimulus that was in neither the
impression, the view nor the persona's retrieved memories is rejected; output that
cannot be parsed for the task is rejected the same way. Either rejection is retried
once with a stricter instruction and then recorded as a `guardrail_violation` carrying
the impression, the view, both prompt hashes and the rule broken — in place of a
reaction, so the persona does not react that tick.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from simcore.schemas import GuardrailRule

from ._parse import ParsedReaction

# The closed set. A third rule cannot be added silently: the boundary test asserts this
# tuple holds every rule the package enforces.
GUARDRAILS: tuple[GuardrailRule, ...] = (
    GuardrailRule.REFERENCES_UNSHOWN_STIMULUS,
    GuardrailRule.UNPARSEABLE_OUTPUT,
)

_STIMULUS_PATTERN = re.compile(r"st-[0-9a-hjkmnp-tv-z]{25}")

STRICT_SUFFIX = (
    " Your previous answer was rejected because it referred to something you were never "
    "shown, or it could not be parsed. Answer again about exactly one of these stimulus "
    "ids: {allowed}. Reply with the JSON object only."
)


@dataclass(frozen=True)
class Rejection:
    rule: GuardrailRule
    detail: str


def allowed_stimuli(shown: set[str], retrieved_descriptions: tuple[str, ...]) -> set[str]:
    """Every stimulus id the response may name: shown now, or recalled from before."""
    allowed = set(shown)
    for description in retrieved_descriptions:
        allowed.update(_STIMULUS_PATTERN.findall(description))
    return allowed


def check(
    parsed: ParsedReaction | None,
    error: str | None,
    *,
    shown: set[str],
    retrieved_descriptions: tuple[str, ...],
) -> Rejection | None:
    """The guardrail verdict on one response: rejected with its rule, or accepted."""
    if parsed is None:
        return Rejection(rule=GuardrailRule.UNPARSEABLE_OUTPUT, detail=f"the response could not be parsed: {error}")
    allowed = allowed_stimuli(shown, retrieved_descriptions)
    if parsed.subject_stimulus_id not in allowed:
        return Rejection(
            rule=GuardrailRule.REFERENCES_UNSHOWN_STIMULUS,
            detail=f"the response is about {parsed.subject_stimulus_id}, which was in neither the impression, the view nor the retrieved memories",
        )
    if parsed.verbatim:
        strangers = sorted(set(_STIMULUS_PATTERN.findall(parsed.verbatim)) - allowed)
        if strangers:
            return Rejection(
                rule=GuardrailRule.REFERENCES_UNSHOWN_STIMULUS,
                detail=f"the response refers to {strangers}, which were in neither the impression, the view nor the retrieved memories",
            )
    return None


def strict_question(allowed: set[str]) -> str:
    from ._prompt import REACTION_QUESTION

    return REACTION_QUESTION + STRICT_SUFFIX.format(allowed=", ".join(sorted(allowed)))
