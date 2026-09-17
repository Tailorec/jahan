"""Phase 8: the character probe.

A seeded share of personas on a fixed cadence is asked questions whose answers sit in
their own attributes; the disagreement rate is derivable from the recorded results, and
a probe that disagrees never touches the turn.
"""

import json

from simcore.agent import AgentConfig, disagreement_rate, probe_attributes, sampled_for_probe, turns
from simcore.schemas import CompletedTurn, InferenceRole, ProbeResult
from simcore.ports.fake import FakeChat

from .support import BatchCountingChat, answering, by_template, make_job


def probed_config(**overrides) -> AgentConfig:
    return AgentConfig(probe_share=1.0, probe_every_ticks=10, probe_questions=2, **overrides)


def probed_ontology():
    from .test_conditioning import ontology

    return ontology()


def echoing(messages, template_id: str) -> str:
    """A responder that chooses, from the options offered, the value its own block states."""
    from .support import held_value, impression_of

    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    if "questions" in user:
        return json.dumps({"answers": [held_value(messages, question) for question in user["questions"]]})
    shown = impression_of(messages)["exposures"]
    return json.dumps({"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "noted"})


def drifting(messages, template_id: str) -> str:
    """A responder that chooses an option other than its own value: drift, not silence."""
    from .support import held_value, impression_of

    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    if "questions" in user:
        answers = []
        for question in user["questions"]:
            mine = held_value(messages, question)
            others = [option for option in question["options"] if option != mine]
            answers.append(others[0] if others else mine)
        return json.dumps({"answers": answers})
    shown = impression_of(messages)["exposures"]
    return json.dumps({"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "noted"})


def test_the_probe_samples_the_configured_share_on_the_configured_cadence():
    assert sampled_for_probe("p-000001", 10, 4021, 1.0)
    assert not sampled_for_probe("p-000001", 10, 4021, 0.0)
    assert sampled_for_probe("p-000001", 10, 4021, 1.0) == sampled_for_probe("p-000001", 10, 4021, 1.0)

    config = probed_config()
    chat = BatchCountingChat(responder=answering())
    (off_cadence,) = turns([make_job(0, tick=9)], chat=chat, config=config)
    assert isinstance(off_cadence, CompletedTurn) and off_cadence.probe is None
    (on_cadence,) = turns([make_job(0, tick=10)], chat=chat, config=config)
    assert isinstance(on_cadence, CompletedTurn) and on_cadence.probe is not None

    quiet = AgentConfig(probe_share=0.0)
    (unprobed,) = turns([make_job(0, tick=10)], chat=BatchCountingChat(responder=answering()), config=quiet)
    assert unprobed.probe is None


def test_probe_questions_come_from_the_personas_own_attributes():
    from .test_conditioning import ontology

    asked = probe_attributes(make_job(0).persona, 4021, 10, 2, ontology())
    assert len(asked) == 2
    projected = {**make_job(0).persona.conditioning, **make_job(0).persona.attributes}
    for attribute, expected, options in asked:
        assert projected[attribute] == expected
        assert expected in options and len(options) > 1

    # An attribute the ontology gives no domain for is not asked about: an open answer
    # cannot be judged, and a persona answering in its own words would read as drift.
    assert [attribute for attribute, _, _ in probe_attributes(make_job(0).persona, 4021, 10, 9)] == ["spend_band"]


def test_the_probe_runs_on_tier_a_and_adds_no_tier_b_call():
    config = probed_config()
    chat = BatchCountingChat(responder=echoing)
    (outcome,) = turns([make_job(0, tick=10)], chat=chat, config=config, ontology=probed_ontology())
    assert isinstance(outcome, CompletedTurn)
    probe_batches = [batch for batch in chat.batches if batch == ["persona_probe"]]
    assert len(probe_batches) == 1
    assert InferenceRole.TIER_B.value not in [role for batch in chat.roles for role in batch]


def test_a_probe_result_records_persona_questions_answers_and_agreement():
    config = probed_config()
    (outcome,) = turns([make_job(0, tick=10)], chat=FakeChat(responder=echoing), config=config, ontology=probed_ontology())
    assert isinstance(outcome, CompletedTurn)
    assert isinstance(outcome.probe, ProbeResult)
    assert outcome.probe.persona_id == "p-000001" and outcome.probe.tick == 10
    assert len(outcome.probe.answers) == 2
    assert all(answer.agreed for answer in outcome.probe.answers)
    assert outcome.probe.disagreement_rate == 0.0


def test_the_runs_disagreement_rate_comes_from_the_trace_alone():
    config = probed_config()
    (steady,) = turns([make_job(0, tick=10)], chat=FakeChat(responder=echoing), config=config, ontology=probed_ontology())
    (adrift,) = turns([make_job(1, tick=10, n=1)], chat=FakeChat(responder=drifting), config=config, ontology=probed_ontology())
    assert isinstance(steady, CompletedTurn) and isinstance(adrift, CompletedTurn)
    assert adrift.probe.disagreement_rate == 1.0
    rate = disagreement_rate([steady.probe, adrift.probe])
    assert rate == 0.5


def test_a_disagreeing_probe_neither_fails_the_turn_nor_alters_the_reaction():
    config = probed_config()
    chat = BatchCountingChat(responder=by_template({"persona_turn": answering(), "persona_probe": drifting}))
    (outcome,) = turns([make_job(0, tick=10)], chat=chat, config=config, ontology=probed_ontology())
    assert isinstance(outcome, CompletedTurn)
    assert outcome.probe.disagreement_rate == 1.0
    assert outcome.turn.reaction.action.value == "comment"
    assert outcome.turn.reaction.verbatim == "the protein claim would get me"
