"""The batch turn: jobs in, outcomes out, in request order.

Batching coalesces calls, never contexts: every job still gets its own prompt carrying
that persona alone. One persona's failed call is recorded as its own outcome beside the
others. A single turn is `turns([job])[0]` — the same code path, not a simpler one.
"""

from __future__ import annotations

from collections.abc import Sequence

from simcore.schemas import (
    ActionKind,
    BeliefChange,
    CallFailure,
    ChatRequest,
    CompletedTurn,
    Completion,
    Reaction,
    Turn,
    TurnFailure,
    TurnFailureKind,
    TurnJob,
    TurnOutcome,
)

from ._config import AgentConfig
from ._ids import reaction_id
from ._parse import ParsedReaction, parse_reaction
from ._prompt import REACTION_QUESTION, assemble_prompt, hash_text, prompt_messages, render_persona_block


def turns(
    jobs: Sequence[TurnJob],
    *,
    chat,
    config: AgentConfig | None = None,
) -> tuple[TurnOutcome, ...]:
    """One outcome per job in request order: a completed turn or a recorded turn failure."""
    cfg = config or AgentConfig()
    prepared = [_prepare(job, index, cfg) for index, job in enumerate(jobs)]
    requests = [item.request for item in prepared]
    completions: tuple = chat.complete(requests) if requests else ()
    return tuple(_finish(item, outcome, index, cfg) for index, (item, outcome) in enumerate(zip(prepared, completions)))


class _Prepared:
    __slots__ = ("job", "request", "persona_block", "persona_block_hash", "prompt_text")

    def __init__(self, job: TurnJob, request: ChatRequest, persona_block: str, persona_block_hash: str, prompt_text: str) -> None:
        self.job = job
        self.request = request
        self.persona_block = persona_block
        self.persona_block_hash = persona_block_hash
        self.prompt_text = prompt_text


def _prepare(job: TurnJob, index: int, cfg: AgentConfig) -> _Prepared:
    block = render_persona_block(job.persona.conditioning, job.persona.attributes)
    impression_json = job.presentation.impression.model_dump_json()
    view_json = job.presentation.view.model_dump_json()
    text = assemble_prompt(block, impression_json, view_json, REACTION_QUESTION)
    messages = prompt_messages(block, impression_json, view_json, REACTION_QUESTION)
    request = ChatRequest(
        role=cfg.tier_for(job.task),
        messages=tuple(dict(message) for message in messages),
        temp=0.0,
        max_tokens=cfg.max_tokens,
        template_id=cfg.template_id,
    )
    return _Prepared(job, request, block, hash_text(block), text)


def _finish(item: _Prepared, outcome: Completion | CallFailure, index: int, cfg: AgentConfig) -> TurnOutcome:
    job = item.job
    impression = job.presentation.impression
    if isinstance(outcome, CallFailure):
        return TurnFailure(
            persona_id=job.persona.persona_id,
            impression_id=impression.impression_id,
            kind=TurnFailureKind.CALL_FAILED,
            detail=f"the {outcome.kind.value} call failed: {outcome.detail}",
        )
    try:
        parsed = parse_reaction(outcome.text)
    except ValueError as error:
        return TurnFailure(
            persona_id=job.persona.persona_id,
            impression_id=impression.impression_id,
            kind=TurnFailureKind.CALL_FAILED,
            detail=f"the response could not be used: {error}",
        )
    shown = {exposure.stimulus_id for exposure in impression.exposures}
    if parsed.subject_stimulus_id not in shown:
        return TurnFailure(
            persona_id=job.persona.persona_id,
            impression_id=impression.impression_id,
            kind=TurnFailureKind.CALL_FAILED,
            detail=f"the response is about {parsed.subject_stimulus_id}, which the impression did not show",
        )
    seen = [exposure.stimulus_id for exposure in impression.exposures if exposure.seen]
    action, verbatim, subject = _settle(parsed, seen, impression.exposures[0].stimulus_id)
    reaction = Reaction(
        reaction_id=reaction_id(outcome.prompt_hash, job.persona.persona_id, index),
        subject_stimulus_id=subject,
        action=action,
        verbatim=verbatim,
        belief_change=BeliefChange(),
        intent=None,
    )
    turn = Turn(impression=impression, view=job.presentation.view, reaction=reaction)
    return CompletedTurn(
        turn=turn,
        template_id=outcome.template_id,
        prompt_hash=outcome.prompt_hash,
        persona_block_hash=item.persona_block_hash,
    )


def _settle(parsed: ParsedReaction, seen: list[str], first_shown: str) -> tuple[ActionKind, str | None, str]:
    """A reaction engages with what the persona noticed; what passed unnoticed gets no reply."""
    if parsed.action is ActionKind.IGNORE or parsed.subject_stimulus_id in seen:
        return parsed.action, parsed.verbatim, parsed.subject_stimulus_id
    if seen:
        return parsed.action, parsed.verbatim, seen[0]
    return ActionKind.IGNORE, None, first_shown
