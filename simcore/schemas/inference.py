"""The inference domain: what one model call returns."""

from typing import Self

from pydantic import model_validator

from .base import HashDigest, Identifier, NonNegativeInt, SimBaseModel
from .enums import InferenceRole
from .trace import CostRecorded


class Completion(SimBaseModel):
    """What one chat call returned: its text, the template it rendered, its prompt hash and latency, and the exact
    cost record it produced. The runner appends that record to the trace as-is, so cost has one source."""

    text: str
    template_id: Identifier
    prompt_hash: HashDigest
    latency_ms: NonNegativeInt
    cost: CostRecorded

    @model_validator(mode="after")
    def _chat_roles_only(self) -> Self:
        if self.cost.role is InferenceRole.EMBED:
            raise ValueError("embedding calls return vectors, not completions; they are billed without one")
        return self
