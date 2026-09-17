"""Every call a turn makes is billed on the outcome that turn produced.

Cost has one source: the records the ports return. The runner writes them to the trace
against the persona whose turn spent them, so a turn that drops them makes a study's
spend unrecoverable — the failure mode the M4 review already fixed once, at the
inference boundary.
"""

from __future__ import annotations

import json

from simcore.agent import turns
from simcore.agent._config import AgentConfig
from simcore.ports.fake import FakeChat, FakeEmbed
from simcore.schemas import CompletedTurn, InferenceRole, TurnFailure
from tests.boundary.agent.support import (
    FailIndexChat,
    answering,
    by_template,
    impression_of,
    make_job,
    reflecting,
)


def busy_config(**overrides) -> AgentConfig:
    """A turn that retries, reflects and is probed: four chat calls for one job."""
    return AgentConfig(
        run_seed=7,
        reflection_interval=1,
        reflection_jitter=0,
        probe_share=1.0,
        probe_every_ticks=1,
        probe_questions=1,
        **overrides,
    )


def invents_then_complies(messages, template_id: str) -> str:
    """The first answer names a stimulus never shown; the stricter retry complies."""
    shown = impression_of(messages)["exposures"]
    if template_id == "persona_turn":
        return json.dumps({"subject_stimulus_id": "st-00000000000000000000000099", "action": "comment", "verbatim": "about that other post"})
    return json.dumps({"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "about what I was shown"})


def test_a_completed_turn_carries_the_cost_of_every_call_it_made():
    chat = FakeChat(by_template({"persona_reflection": reflecting(), "persona_turn": invents_then_complies,
                                 "persona_turn_strict": invents_then_complies}))
    (outcome,) = turns([make_job(0, tick=1)], chat=chat, config=busy_config())
    assert isinstance(outcome, CompletedTurn)
    # the reaction, its stricter retry, the reflection and the probe
    assert len(chat.calls) == 4
    templates = sorted(cost.model_id for cost in outcome.costs)
    assert len(outcome.costs) == len(chat.calls), f"{len(chat.calls)} calls billed, {len(outcome.costs)} recorded"
    assert templates and all(cost.input_tokens > 0 for cost in outcome.costs)


def test_a_turn_that_embedded_carries_its_embedding_costs_too():
    embed = FakeEmbed(dim=8, model_id="fake/embed-v1")
    chat = FakeChat(answering())
    (outcome,) = turns([make_job(0, tick=1)], chat=chat, config=AgentConfig(run_seed=7), embed=embed)
    assert isinstance(outcome, CompletedTurn)
    roles = {cost.role for cost in outcome.costs}
    assert InferenceRole.EMBED in roles, "the stimulus and the new memory were embedded, and nothing recorded it"
    assert InferenceRole.TIER_A in roles


def test_a_failed_turn_records_what_the_failed_call_billed():
    chat = FailIndexChat({0}, responder=answering())
    (outcome,) = turns([make_job(0, tick=1)], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, TurnFailure)
    assert hasattr(outcome, "costs")


def test_costs_stay_with_the_persona_that_spent_them():
    chat = FakeChat(answering())
    jobs = [make_job(index, tick=1, n=index) for index in range(3)]
    outcomes = turns(jobs, chat=chat, config=AgentConfig(run_seed=7))
    for job, outcome in zip(jobs, outcomes):
        assert isinstance(outcome, CompletedTurn)
        assert len(outcome.costs) == 1, "one call, one cost record, on that persona's own outcome"
