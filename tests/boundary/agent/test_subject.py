"""A reaction is about the proposition the persona named, or it is not recorded.

The first turn pipeline quietly reattributed a response: when the model answered about a
stimulus that was shown but not noticed, the words were kept and the subject was replaced
with something the persona never mentioned. Intent is directed at a specific proposition
(ADR 0003), so a record that moves it is worse than no record at all.
"""

from __future__ import annotations

import json

from simcore.agent import AgentConfig, turns
from simcore.ports.fake import FakeChat
from simcore.schemas import CompletedTurn, GuardrailRule, TurnFailure, TurnFailureKind
from tests.boundary.agent.support import by_template, impression_of, make_job


def about(index: int):
    """A responder answering about the exposure at `index`, noticed or not."""

    def respond(messages, template_id: str) -> str:
        shown = impression_of(messages)["exposures"]
        return json.dumps(
            {"subject_stimulus_id": shown[index]["stimulus_id"], "action": "comment", "verbatim": "this is what I think"}
        )

    return respond


def test_a_response_about_something_unnoticed_is_not_reattributed():
    """The first exposure passed unnoticed; the model answers about it anyway."""
    job = make_job(0, tick=3, shown=[(1, "interest", 0.0), (2, "random", 0.6)])
    unnoticed = job.presentation.impression.exposures[0].stimulus_id
    noticed = job.presentation.impression.exposures[1].stimulus_id
    chat = FakeChat(about(0))
    (outcome,) = turns([job], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, TurnFailure), "words about an unnoticed stimulus were kept under another subject"
    assert outcome.kind is TurnFailureKind.GUARDRAIL_VIOLATION
    assert outcome.rule is GuardrailRule.REFERENCES_UNSHOWN_STIMULUS
    assert unnoticed in outcome.detail and noticed not in outcome.detail


def test_the_stricter_retry_names_only_what_was_noticed():
    job = make_job(0, tick=3, shown=[(1, "interest", 0.0), (2, "random", 0.6)])
    noticed = job.presentation.impression.exposures[1].stimulus_id
    chat = FakeChat(by_template({"persona_turn": about(0), "persona_turn_strict": about(1)}))
    (outcome,) = turns([job], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.turn.reaction.subject_stimulus_id == noticed
    assert outcome.rejected_prompt_hashes, "the accepted turn records the prompt it rejected"
    strict = [call for call in chat.calls if "exactly one of these stimulus ids" in call]
    assert strict, "the rejected response was not retried with a stricter instruction"
    offered = strict[0].split("exactly one of these stimulus ids:")[1].split(".")[0]
    assert noticed in offered
    assert job.presentation.impression.exposures[0].stimulus_id not in offered, "the retry still offers what passed unnoticed"


def test_a_persona_that_noticed_nothing_is_asked_nothing():
    job = make_job(0, tick=3, shown=[(1, "interest", 0.0), (2, "random", 0.0)])
    chat = FakeChat(about(0))
    (outcome,) = turns([job], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, TurnFailure)
    assert outcome.kind is TurnFailureKind.NOTHING_NOTICED
    assert len(chat.calls) == 0, "nothing was noticed, so there was nothing to ask a model about"


def test_a_response_about_what_it_noticed_is_kept_as_it_is():
    job = make_job(0, tick=3, shown=[(1, "interest", 0.8), (2, "random", 0.6)])
    chat = FakeChat(about(1))
    (outcome,) = turns([job], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.turn.reaction.subject_stimulus_id == job.presentation.impression.exposures[1].stimulus_id
    assert outcome.turn.reaction.verbatim == "this is what I think"
