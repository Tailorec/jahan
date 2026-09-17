"""The batch turn: jobs in, outcomes out, in request order.

Batching coalesces calls, never contexts: every job still gets its own prompt carrying
that persona alone. One persona's failed call is recorded as its own outcome beside the
others. A single turn is `turns([job])[0]` — the same code path, not a simpler one.

Dispatch is refused before any model call when the persona block is empty
(`unconditioned`), or when the tier's budget cannot hold the block (`context_exceeded`).
A turn whose beliefs moved sharply, or whose persona is due, reflects in a second
batched round on tier B before its outcome is recorded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from simcore.schemas import (
    ActionKind,
    BeliefChange,
    CallFailure,
    CategoryOntology,
    ChatRequest,
    CompletedTurn,
    Completion,
    InferenceRole,
    MemoryEvent,
    MemorySource,
    Reaction,
    Turn,
    TurnFailure,
    TurnFailureKind,
    TurnJob,
    TurnOutcome,
)

from ._beliefs import (
    CONSOLIDATED_IMPORTANCE,
    advance_state,  # noqa: F401  (re-exported for the runner)
    combine,
    reflection_due,
    split_summary,
)
from ._config import AgentConfig
from ._context import ContextBudgetExceeded, assemble, render_beliefs
from ._ids import reaction_id, ulid_from
from ._memory import describe_turn, importance_of, retrieve, write_memory
from ._parse import ParsedReaction, parse_reaction, parse_reflection
from ._prompt import REACTION_QUESTION, hash_text, render_persona_block
from ._render import PersonaBlockCache

REFLECTION_QUESTION = (
    "Look back over your recent experience above. Reply with a JSON object with keys "
    "'dimensions' (an object mapping any of value, fit, trust to a belief move in -1..1), "
    "'claim_credence' (an object mapping claim ids like C1 to a move in -1..1) and "
    "'summary' (two or three sentences consolidating what changed for you). "
    "Only moved entries appear; leave out what did not move."
)


def turns(
    jobs: Sequence[TurnJob],
    *,
    chat,
    config: AgentConfig | None = None,
    ontology: CategoryOntology | None = None,
    blocks: PersonaBlockCache | None = None,
    embed=None,
    stimulus_texts: Mapping[str, str] | None = None,
) -> tuple[TurnOutcome, ...]:
    """One outcome per job in request order: a completed turn or a recorded turn failure."""
    cfg = config or AgentConfig()
    cache = blocks if blocks is not None else PersonaBlockCache()
    prepared = [_prepare(job, index, cfg, ontology, cache, embed, stimulus_texts) for index, job in enumerate(jobs)]
    dispatch = [(position, item) for position, item in enumerate(prepared) if item.request is not None]
    first: dict[int, Completion | CallFailure] = {}
    if dispatch:
        outcomes = chat.complete([item.request for _, item in dispatch])
        first = {position: outcome for (position, _), outcome in zip(dispatch, outcomes)}
    reacted = [_react(item, first[position], position) for position, item in enumerate(prepared) if item.request is not None]

    due = [entry for entry in reacted if entry.failure is None and _due(entry, cfg)]
    second: dict[int, Completion | CallFailure] = {}
    if due:
        answers = chat.complete([_reflection_request(entry, cfg) for entry in due])
        second = {entry.position: answer for entry, answer in zip(due, answers)}

    results: list[TurnOutcome] = []
    reacted_by_position = {entry.position: entry for entry in reacted}
    for position, item in enumerate(prepared):
        if item.early is not None:
            results.append(item.early)
        else:
            results.append(_finalize(reacted_by_position[position], second.get(position), cfg, embed))
    return tuple(results)


def _due(entry: _Reacted, cfg: AgentConfig) -> bool:
    return reflection_due(
        entry.item.job.state,
        entry.change,
        run_seed=cfg.run_seed,
        base=cfg.reflection_interval,
        jitter=cfg.reflection_jitter,
        threshold=cfg.reflection_delta_threshold,
    )


class _Prepared:
    __slots__ = ("early", "job", "memory_ids", "persona_block", "persona_block_hash", "request")

    def __init__(
        self,
        job: TurnJob,
        request: ChatRequest | None,
        persona_block_hash: str,
        memory_ids: tuple[str, ...],
        early: TurnFailure | None,
        persona_block: str = "",
    ) -> None:
        self.job = job
        self.request = request
        self.persona_block_hash = persona_block_hash
        self.memory_ids = memory_ids
        self.early = early
        self.persona_block = persona_block


@dataclass
class _Reacted:
    position: int
    item: _Prepared
    outcome: Completion | None = None
    parsed: ParsedReaction | None = None
    action: ActionKind = ActionKind.IGNORE
    verbatim: str | None = None
    subject: str = ""
    change: BeliefChange = BeliefChange()
    failure: TurnFailure | None = None


def _prepare(
    job: TurnJob,
    index: int,
    cfg: AgentConfig,
    ontology: CategoryOntology | None,
    cache: PersonaBlockCache,
    embed,
    stimulus_texts: Mapping[str, str] | None,
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
            block,
        )
    beliefs = job.state.beliefs
    beliefs_text = render_beliefs(
        {dim.value: value for dim, value in beliefs.dimensions.items()},
        dict(beliefs.claim_credence),
    )
    tier = cfg.tier_for(job.task)
    tau_r = max(1.0, cfg.tau_r_share * cfg.horizon_ticks)
    recalled = retrieve(
        job.state.memories,
        stimulus_text=_stimulus_text(job, stimulus_texts),
        tick=impression.tick,
        k=cfg.top_k[tier],
        tau_r=tau_r,
        embed=embed,
    )
    memory_texts = tuple(f"[tick {memory.tick}] {memory.description}" for memory in recalled)
    memory_ids = tuple(memory.memory_id for memory in recalled)
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
            block,
        )
    request = ChatRequest(
        role=tier,
        messages=tuple(dict(message) for message in assembled.messages),
        temp=0.0,
        max_tokens=cfg.max_tokens,
        template_id=cfg.template_id,
    )
    return _Prepared(job, request, block_hash, memory_ids, None, block)


def _react(item: _Prepared, outcome: Completion | CallFailure, position: int) -> _Reacted:
    job = item.job
    impression = job.presentation.impression
    if isinstance(outcome, CallFailure):
        return _Reacted(
            position,
            item,
            failure=TurnFailure(
                persona_id=job.persona.persona_id,
                impression_id=impression.impression_id,
                kind=TurnFailureKind.CALL_FAILED,
                detail=f"the {outcome.kind.value} call failed: {outcome.detail}",
            ),
        )
    try:
        parsed = parse_reaction(outcome.text)
    except ValueError as error:
        return _Reacted(
            position,
            item,
            failure=TurnFailure(
                persona_id=job.persona.persona_id,
                impression_id=impression.impression_id,
                kind=TurnFailureKind.CALL_FAILED,
                detail=f"the response could not be used: {error}",
            ),
        )
    shown = {exposure.stimulus_id for exposure in impression.exposures}
    if parsed.subject_stimulus_id not in shown:
        return _Reacted(
            position,
            item,
            failure=TurnFailure(
                persona_id=job.persona.persona_id,
                impression_id=impression.impression_id,
                kind=TurnFailureKind.CALL_FAILED,
                detail=f"the response is about {parsed.subject_stimulus_id}, which the impression did not show",
            ),
        )
    seen = [exposure.stimulus_id for exposure in impression.exposures if exposure.seen]
    action, verbatim, subject = _settle(parsed, seen, impression.exposures[0].stimulus_id)
    return _Reacted(position, item, outcome, parsed, action, verbatim, subject, parsed.belief_change)


def _stimulus_text(job: TurnJob, stimulus_texts: Mapping[str, str] | None) -> str:
    """What the persona is looking at, as retrieval text: the shown stimuli it knows."""
    parts = []
    for exposure in job.presentation.impression.exposures:
        if stimulus_texts is not None and exposure.stimulus_id in stimulus_texts:
            parts.append(stimulus_texts[exposure.stimulus_id])
    if parts:
        return "\n".join(parts)
    return job.presentation.impression.model_dump_json()


def _reflection_request(entry: _Reacted, cfg: AgentConfig) -> ChatRequest:
    job = entry.item.job
    user = {
        "beliefs": render_beliefs(
            {dim.value: value for dim, value in job.state.beliefs.dimensions.items()},
            dict(job.state.beliefs.claim_credence),
        ),
        "memories": [f"[tick {memory.tick}] {memory.description}" for memory in job.state.memories[-8:]],
        "turn": entry.parsed.verbatim or entry.action.value,
        "question": REFLECTION_QUESTION,
    }
    return ChatRequest(
        role=InferenceRole.TIER_B,
        messages=({"role": "system", "content": entry.item.persona_block}, {"role": "user", "content": json.dumps(user)}),
        temp=0.0,
        max_tokens=cfg.max_tokens,
        template_id=cfg.reflection_template_id,
    )


def _reflection_memories(
    entry: _Reacted, answer: Completion | CallFailure | None, tick: int, embed
) -> tuple[BeliefChange, tuple[MemoryEvent, ...]]:
    """The reflection's revision and its consolidated memories — or the rule-based fallback."""
    persona_id = entry.item.job.persona.persona_id
    if isinstance(answer, Completion):
        try:
            parsed = parse_reflection(answer.text)
        except ValueError:
            parsed = None
        if parsed is not None:
            memories = tuple(
                write_memory(
                    memory_uid=f"me-{ulid_from('reflection', persona_id, answer.prompt_hash, str(index))}",
                    tick=tick,
                    description=sentence,
                    importance=CONSOLIDATED_IMPORTANCE,
                    source=MemorySource.REFLECTION,
                    embed=embed,
                )
                for index, sentence in enumerate(split_summary(parsed.summary))
            )
            return parsed.belief_change, memories
    fallback = write_memory(
        memory_uid=f"me-{ulid_from('reflection-fallback', persona_id, entry.outcome.prompt_hash)}",
        tick=tick,
        description=f"On reflection: {describe_turn(entry.action, entry.subject, entry.parsed.verbatim)}",
        importance=CONSOLIDATED_IMPORTANCE,
        source=MemorySource.REFLECTION,
        embed=embed,
    )
    return BeliefChange(), (fallback,)


def _finalize(entry: _Reacted, answer: Completion | CallFailure | None, cfg: AgentConfig, embed) -> TurnOutcome:
    if entry.failure is not None:
        return entry.failure
    assert entry.outcome is not None and entry.parsed is not None
    job = entry.item.job
    impression = job.presentation.impression
    tick = impression.tick
    if answer is None:
        revision, consolidated = BeliefChange(), ()
    else:
        revision, consolidated = _reflection_memories(entry, answer, tick, embed)
    change = combine(entry.change, revision)
    if cfg.tier_for(job.task) is InferenceRole.TIER_B and entry.parsed.importance is not None:
        importance = entry.parsed.importance
    else:
        importance = importance_of(entry.action, change)
    reaction = Reaction(
        reaction_id=reaction_id(entry.outcome.prompt_hash, job.persona.persona_id, entry.position),
        subject_stimulus_id=entry.subject,
        action=entry.action,
        verbatim=entry.verbatim,
        belief_change=change,
        intent=None,
    )
    turn = Turn(impression=impression, view=job.presentation.view, reaction=reaction)
    remembered = write_memory(
        memory_uid=f"me-{ulid_from('memory', job.persona.persona_id, entry.outcome.prompt_hash)}",
        tick=tick,
        description=describe_turn(entry.action, entry.subject, entry.verbatim),
        importance=importance,
        source=MemorySource.TURN,
        embed=embed,
    )
    return CompletedTurn(
        turn=turn,
        template_id=entry.outcome.template_id,
        prompt_hash=entry.outcome.prompt_hash,
        persona_block_hash=entry.item.persona_block_hash,
        memory_ids=entry.item.memory_ids,
        memories=(remembered, *consolidated),
        belief_change=change,
    )


def _settle(parsed: ParsedReaction, seen: list[str], first_shown: str) -> tuple[ActionKind, str | None, str]:
    """A reaction engages with what the persona noticed; what passed unnoticed gets no reply."""
    if parsed.action is ActionKind.IGNORE or parsed.subject_stimulus_id in seen:
        return parsed.action, parsed.verbatim, parsed.subject_stimulus_id
    if seen:
        return parsed.action, parsed.verbatim, seen[0]
    return ActionKind.IGNORE, None, first_shown
