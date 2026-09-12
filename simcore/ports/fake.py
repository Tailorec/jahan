"""The deterministic `ChatPort`: the same prompt always yields the same completion.

Keyed by the prompt it is given, so two runs in one process or two see identical answers. A prompt
that carries the completion request's JSON answers with the first offered value for every persona
named; a test replaces the responder to force an off-list answer or a bad response.

An answer longer than its `max_tokens` budget is cut off, as a real provider would cut it, at roughly
four characters a token. A fake that ignored the budget once let a single completion call carry two
thousand personas and a ten-thousand-token answer under a limit of 1024 — a request no provider
could have honoured, passing every test."""

import hashlib
import json
from collections.abc import Callable, Sequence

from simcore.schemas import Completion, CostRecorded, InferenceRole, InferenceRoute

from .chat import ChatMessage

CHARACTERS_PER_TOKEN = 4


class FakeChat:
    def __init__(
        self,
        responder: Callable[[Sequence[ChatMessage], str], str] | None = None,
        *,
        model_id: str = "fake/chat",
    ) -> None:
        self._responder = responder or _first_offered
        self._model_id = model_id
        self.calls: list[str] = []

    def chat(
        self,
        role: InferenceRole,
        messages: Sequence[ChatMessage],
        *,
        temp: float,
        max_tokens: int,
        template_id: str,
    ) -> Completion:
        prompt = json.dumps([dict(message) for message in messages], sort_keys=True)
        self.calls.append(prompt)
        text = self._responder(messages, template_id)[: max_tokens * CHARACTERS_PER_TOKEN]
        return Completion(
            text=text,
            template_id=template_id,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            latency_ms=0,
            cost=CostRecorded(
                kind="cost",
                role=role,
                model_id=self._model_id,
                route=InferenceRoute.PRIMARY,
                input_tokens=len(prompt.split()),
                output_tokens=len(text.split()),
                cost=0.0,
            ),
        )


def _first_offered(messages: Sequence[ChatMessage], template_id: str) -> str:
    request = _request(messages)
    values = request.get("values")
    personas = request.get("personas", [])
    if not isinstance(values, list) or not values:
        return "{}"
    return json.dumps({persona["persona_id"]: values[0] for persona in personas}, sort_keys=True)


def _request(messages: Sequence[ChatMessage]) -> dict:
    for message in reversed(list(messages)):
        if message.get("role") != "user":
            continue
        try:
            parsed = json.loads(message["content"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
