"""The agent's boundary: what one turn is asked, and what comes back.

A batch of jobs answers as a batch of outcomes in request order — a completed turn or a recorded
failure, never an exception for one persona and never a silent gap (ADR 0031). A persona's state
travels in and out, so any worker can take any persona and the agent stores nothing (ADR 0030).
"""

from typing import Self

from pydantic import model_validator

from .base import HashDigest, Identifier, PersonaId, SimBaseModel
from .enums import GuardrailRule, TurnFailureKind, TurnTask
from .persona import Persona
from .inference import CostRecorded
from .sim import BeliefChange, ImpressionId, MemoryEvent, MemoryId, PersonaState, Presentation, ProbeResult, Turn


class TurnJob(SimBaseModel):
    """One persona, what it carries, and what it was shown."""

    persona: Persona
    state: PersonaState
    presentation: Presentation
    task: TurnTask = TurnTask.REACTION

    @model_validator(mode="after")
    def _one_persona_throughout(self) -> Self:
        whose = self.persona.persona_id
        if self.state.persona_id != whose:
            raise ValueError(f"a job for {whose} carries the state of {self.state.persona_id}")
        shown_to = self.presentation.impression.persona_id
        if shown_to != whose:
            raise ValueError(f"a job for {whose} carries an impression shown to {shown_to}")
        return self


class CompletedTurn(SimBaseModel):
    """A turn that happened: what the persona did, what it now remembers, how its beliefs moved, and
    the hashes the trace records so a prompt can be compared without being stored."""

    turn: Turn
    template_id: Identifier
    prompt_hash: HashDigest
    persona_block_hash: HashDigest
    memory_ids: tuple[MemoryId, ...] = ()
    rejected_prompt_hashes: tuple[HashDigest, ...] = ()
    memories: tuple[MemoryEvent, ...] = ()
    belief_change: BeliefChange = BeliefChange()
    probe: ProbeResult | None = None
    # Every call this turn made, as the ports billed it: the reaction, any stricter retry, a
    # reflection, a probe and the embeddings. The runner writes them against this persona, so a
    # turn that dropped them would make the study's spend unrecoverable.
    costs: tuple[CostRecorded, ...] = ()

    @property
    def persona_id(self) -> str:
        return self.turn.impression.persona_id

    @model_validator(mode="after")
    def _recalls_only_what_it_already_held(self) -> Self:
        written = {memory.memory_id for memory in self.memories}
        both = sorted(written & set(self.memory_ids))
        if both:
            raise ValueError(f"a turn recalls a memory it wrote in the same breath: {both}")
        return self

    @model_validator(mode="after")
    def _a_probe_belongs_to_the_persona_who_answered(self) -> Self:
        if self.probe is not None and self.probe.persona_id != self.persona_id:
            raise ValueError(f"a turn by {self.persona_id} carries a probe answered by {self.probe.persona_id}")
        return self


class TurnFailure(SimBaseModel):
    """A job that produced no reaction, recorded beside the outcomes that did."""

    persona_id: PersonaId
    impression_id: ImpressionId
    kind: TurnFailureKind
    detail: str
    rule: GuardrailRule | None = None
    prompt_hashes: tuple[HashDigest, ...] = ()
    # What the failed attempt billed anyway: an endpoint that charged for an answer it never
    # returned is still spend, and a ledger that ignores it undercounts the run.
    costs: tuple[CostRecorded, ...] = ()

    @model_validator(mode="after")
    def _a_violation_names_its_rule_and_both_attempts(self) -> Self:
        violation = self.kind is TurnFailureKind.GUARDRAIL_VIOLATION
        if violation:
            if self.rule is None:
                raise ValueError("a guardrail violation names the rule it broke")
            if len(self.prompt_hashes) != 2 or self.prompt_hashes[0] == self.prompt_hashes[1]:
                raise ValueError("a violation follows a retry, so it carries two attempts that differ")
        elif self.rule is not None or self.prompt_hashes:
            raise ValueError(f"only a guardrail violation names a rule and its attempts; {self.kind.value} names neither")
        if not self.detail.strip():
            raise ValueError("a failure says what went wrong")
        return self


TurnOutcome = CompletedTurn | TurnFailure
