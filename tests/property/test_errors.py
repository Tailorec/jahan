import pytest

from simcore.schemas import BudgetExhausted, GateFailure, SchemaVersionError, SimError


def test_exit_codes_are_distinct_and_match_the_ladder():
    codes = [
        SimError.exit_code,
        GateFailure.exit_code,
        BudgetExhausted.exit_code,
        SchemaVersionError.exit_code,
    ]
    assert codes == [1, 2, 3, 5]
    assert len(set(codes)) == len(codes)


def test_every_error_is_a_sim_error():
    assert issubclass(GateFailure, SimError)
    assert issubclass(BudgetExhausted, SimError)
    assert issubclass(SchemaVersionError, SimError)


def test_failed_gate_is_distinguishable_from_a_crash():
    with pytest.raises(SimError) as crash:
        raise SimError("unexpected")
    with pytest.raises(SimError) as gate:
        raise GateFailure("conditioning set too strict")
    assert gate.type.exit_code != crash.type.exit_code
