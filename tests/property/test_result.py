import copy

import pytest
from pydantic import ValidationError

import simcore.schemas as schemas
from simcore.schemas import RunRegistryEntry, RunResult, WorldStatus
from tests.study_builders import registry_payload, run_result_payload

def outcomes_of(data: dict) -> list[dict]:
    return data["outcomes"]


def test_a_run_result_carries_the_registry_and_one_outcome_per_world():
    result = RunResult.model_validate(run_result_payload())
    assert [outcome.world_id for outcome in result.outcomes] == list(result.registry.world_ids)
    assert result.outcomes[1].rungs == (schemas.DegradationRung.WARN, schemas.DegradationRung.FREEZE_OPTIONAL_TIER_B)
    assert result.registry.config_hash == RunRegistryEntry.model_validate(registry_payload(status="completed")).config_hash
    assert RunResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda o: o.pop(), "missing"),
        (lambda o: o.append({**o[0], "world_id": "ffffffffffff"}), "unknown"),
        (lambda o: o.append(copy.deepcopy(o[0])), "reported more than once"),
    ],
    ids=["world-missing", "world-not-configured", "world-reported-twice"],
)
def test_a_result_reports_exactly_the_registrys_worlds(change, match):
    data = run_result_payload()
    change(outcomes_of(data))
    with pytest.raises(ValidationError, match=match):
        RunResult.model_validate(data)


def test_a_result_reports_at_least_one_world():
    with pytest.raises(ValidationError, match="outcomes"):
        RunResult.model_validate(run_result_payload(outcomes=[]))


# --- what a world did -------------------------------------------------------------------------


def test_a_world_that_never_started_closed_no_tick_and_degraded_not_at_all():
    data = run_result_payload(registry=registry_payload(status="partial"))
    outcomes_of(data)[1] = {"world_id": outcomes_of(data)[1]["world_id"], "status": "not_started"}
    outcome = RunResult.model_validate(data).outcomes[1]
    assert outcome.status is WorldStatus.NOT_STARTED and outcome.last_closed_tick is None and outcome.rungs == ()


@pytest.mark.parametrize(
    "change",
    [{"last_closed_tick": 0}, {"rungs": ["warn"]}],
    ids=["closed-a-tick", "applied-a-rung"],
)
def test_a_not_started_world_that_claims_it_did_something_is_refused(change):
    data = run_result_payload(registry=registry_payload(status="partial"))
    outcomes_of(data)[1] = {"world_id": outcomes_of(data)[1]["world_id"], "status": "not_started", **change}
    with pytest.raises(ValidationError, match="never started"):
        RunResult.model_validate(data)


def test_a_partial_world_may_stop_anywhere_short_of_the_horizon():
    data = run_result_payload(registry=registry_payload(status="paused"))
    outcomes_of(data)[1].update(status="partial", last_closed_tick=4, rungs=["warn", "pause"])
    result = RunResult.model_validate(data)
    assert result.outcomes[1].status is WorldStatus.PARTIAL and result.outcomes[1].last_closed_tick == 4


@pytest.mark.parametrize(
    "rungs",
    [["freeze_optional_tier_b", "warn"], ["warn", "warn"], ["pause", "subsample_activation"]],
    ids=["de-escalates", "repeats", "steps-back-down"],
)
def test_a_worlds_rungs_only_escalate(rungs):
    data = run_result_payload()
    outcomes_of(data)[1]["rungs"] = rungs
    with pytest.raises(ValidationError, match="degradation only escalates"):
        RunResult.model_validate(data)


# --- one result type for runs and sweeps ------------------------------------------------------


def test_a_sweep_returns_an_ordinary_run_result():
    assert not [name for name in schemas.__all__ if "Sweep" in name and "Result" in name]
    assert {"SweepPlan", "SweepGrid", "RunResult"} <= set(schemas.__all__)
