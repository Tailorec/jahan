"""A persona is offered the actions its channel can land, and no others.

The first real study ran 897 turns in a survey room, which affords exactly one action —
`answer`. The question offered all fifteen, so 625 personas asked a peer, 268 replied, and
two answered: 895 turns produced an action the room discards. The world's affordance check
was working; it was being asked the wrong question.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from simcore.agent import AgentConfig, turns
from simcore.ports.chat import ChatMessage
from simcore.ports.fake import FakeChat
from simcore.schemas import CHANNEL_AFFORDANCES, Channel
from simcore.schemas import TurnJob
from tests.boundary.agent.support import job_payload


def _capture():
    seen: dict[str, str] = {}

    def respond(messages: Sequence[ChatMessage], template_id: str) -> str:
        user = json.loads(next(m for m in reversed(list(messages)) if m.get("role") == "user")["content"])
        if "questions" in user:
            return json.dumps({"answers": [q.get("options", ["x"])[0] for q in user["questions"]]})
        seen.setdefault("question", user["question"])
        return json.dumps({
            "subject_stimulus_id": user["shown"][0]["stimulus_id"],
            "action": "ignore",
            "verbatim": "nothing for me",
        })

    return seen, respond


def _question_for_channel(channel: str) -> str:
    seen, respond = _capture()
    payload = job_payload(0, tick=3)
    payload["presentation"]["impression"]["channel"] = channel
    job = TurnJob.model_validate(payload)
    turns([job], chat=FakeChat(respond), config=AgentConfig(run_seed=7))
    return seen["question"]


def test_a_survey_room_offers_only_the_action_it_affords():
    question = _question_for_channel("survey_room")
    assert "answer" in question
    for unafforded in ("ask_peer", "reply", "upvote", "repost", "follow"):
        assert unafforded not in question, f"a survey room cannot land {unafforded}"


def test_ignore_is_always_offered_because_it_always_lands():
    assert "ignore" in _question_for_channel("survey_room")


def test_a_social_feed_offers_what_a_feed_affords():
    question = _question_for_channel("social_feed")
    for afforded in CHANNEL_AFFORDANCES[Channel.SOCIAL_FEED]:
        assert afforded.value in question, f"a feed affords {afforded.value} and did not offer it"


def _question_for_task(task: str, channel: str = "survey_room") -> str:
    seen, respond = _capture()
    payload = job_payload(0, tick=3)
    payload["presentation"]["impression"]["channel"] = channel
    payload["task"] = task
    turns([TurnJob.model_validate(payload)], chat=FakeChat(respond), config=AgentConfig(run_seed=7))
    return seen["question"]


def test_a_purchase_intent_turn_still_asks_for_the_turn_object():
    """The intent question replaced the whole envelope, so the model answered in prose and the
    parser — which reads `subject_stimulus_id`, `action`, `verbatim` and `belief_deltas`, and
    whose verbatim is the very text `score_intents` scores — rejected all of it. The first study
    that asked for intent recorded 1000 unparseable outputs and not one turn."""
    question = _question_for_task("purchase")
    assert "purchase the product" in question, "the SSR question is asked"
    for key in ("subject_stimulus_id", "action", "verbatim", "belief_deltas"):
        assert key in question, f"the turn envelope lost {key}"
    assert "ask_peer" not in question, "a survey room still offers only what it affords"


def test_a_purchase_intent_turn_still_forbids_a_number():
    question = _question_for_task("purchase")
    assert "Do not use numbers" in question
