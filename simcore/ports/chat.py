"""The `ChatPort` protocol: the one way a core module reaches a chat model.

The engine builds a prompt and reads text back; which provider answers, how it is retried and what it
costs is the inference module's business, not the caller's. Projection asks for its sparse fields to
be completed through this port, so its determinism under a fake is the same code path as production.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from simcore.schemas import Completion, InferenceRole

ChatMessage = Mapping[str, str]


@runtime_checkable
class ChatPort(Protocol):
    def chat(
        self,
        role: InferenceRole,
        messages: Sequence[ChatMessage],
        *,
        temp: float,
        max_tokens: int,
        template_id: str,
    ) -> Completion: ...
