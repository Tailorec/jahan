"""The inference domain: what a model call returns — a completion, or a failure recorded as one."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import FrozenDict, HashDigest, Identifier, NonEmptyStr, NonNegativeInt, PersonaId, PositiveInt, SimBaseModel
from .enums import FailureKind, InferenceRole, InferenceRoute
from .trace import CostRecorded


class SampleKey(SimBaseModel):
    """The identity of one draw: which world, which persona, which tick, which call within it. A seed is
    derived from it, and any sampled call is cached under it, so two replicates can never be handed the
    same sample (ADR 0025)."""

    world_seed: NonNegativeInt
    persona_id: PersonaId | None = None
    tick: NonNegativeInt = 0
    seq: NonNegativeInt = 0


class ChatRequest(SimBaseModel):
    """One chat call as its caller states it: a role, the rendered messages, the sampling budget, the
    template that produced the text, and — where the call is sampled — the draw it belongs to. A request
    above temperature zero must name its sample key, or its answer could be served to another replicate.

    `json_schema` is the JSON text of the schema a structured answer must satisfy: carried as text so a
    request stays immutable, and sent as a strict response format only where the pin declares the
    capability (ADR 0023)."""

    role: InferenceRole
    messages: tuple[FrozenDict[str, str], ...] = Field(min_length=1)
    temp: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    max_tokens: PositiveInt
    template_id: Identifier
    sample: SampleKey | None = None
    json_schema: str | None = None

    @model_validator(mode="after")
    def _messages_are_roles_with_content(self) -> Self:
        for message in self.messages:
            if "role" not in message or "content" not in message:
                raise ValueError("every message carries a role and content")
            if message["role"] not in ("system", "user", "assistant", "tool"):
                raise ValueError(f"message role {message['role']!r} is not one a chat endpoint speaks")
        return self

    @model_validator(mode="after")
    def _a_sampled_call_belongs_to_one_draw(self) -> Self:
        if self.temp > 0.0 and self.sample is None:
            raise ValueError(
                "a call above temperature zero names the sample it is a draw of — replicate seed, persona, "
                "tick and sequence — so its answer can never be shared with another replicate (ADR 0025)"
            )
        return self


class Completion(SimBaseModel):
    """What one chat call returned: its text, the template it rendered, its prompt hash and latency, and the exact
    cost record it produced. The runner appends that record to the trace as-is, so cost has one source.

    A seed is recorded here when the call was sent one: it names what the engine asked for, never what the
    provider promised, because determinism comes from replay, not from a seed a provider may ignore."""

    text: str
    template_id: Identifier
    prompt_hash: HashDigest
    latency_ms: NonNegativeInt
    cost: CostRecorded
    seed: PositiveInt | None = None

    @model_validator(mode="after")
    def _chat_roles_only(self) -> Self:
        if self.cost.role is InferenceRole.EMBED:
            raise ValueError("embedding calls return vectors, not completions; they are billed without one")
        return self


class CallFailure(SimBaseModel):
    """A model call that returned no completion, recorded as an outcome beside the completions around it
    rather than raised: a caller must never mistake a network event for a persona declining to act.
    It names what went wrong, how many attempts made it that far — none, for a call the circuit breaker
    short-circuited — and which route was last tried."""

    kind: FailureKind
    detail: NonEmptyStr
    attempts: NonNegativeInt
    route: InferenceRoute


ChatOutcome = Completion | CallFailure
