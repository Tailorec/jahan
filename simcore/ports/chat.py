"""The `ChatPort` protocol: the one way a core module reaches a chat model.

A batch of requests goes in and one outcome per request comes back in request order — a `Completion`
or a recorded `CallFailure` — so a caller never depends on network timing and one failure never
aborts or erases the rest of its batch (ADR 0023). `chat()` is exactly a batch of one. Which provider
answers, how it is retried and what it costs is the inference module's business, not the caller's."""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from simcore.schemas import ChatOutcome, ChatRequest, InferenceRole

ChatMessage = Mapping[str, str]


@runtime_checkable
class ChatPort(Protocol):
    def complete(self, requests: Sequence[ChatRequest], on_outcome=None) -> tuple[ChatOutcome, ...]: ...

    def chat(
        self,
        role: InferenceRole,
        messages: Sequence[ChatMessage],
        *,
        temp: float,
        max_tokens: int,
        template_id: str,
        sample=None,
        json_schema: str | None = None,
    ) -> ChatOutcome: ...
