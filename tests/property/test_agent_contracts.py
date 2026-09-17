"""M6 phase 1: the contracts the agent's boundary needs.

A persona's state travels with its job and the agent stores nothing (ADR 0030); a batch answers in
request order with failures as outcomes (ADR 0031). These are the shapes that carry both.
"""

import pytest
from pydantic import ValidationError

from simcore.schemas import (
    BeliefChange,
    CompletedTurn,
    MemoryEvent,
    MemorySource,
    PersonaState,
    ProbeResult,
    TurnFailure,
    TurnFailureKind,
    TurnJob,
    TurnOutcome,
    TurnTask,
)
from tests.study_builders import beliefs_payload, persona_payload, stimulus_id, turn_payload, ulid


def memory(n: int = 1, **overrides) -> dict:
    payload = {
        "memory_id": f"me-{ulid(400 + n)}",
        "tick": 2,
        "description": "saw the protein claim and doubted it",
        "importance": 0.6,
        "source": "turn",
        "embedding": [0.1, 0.2, 0.3],
        "embed_model_id": "amazon.titan-embed-text-v2:0",
    }
    payload.update(overrides)
    return payload


def state(**overrides) -> dict:
    payload = {"persona_id": "p-000001", "beliefs": beliefs_payload(), "memories": [memory()]}
    payload.update(overrides)
    return payload


def presentation(persona: str = "p-000001", tick: int = 3) -> dict:
    whole = turn_payload(persona, tick, [(1, "interest", 0.8)], {})
    return {"impression": whole["impression"], "view": whole["view"]}


def job(**overrides) -> dict:
    payload = {
        "persona": persona_payload(0, persona_id="p-000001"),
        "state": state(),
        "presentation": presentation(),
        "task": "reaction",
    }
    payload.update(overrides)
    return payload


def completed(**overrides) -> dict:
    whole = turn_payload("p-000001", 3, [(1, "interest", 0.8)], {
        "subject_stimulus_id": stimulus_id(1), "action": "comment", "verbatim": "the protein claim would get me"})
    payload = {
        "turn": whole,
        "template_id": "persona_turn",
        "prompt_hash": "12" * 32,
        "persona_block_hash": "34" * 32,
        "memories": [memory(2, tick=3)],
        "belief_change": {"dimensions": {"value": 0.1}},
        "memory_ids": [memory()["memory_id"]],
    }
    payload.update(overrides)
    return payload


# --- a memory -----------------------------------------------------------------------------------


def test_a_memory_carries_what_it_was_and_how_it_is_retrieved():
    remembered = MemoryEvent.model_validate(memory())
    assert remembered.source is MemorySource.TURN
    assert remembered.importance == 0.6
    assert remembered.embedding == (0.1, 0.2, 0.3)
    assert MemoryEvent.model_validate_json(remembered.model_dump_json()) == remembered


def test_a_memory_without_its_embedding_is_one_the_trace_recorded():
    """The trace keeps what was remembered, not the vector it was indexed by; live state carries both."""
    unindexed = MemoryEvent.model_validate(memory(embedding=None, embed_model_id=None))
    assert unindexed.embedding is None


def test_an_embedding_names_the_model_that_produced_it():
    with pytest.raises(ValidationError, match="names the model"):
        MemoryEvent.model_validate(memory(embed_model_id=None))
    with pytest.raises(ValidationError, match="names the model"):
        MemoryEvent.model_validate(memory(embedding=None))


def test_a_memory_source_is_a_closed_set():
    assert {source.value for source in MemorySource} == {"turn", "reflection"}
    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(memory(source="imagined"))


# --- persona state ------------------------------------------------------------------------------


def test_state_carries_beliefs_memories_and_the_reflection_counters():
    carried = PersonaState.model_validate(state())
    assert carried.beliefs.dimensions
    assert carried.last_reflection_tick == 0 and carried.turns_since_reflection == 0
    assert PersonaState.model_validate_json(carried.model_dump_json()) == carried


def test_state_holds_each_memory_once():
    with pytest.raises(ValidationError, match="more than once"):
        PersonaState.model_validate(state(memories=[memory(), memory()]))


def test_a_persona_with_no_memories_yet_is_a_state_like_any_other():
    assert PersonaState.model_validate(state(memories=[])).memories == ()


# --- the job ------------------------------------------------------------------------------------


def test_a_job_is_one_persona_its_state_and_what_it_was_shown():
    asked = TurnJob.model_validate(job())
    assert asked.task is TurnTask.REACTION
    assert asked.persona.persona_id == asked.state.persona_id == asked.presentation.impression.persona_id


def test_a_job_whose_state_belongs_to_another_persona_is_refused():
    with pytest.raises(ValidationError, match="state of p-000002"):
        TurnJob.model_validate(job(state=state(persona_id="p-000002")))


def test_a_job_shown_another_personas_impression_is_refused():
    with pytest.raises(ValidationError, match="shown to p-000002"):
        TurnJob.model_validate(job(presentation=presentation("p-000002")))


def test_the_task_set_covers_the_tier_routing_table():
    assert {task.value for task in TurnTask} >= {"first_seen", "conversation", "reflection", "purchase", "claim_audit"}


# --- outcomes -----------------------------------------------------------------------------------


def test_a_completed_turn_carries_the_turn_and_everything_the_trace_needs():
    outcome = CompletedTurn.model_validate(completed())
    assert outcome.turn.reaction.verbatim
    assert outcome.persona_id == "p-000001"
    assert outcome.belief_change != BeliefChange()
    assert outcome.memories[0].tick == 3


def test_a_completed_turn_recalls_only_memories_its_state_held():
    """The memories a turn recalls are ids; that they exist is the partition's to check, but a turn
    cannot recall a memory it wrote in the same breath."""
    written = completed()
    with pytest.raises(ValidationError, match="recalls a memory it wrote"):
        CompletedTurn.model_validate({**written, "memory_ids": [written["memories"][0]["memory_id"]]})


def test_a_failure_names_what_went_wrong_and_carries_no_turn():
    failed = TurnFailure.model_validate({
        "persona_id": "p-000001", "impression_id": presentation()["impression"]["impression_id"],
        "kind": "call_failed", "detail": "the tier-a call timed out",
    })
    assert failed.kind is TurnFailureKind.CALL_FAILED
    assert not hasattr(failed, "turn")


def test_a_guardrail_failure_names_the_rule_and_two_distinct_attempts():
    base = {"persona_id": "p-000001", "impression_id": presentation()["impression"]["impression_id"],
            "kind": "guardrail_violation", "detail": "referred to a stimulus never shown"}
    failed = TurnFailure.model_validate({**base, "rule": "references_unshown_stimulus", "prompt_hashes": ["9a" * 32, "9b" * 32]})
    assert failed.prompt_hashes[0] != failed.prompt_hashes[1]
    with pytest.raises(ValidationError, match="names the rule"):
        TurnFailure.model_validate(base)
    with pytest.raises(ValidationError, match="two attempts"):
        TurnFailure.model_validate({**base, "rule": "references_unshown_stimulus", "prompt_hashes": ["9a" * 32, "9a" * 32]})


def test_a_failure_that_is_not_a_violation_carries_no_rule():
    with pytest.raises(ValidationError, match="only a guardrail violation"):
        TurnFailure.model_validate({
            "persona_id": "p-000001", "impression_id": presentation()["impression"]["impression_id"],
            "kind": "call_failed", "detail": "timed out", "rule": "references_unshown_stimulus",
            "prompt_hashes": ["9a" * 32, "9b" * 32]})


def test_an_outcome_is_one_or_the_other_and_never_both():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(TurnOutcome)
    assert isinstance(adapter.validate_python(completed()), CompletedTurn)
    assert isinstance(adapter.validate_python({
        "persona_id": "p-000001", "impression_id": presentation()["impression"]["impression_id"],
        "kind": "call_failed", "detail": "timed out"}), TurnFailure)
    with pytest.raises(ValidationError):
        adapter.validate_python({**completed(), "kind": "call_failed"})


# --- the probe ----------------------------------------------------------------------------------


def probe(**overrides) -> dict:
    payload = {
        "persona_id": "p-000001",
        "tick": 10,
        "answers": [
            {"question": "How often do you exercise?", "attribute": "exercise_frequency",
             "expected": "3_plus_weekly", "answer": "three or four times a week", "agreed": True},
            {"question": "How much do you usually spend?", "attribute": "spend_band",
             "expected": "5_10", "answer": "about twenty pounds", "agreed": False},
        ],
    }
    payload.update(overrides)
    return payload


def test_a_probe_records_each_answer_against_the_attribute_it_came_from():
    result = ProbeResult.model_validate(probe())
    assert result.disagreement_rate == 0.5
    assert ProbeResult.model_validate_json(result.model_dump_json()) == result


def test_a_probe_asks_at_least_one_question_and_never_the_same_attribute_twice():
    with pytest.raises(ValidationError):
        ProbeResult.model_validate(probe(answers=[]))
    answers = probe()["answers"]
    with pytest.raises(ValidationError, match="more than once"):
        ProbeResult.model_validate(probe(answers=[answers[0], answers[0]]))
