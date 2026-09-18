"""A turn's move and its reflection's revision, combined within the range a change may state."""

import pytest

from simcore.agent._beliefs import combine
from simcore.schemas import BeliefChange, BeliefDim


def _change(**kwargs) -> BeliefChange:
    return BeliefChange.model_validate(kwargs)


def test_two_moves_in_one_direction_saturate_rather_than_leave_the_scale():
    """A reaction said a claim's credence moved +1.0 and the reflection said +1.0 again. Summed,
    that is 2.0 — outside what a `BeliefChange` may state — and the contract refused it, killing
    the turn, the batch and the whole run. A move saturates at the end of its scale."""
    first = _change(claim_credence={"C1": 1.0}, dimensions={"value": 0.9})
    second = _change(claim_credence={"C1": 1.0}, dimensions={"value": 0.4})
    combined = combine(first, second)
    assert combined.claim_credence["C1"] == 1.0
    assert combined.dimensions[BeliefDim.VALUE] == 1.0


def test_two_moves_down_saturate_at_the_other_end():
    combined = combine(_change(claim_credence={"C1": -0.8}), _change(claim_credence={"C1": -0.7}))
    assert combined.claim_credence["C1"] == -1.0


def test_moves_that_stay_in_range_are_summed_exactly():
    combined = combine(_change(claim_credence={"C1": 0.25}), _change(claim_credence={"C1": -0.1}))
    assert combined.claim_credence["C1"] == pytest.approx(0.15)


def test_one_persona_whose_turn_cannot_be_finalized_is_an_outcome_not_an_exception(monkeypatch):
    """ADR 0031: one outcome per job, never an exception for one persona. A turn that could not
    be finalized propagated out of the batch and ended the run — 500 personas lost to one."""
    import simcore.agent._turns as turns_module
    from simcore.agent import AgentConfig, turns
    from simcore.ports.fake import FakeChat
    from simcore.schemas import CompletedTurn, TurnFailure
    from tests.boundary.agent.support import answering, make_job

    jobs = [make_job(index, tick=3) for index in range(3)]
    original = turns_module._finalize
    seen = {"n": 0}

    def explode(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] == 2:
            raise ValueError("a contract refused what this persona said")
        return original(*args, **kwargs)

    monkeypatch.setattr(turns_module, "_finalize", explode)
    outcomes = turns(jobs, chat=FakeChat(answering()), config=AgentConfig(run_seed=7))
    assert len(outcomes) == len(jobs)
    failed = [outcome for outcome in outcomes if isinstance(outcome, TurnFailure)]
    assert len(failed) == 1, [type(o).__name__ for o in outcomes]
    assert "contract refused" in failed[0].detail
    assert sum(isinstance(outcome, CompletedTurn) for outcome in outcomes) == 2
