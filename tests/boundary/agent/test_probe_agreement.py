"""What the probe can actually measure.

The first probe asked "What is your exercise_frequency?" and compared the answer with the
attribute's code by string equality. A persona answering as itself — "three or four times a
week" — disagreed with its own attribute `3_plus_weekly`, so a faithful run reported total
drift, and a probe whose own call failed reported drift too. The probe asks a closed
question instead: the persona's own value among distractors from the attribute's domain.
"""

from __future__ import annotations

import json

from simcore.agent import AgentConfig, turns
from simcore.agent._probe import agrees, probe_options, probe_result
from simcore.ports.fake import FakeChat
from simcore.schemas import CompletedTurn
from tests.boundary.agent.support import impression_of, make_job
from tests.boundary.agent.test_conditioning import ontology


def answering_in_its_own_words(messages, template_id: str) -> str:
    """A persona that is entirely in character, in its own words."""
    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    if "questions" in user:
        return json.dumps({"answers": ["I get to the gym three or four times a week"] * len(user["questions"])})
    shown = impression_of(messages)["exposures"]
    return json.dumps({"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "noted"})


def choosing_its_own_value(messages, template_id: str) -> str:
    """A persona that picks its own value from the options offered."""
    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    if "questions" in user:
        system = messages[0]["content"]
        held = {}
        for line in system.splitlines():
            if line.startswith("- ") and ": " in line:
                name, _, value = line[2:].partition(": ")
                held[name.strip()] = value.strip()
        answers = []
        for question in user["questions"]:
            attribute = question["attribute"] if isinstance(question, dict) else ""
            answers.append(held.get(attribute, "?"))
        return json.dumps({"answers": answers})
    shown = impression_of(messages)["exposures"]
    return json.dumps({"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "noted"})


def probing_config(**overrides) -> AgentConfig:
    return AgentConfig(run_seed=7, probe_share=1.0, probe_every_ticks=10, probe_questions=1, **overrides)


def test_a_probe_question_offers_the_attributes_own_domain():
    options = probe_options("exercise_frequency", "3_plus_weekly", ontology(), run_seed=7, tick=10, count=4)
    assert "3_plus_weekly" in options
    assert len(options) > 1, "a closed question needs something to choose between"
    assert options == probe_options("exercise_frequency", "3_plus_weekly", ontology(), run_seed=7, tick=10, count=4)


def test_an_attribute_with_no_known_domain_is_not_asked_about():
    assert probe_options("unknown_attribute", "whatever", ontology(), run_seed=7, tick=10, count=4) == ()


def test_a_persona_choosing_its_own_value_agrees():
    chat = FakeChat(choosing_its_own_value)
    (outcome,) = turns([make_job(0, tick=10)], chat=chat, config=probing_config(), ontology=ontology())
    assert isinstance(outcome, CompletedTurn) and outcome.probe is not None
    assert outcome.probe.disagreement_rate == 0.0
    assert all(answer.options for answer in outcome.probe.answers)


def test_an_answer_naming_its_option_agrees_however_it_is_written():
    assert agrees("3_plus_weekly", "3_plus_weekly is me", ("3_plus_weekly", "1_2_weekly")) is True
    assert agrees("3_plus_weekly", "  3 PLUS WEEKLY  ", ("3_plus_weekly", "1_2_weekly")) is True


def test_an_answer_naming_no_option_is_unreadable_rather_than_drift():
    """A persona answering in prose chose nothing; that is a probe we cannot read, not drift."""
    prose = "I get to the gym three or four times a week"
    assert agrees("3_plus_weekly", prose, ("3_plus_weekly", "1_2_weekly")) is False
    result = probe_result("p-000001", 10, [("exercise_frequency", "3_plus_weekly", ("3_plus_weekly", "1_2_weekly"))], [prose])
    assert result.answers[0].answered is False and result.answers[0].agreed is False
    assert result.disagreement_rate == 0.0 and result.answered_count == 0


def test_an_answer_naming_another_option_is_drift():
    assert agrees("3_plus_weekly", "1_2_weekly", ("3_plus_weekly", "1_2_weekly")) is False


def test_a_probe_whose_call_failed_is_not_counted_as_drift():
    result = probe_result("p-000001", 10, [("exercise_frequency", "3_plus_weekly", ("3_plus_weekly", "1_2_weekly"))], None)
    assert result.answers[0].answered is False
    assert result.answers[0].agreed is False
    assert result.disagreement_rate == 0.0, "a call that never answered says nothing about drift"
    assert result.answered_count == 0
