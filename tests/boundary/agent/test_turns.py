"""Phase 2: a conditioned turn, end to end.

A batch of jobs in, a batch of outcomes out, through a fake model. Nothing is retrieved,
nothing reflects, no guardrail runs yet — but the order, the failure contract and the
one-persona-per-prompt rule are settled here and never revisited.
"""

from simcore.agent import turns
from simcore.ports.fake import FakeChat
from simcore.schemas import CompletedTurn, TurnFailure, TurnFailureKind
from tests.study_builders import stimulus_id

from .support import FailIndexChat, answering, impression_of, make_job


def test_a_batch_returns_one_outcome_per_job_in_request_order():
    jobs = [make_job(index, n=index) for index in range(3)]
    outcomes = turns(jobs, chat=FakeChat(responder=answering()))
    assert len(outcomes) == 3
    assert [outcome.persona_id for outcome in outcomes] == ["p-000001", "p-000002", "p-000003"]
    assert all(isinstance(outcome, CompletedTurn) for outcome in outcomes)


def test_one_failed_call_is_its_own_outcome_and_the_rest_still_produce():
    jobs = [make_job(index, n=index) for index in range(3)]
    outcomes = turns(jobs, chat=FailIndexChat({1}, responder=answering()))
    assert isinstance(outcomes[1], TurnFailure)
    assert outcomes[1].kind is TurnFailureKind.CALL_FAILED
    assert outcomes[1].persona_id == "p-000002"
    assert isinstance(outcomes[0], CompletedTurn) and isinstance(outcomes[2], CompletedTurn)
    assert outcomes[0].persona_id == "p-000001" and outcomes[2].persona_id == "p-000003"


def test_a_single_turn_is_a_batch_of_one_with_no_separate_code_path():
    job = make_job(0)
    (single,) = turns([job], chat=FakeChat(responder=answering()))
    batch = turns([job, make_job(1, n=1)], chat=FakeChat(responder=answering()))
    assert single == batch[0]


def test_each_prompt_carries_its_persona_alone():
    jobs = [make_job(index, n=index) for index in range(3)]
    chat = FakeChat(responder=answering())
    turns(jobs, chat=chat)
    assert len(chat.calls) == 3
    own_markers = ["25_34", "35_44", "45_54"]
    own_ids = ["p-000001", "p-000002", "p-000003"]
    for position, raw in enumerate(chat.calls):
        assert own_markers[position] in raw
        for other in own_markers[:position] + own_markers[position + 1 :]:
            assert other not in raw
        assert own_ids[position] in raw
        for other in own_ids[:position] + own_ids[position + 1 :]:
            assert other not in raw


def test_a_reaction_names_the_stimulus_it_is_about():
    respond = answering(subject=stimulus_id(2))
    job = make_job(0, shown=[(1, "interest", 0.8), (2, "social_proof", 0.6)])
    (outcome,) = turns([job], chat=FakeChat(responder=respond))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.turn.reaction.subject_stimulus_id == stimulus_id(2)
    assert outcome.turn.impression.stimulus_ids == {stimulus_id(1), stimulus_id(2)}


def test_a_reaction_carries_no_aggregate_outcome():
    jobs = [make_job(index, n=index) for index in range(2)]
    chat = FakeChat(responder=answering())
    outcomes = turns(jobs, chat=chat)
    for raw in chat.calls:
        assert "adoption" not in raw and "polarization" not in raw
    for outcome in outcomes:
        assert isinstance(outcome, CompletedTurn)
        assert set(type(outcome.turn.reaction).model_fields) == {
            "reaction_id",
            "subject_stimulus_id",
            "action",
            "verbatim",
            "belief_change",
            "intent",
        }


def test_a_turn_records_the_prompt_and_persona_block_it_used():
    from simcore.agent._prompt import hash_text, render_persona_block

    job = make_job(0)
    (outcome,) = turns([job], chat=FakeChat(responder=answering()))
    assert isinstance(outcome, CompletedTurn)
    expected_block = render_persona_block(job.persona.conditioning, job.persona.attributes)
    assert outcome.persona_block_hash == hash_text(expected_block)
    assert len(outcome.prompt_hash) == 64
