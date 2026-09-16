"""The inference domain: what a model call returns — a completion, or a failure recorded as one."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import HashDigest, Identifier, NonEmptyStr, NonNegativeInt, PositiveInt, SimBaseModel
from .enums import FailureKind, InferenceRole, InferenceRoute
from .trace import CostRecorded


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
    It names what went wrong, how many attempts made it that far, and which route was last tried."""

    kind: FailureKind
    detail: NonEmptyStr
    attempts: PositiveInt
    route: InferenceRoute


ChatOutcome = Completion | CallFailure


class CompletedDistribution(SimBaseModel):
    """The probability distribution a completed field was sampled from, in the vocabulary's own order.
    Recorded so projection's calibration can be measured after the fact: a sampled value without its
    distribution is a number nobody can check (ADR 0019, ADR 0024)."""

    values: tuple[NonEmptyStr, ...] = Field(min_length=1)
    probabilities: tuple[Annotated[float, Field(ge=0.0)], ...]

    @model_validator(mode="after")
    def _covers_the_vocabulary_once(self) -> Self:
        if len(self.values) != len(self.probabilities):
            raise ValueError(
                f"a distribution names {len(self.probabilities)} probabilities for {len(self.values)} vocabulary values"
            )
        if len(set(self.values)) != len(self.values):
            raise ValueError("a distribution's vocabulary repeats a value")
        total = sum(self.probabilities)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"a distribution must sum to one, got {total}")
        return self
