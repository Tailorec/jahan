"""The batch turn: jobs in, outcomes out, in request order.

Batching coalesces calls, never contexts: every job still gets its own prompt carrying
that persona alone. One persona's failed call is recorded as its own outcome beside the
others. A single turn is `turns([job])[0]` — the same code path, not a simpler one.

Dispatch is refused before any model call when the persona block is empty
(`unconditioned`), or when the tier's budget cannot hold the block (`context_exceeded`).
"""

from __future__ import annotations

from collections.abc import Sequence

from simcore.schemas import (
    ActionKind,
    BeliefChange,
    CallFailure,
    CategoryOntology,
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
from ._context import ContextBudgetExceeded, assemble, render_beliefs
from ._ids import reaction_id
from ._parse import ParsedReaction, parse_reaction
from ._prompt import REACTION_QUESTION, hash_text, render_persona_block
from ._render import PersonaBlockCache


def turns(
    jobs: Sequence[TurnJob],
    *,
    chat,
    config: AgentConfig | None = None,
    ontology: CategoryOntology | None = None,
    blocks: PersonaBlockCache | None = None,
) -> tuple[TurnOutcome, ...]:
    """One outcome per job in request order: a completed turn or a recorded turn failure."""
    cfg = config or AgentConfig()
    cache = blocks if blocks is not None else PersonaBlockCache()
    prepared = [_prepare(job, index, cfg, ontology, cache) for index, job in enumerate(jobs)]
    dispatch = [(position, item) for position, item in enumerate(prepared) if item.request is not None]
    completions: dict[int, Completion | CallFailure] = {}
    if dispatch:
        outcomes = chat.complete([item.request for _, item in dispatch])
        completions = {position: outcome for (position, _), outcome in zip(dispatch, outcomes)}
    results: list[TurnOutcome] = []
    for position, item in enumerate(prepared):
        if item.early is not None:
            results.append(item.early)
        else:
            results.append(_finish(item, completions[position], position, cfg))
    return tuple(results)


class _Prepared:
    __slots__ = ("early", "job", "memory_ids", "persona_block_hash", "request")

    def __init__(
        self,
        job: TurnJob,
        request: ChatRequest | None,
        persona_block_hash: str,
        memory_ids: tuple[str, ...],
        early: TurnFailure | None,
    ) -> None:
        self.job = job
        self.request = request
        self.persona_block_hash = persona_block_hash
        self.memory_ids = memory_ids
        self.early = early


def _prepare(
    job: TurnJob, index: int, cfg: AgentConfig, ontology: CategoryOntology | None, cache: PersonaBlockCache
) -> _Prepared:
    impression = job.presentation.impression
    if ontology is None:
        block = render_persona_block(job.persona.conditioning, job.persona.attributes)
        block_hash = hash_text(block)
    else:
        block, block_hash = cache.block_for(job.persona, ontology)
    if not block.strip():
        return _Prepared(
            job,
            None,
            block_hash,
            (),
            TurnFailure(
                persona_id=job.persona.persona_id,
                impression_id=impression.impression_id,
                kind=TurnFailureKind.UNCONDITIONED,
                detail="refused before dispatch: the persona block is empty, so the turn would answer as nobody in particular",
            ),
        )
    beliefs = job.state.beliefs
    beliefs_text = render_beliefs(
        {dim.value: value for dim, value in beliefs.dimensions.items()},
        dict(beliefs.claim_credence),
    )
    memory_texts = tuple(f"[tick {memory.tick}] {memory.description}" for memory in job.state.memories)
    tier = cfg.tier_for(job.task)
    try:
        assembled = assemble(
            persona_block=block,
            persona_block_hash=block_hash,
            beliefs_text=beliefs_text,
            memory_texts=memory_texts,
            impression_json=impression.model_dump_json(),
            view_json=job.presentation.view.model_dump_json(),
            question=REACTION_QUESTION,
            budget=cfg.token_budget[tier],
        )
    except ContextBudgetExceeded as error:
        return _Prepared(
            job,
            None,
            block_hash,
            (),
            TurnFailure(
                persona_id=job.persona.persona_id,
                impression_id=impression.impression_id,
                kind=TurnFailureKind.CONTEXT_BUDGET_EXCEEDED,
                detail=f"refused before dispatch: {error}",
            ),
        )
    request = ChatRequest(
        role=tier,
        messages=tuple(dict(message) for message in assembled.messages),
        temp=0.0,
        max_tokens=cfg.max_tokens,
        template_id=cfg.template_id,
    )
    return _Prepared(job, request, block_hash, (), None)


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
