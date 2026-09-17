"""Builders for agent boundary tests: jobs with distinctive personas, fake responders."""

from __future__ import annotations

import json
from collections.abc import Sequence

from simcore.ports.chat import ChatMessage
from simcore.ports.fake import FakeChat
from simcore.schemas import CallFailure, FailureKind, InferenceRoute, TurnJob
from tests.study_builders import beliefs_payload, persona_payload, stimulus_id, turn_payload

DISTINCT_AGES = ["25_34", "35_44", "45_54", "55_64"]


def job_payload(persona_index: int = 0, tick: int = 3, n: int = 0, **overrides) -> dict:
    persona_id = f"p-00000{persona_index + 1}"
    shown = overrides.pop("shown", [(1, "interest", 0.8)])
    whole = turn_payload(persona_id, tick, shown, {}, None, n)
    payload = {
        "persona": persona_payload(
            persona_index,
            persona_id=persona_id,
            conditioning={
                "age": DISTINCT_AGES[persona_index % len(DISTINCT_AGES)],
                "sex": "female",
                "exercise_frequency": "3_plus_weekly",
            },
        ),
        "state": {"persona_id": persona_id, "beliefs": beliefs_payload()},
        "presentation": {"impression": whole["impression"], "view": whole["view"]},
        "task": "reaction",
    }
    payload.update(overrides)
    return payload


def make_job(persona_index: int = 0, tick: int = 3, n: int = 0, **overrides) -> TurnJob:
    return TurnJob.model_validate(job_payload(persona_index, tick, n, **overrides))


def impression_of(messages: Sequence[ChatMessage]) -> dict:
    """The impression a prompt carries, parsed back out of the fake's recorded call."""
    user = next(message for message in reversed(list(messages)) if message.get("role") == "user")
    outer = json.loads(user["content"])
    return json.loads(outer["impression"])


def answering(action: str = "comment", verbatim: str = "the protein claim would get me", subject: str | None = None):
    """A responder that answers about the impression's first exposure (or the named subject)."""

    def respond(messages: Sequence[ChatMessage], template_id: str) -> str:
        shown = impression_of(messages)["exposures"]
        target = subject or shown[0]["stimulus_id"]
        return json.dumps({"subject_stimulus_id": target, "action": action, "verbatim": verbatim})

    return respond


class FailIndexChat(FakeChat):
    """A fake that fails the calls at the given batch positions, answering the rest."""

    def __init__(self, indices: set[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self._indices = set(indices)
        self._position = 0

    def complete(self, requests):
        outcomes = []
        for request in requests:
            if self._position in self._indices:
                outcomes.append(
                    CallFailure(
                        kind=FailureKind.TIMED_OUT,
                        detail="the endpoint timed out",
                        attempts=2,
                        route=InferenceRoute.PRIMARY,
                    )
                )
            else:
                outcomes.append(self._one(request))
            self._position += 1
        return tuple(outcomes)
