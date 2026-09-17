"""Phase 5: beliefs and reflection.

Deltas apply across the closed dimension set and per claim; reflection fires on the
jittered cadence or on a sharp move, writes a belief change plus consolidated
memories, and the capped state stays bounded over a long horizon.
"""

from simcore.agent import (
    AgentConfig,
    advance_state,
    apply_change,
    enforce_cap,
    reflection_interval_for,
    turns,
)
from simcore.agent._beliefs import max_abs_change
from simcore.ports.fake import FakeChat, FakeEmbed
from simcore.schemas import BeliefChange, Beliefs, CompletedTurn, MemorySource, PersonaState
from tests.study_builders import beliefs_payload

from .support import answering, by_template, make_job, memory_dict, moving, reflecting


def beliefs(**overrides) -> Beliefs:
    payload = beliefs_payload()
    payload.update(overrides)
    return Beliefs.model_validate(payload)


def test_deltas_apply_across_dimensions_and_per_claim():
    before = beliefs()
    change = BeliefChange.model_validate({"dimensions": {"value": 0.1}, "claim_credence": {"C1": -0.2}})
    after = apply_change(before, change)
    assert after.dimensions["value"] == before.dimensions["value"] + 0.1
    assert after.claim_credence["C1"] == before.claim_credence["C1"] - 0.2
    assert after.dimensions["fit"] == before.dimensions["fit"]


def test_a_single_claim_flip_is_visible_when_aggregate_belief_barely_moves():
    before = beliefs()
    change = BeliefChange.model_validate({"claim_credence": {"C2": 0.5}})
    after = apply_change(before, change)
    assert after.claim_credence["C2"] == before.claim_credence["C2"] + 0.5
    assert max_abs_change(change) == 0.5
    assert all(after.dimensions[dim] == before.dimensions[dim] for dim in after.dimensions)


def test_a_turn_carries_the_belief_move_its_response_proposed():
    job = make_job(0)
    responder = moving(dimensions={"value": 0.2}, claim_credence={"C1": 0.3})
    (outcome,) = turns([job], chat=FakeChat(responder=responder))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.belief_change.dimensions["value"] == 0.2
    assert outcome.belief_change.claim_credence["C1"] == 0.3
    carried = advance_state(job.state, outcome, tick=3, memory_cap=50)
    assert carried.beliefs.dimensions["value"] == job.state.beliefs.dimensions["value"] + 0.2


def test_reflection_fires_at_the_jittered_cadence_and_not_before():
    interval = reflection_interval_for("p-000001", 4021)
    assert 4 <= interval <= 8
    assert reflection_interval_for("p-000001", 4021) == interval
    assert all(4 <= reflection_interval_for(f"p-00000{i}", 4021) <= 8 for i in range(1, 5))

    config = AgentConfig(run_seed=4021)
    chat = FakeChat(responder=by_template({"persona_reflection": reflecting(dimensions={"trust": 0.1})}))
    state = make_job(0).state
    fired_at = None
    for tick in range(1, 30):
        job = make_job(0, tick=tick, n=tick).model_copy(update={"state": state})
        (outcome,) = turns([job], chat=chat, config=config, embed=FakeEmbed(dim=4))
        assert isinstance(outcome, CompletedTurn)
        state = advance_state(state, outcome, tick=tick, memory_cap=50)
        if any(memory.source is MemorySource.REFLECTION for memory in outcome.memories):
            fired_at = tick
            break
    assert fired_at == interval
    assert outcome.belief_change.dimensions["trust"] == 0.1
    consolidated = [memory for memory in outcome.memories if memory.source is MemorySource.REFLECTION]
    assert 1 <= len(consolidated) <= 3
    assert all(memory.importance >= 0.8 for memory in consolidated)


def test_reflection_fires_on_a_sharp_single_claim_move():
    config = AgentConfig(run_seed=4021)
    chat = FakeChat(
        responder=by_template(
            {
                "persona_turn": moving(claim_credence={"C2": 0.5}),
                "persona_reflection": reflecting(claim_credence={"C2": 0.1}),
            }
        )
    )
    (outcome,) = turns([make_job(0)], chat=chat, config=config, embed=FakeEmbed(dim=4))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.belief_change.claim_credence["C2"] == 0.6
    assert any(memory.source is MemorySource.REFLECTION for memory in outcome.memories)


def test_no_reflection_on_a_quiet_turn_before_the_cadence():
    config = AgentConfig(run_seed=4021)
    chat = FakeChat(responder=answering())
    (outcome,) = turns([make_job(0)], chat=chat, config=config, embed=FakeEmbed(dim=4))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.belief_change == BeliefChange()
    assert not any(memory.source is MemorySource.REFLECTION for memory in outcome.memories)


def test_a_rerun_reflects_on_the_same_ticks():
    def run_once() -> list[int]:
        config = AgentConfig(run_seed=917731)
        chat = FakeChat(responder=by_template({"persona_reflection": reflecting()}))
        state = make_job(1).state
        fired = []
        for tick in range(1, 25):
            job = make_job(1, tick=tick, n=tick).model_copy(update={"state": state})
            (outcome,) = turns([job], chat=chat, config=config)
            state = advance_state(state, outcome, tick=tick, memory_cap=50)
            if any(memory.source is MemorySource.REFLECTION for memory in outcome.memories):
                fired.append(tick)
        return fired

    assert run_once() == run_once()
    assert len(run_once()) >= 2


def test_memories_are_capped_without_discarding_the_highest_importance_items():
    state = PersonaState.model_validate(
        {"persona_id": "p-000001", "beliefs": beliefs_payload(), "memories": [memory_dict(n, 1, f"old {n}", 0.1 + 0.01 * n) for n in range(60)]}
    )
    kept = enforce_cap(state.memories, 50)
    assert len(kept) == 50
    assert max(memory.importance for memory in kept) == max(memory.importance for memory in state.memories)


def test_state_after_many_ticks_is_bounded_in_size():
    config = AgentConfig(run_seed=4021, memory_cap=20)
    chat = FakeChat(responder=by_template({"persona_reflection": reflecting(dimensions={"value": 0.05})}))
    embed = FakeEmbed(dim=4)
    state = make_job(0).state
    for tick in range(1, 41):
        job = make_job(0, tick=tick, n=tick).model_copy(update={"state": state})
        (outcome,) = turns([job], chat=chat, config=config, embed=embed)
        state = advance_state(state, outcome, tick=tick, memory_cap=config.memory_cap)
    assert len(state.memories) <= 20
    assert len(state.model_dump_json()) < 20000


def test_a_failed_reflection_still_consolidates_by_rule():
    config = AgentConfig(run_seed=4021)
    chat = FakeChat(responder=by_template({"persona_turn": moving(claim_credence={"C2": 0.5}), "persona_reflection": "not json"}))
    (outcome,) = turns([make_job(0)], chat=chat, config=config, embed=FakeEmbed(dim=4))
    assert isinstance(outcome, CompletedTurn)
    consolidated = [memory for memory in outcome.memories if memory.source is MemorySource.REFLECTION]
    assert len(consolidated) == 1
    assert outcome.belief_change.claim_credence["C2"] == 0.5
