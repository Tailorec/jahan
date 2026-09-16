"""Phase 2: the elicitation record, its failures and its parameters."""

import pytest
from pydantic import ValidationError

from simcore.schemas import (
    ElicitationFailure,
    ElicitationParams,
    RunConfig,
    SsrResult,
    canonical_hash,
)
from tests.study_builders import run_config_payload, ssr_payload


def test_the_record_carries_temperature_epsilon_and_one_similarity_vector_per_set():
    result = SsrResult.model_validate(ssr_payload())
    assert result.temperature == 1.0 and result.epsilon == 0.0
    assert len(result.per_set_similarities) == len(result.per_set_pmfs) == 6
    assert all(len(vector) == 5 for vector in result.per_set_similarities)
    with pytest.raises(ValidationError):
        SsrResult.model_validate(ssr_payload(per_set_similarities=ssr_payload()["per_set_similarities"][:5]))
    payload = ssr_payload()
    first = payload["per_set_similarities"][0]
    payload["per_set_similarities"] = tuple(payload["per_set_similarities"]) + (tuple(first),)
    with pytest.raises(ValidationError, match="similarity"):
        SsrResult.model_validate(payload)


def test_the_headline_is_temperature_applied_to_the_mean_and_contradictions_refused():
    warm = SsrResult.model_validate(ssr_payload(temperature=2.0))
    sets = ssr_payload()["per_set_pmfs"]
    mean = [sum(s[i] for s in sets) / len(sets) for i in range(5)]
    shaped = [v ** (1.0 / 2.0) for v in mean]
    total = sum(shaped)
    assert warm.pmf == pytest.approx(tuple(v / total for v in shaped))
    one_hot = SsrResult.model_validate(ssr_payload(temperature=0.0))
    assert one_hot.pmf == pytest.approx((0.0, 0.0, 0.0, 0.0, 1.0))
    with pytest.raises(ValidationError, match="computed"):
        SsrResult.model_validate({**ssr_payload(), "pmf": (0.05, 0.05, 0.1, 0.3, 0.5)})


def test_at_least_six_anchor_sets_are_still_required():
    assert SsrResult.model_validate(ssr_payload()).per_set_pmfs
    with pytest.raises(ValidationError):
        SsrResult.model_validate(ssr_payload(per_set_pmfs=ssr_payload()["per_set_pmfs"][:5]))


def test_a_failure_names_its_kind_and_carries_no_distribution():
    for kind in ("numeric_answer", "embedding_failure", "empty_response"):
        failure = ElicitationFailure.model_validate(
            {"kind": kind, "detail": f"what went wrong: {kind}", "response_text": "4/5", "construct_id": "purchase_intent"}
        )
        assert failure.kind.value == kind
        assert not hasattr(failure, "pmf") and not hasattr(failure, "per_set_pmfs")
    with pytest.raises(ValidationError):
        ElicitationFailure.model_validate({"kind": "stale_cache", "detail": "no such kind", "construct_id": "purchase_intent"})


def test_temperature_and_epsilon_are_per_construct_run_parameters_in_the_hash():
    assert ElicitationParams().temperature == 1.0 and ElicitationParams().epsilon == 0.0
    base = RunConfig.model_validate(run_config_payload())
    assert dict(base.elicitation_params) == {}
    tuned = RunConfig.model_validate(
        run_config_payload(elicitation_params={"purchase_intent": {"temperature": 2.0, "epsilon": 0.5}})
    )
    assert tuned.elicitation_params["purchase_intent"].temperature == 2.0
    assert tuned.elicitation_params["purchase_intent"].epsilon == 0.5
    assert canonical_hash(tuned) != canonical_hash(base)
