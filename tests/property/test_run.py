import os
import subprocess
import sys
from pathlib import Path

import pytest
import simcore.schemas.base as base_module
from pydantic import ValidationError

from simcore.schemas import (
    Budget,
    ConceptCard,
    Intervention,
    ModelPins,
    RunConfig,
    Scenario,
    SweepGrid,
    TickUnit,
    canonical_hash,
    derive_world_id,
    derive_world_seed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

PINS = {
    "tier_a": "openrouter/camel-ai/persona-8b",
    "tier_b": "anthropic/claude-sonnet-4.5",
    "embed": "openai/text-embedding-3-small",
}


def scenario_payload(**overrides):
    payload = {
        "variant": {
            "variant_id": "v1baseline",
            "name": "Baseline",
            "description": "Baseline concept at the brief price",
            "emphasized_claims": ["C1"],
        },
        "price": {"amount": 2.49, "currency": "USD"},
        "audience_weights": {"gym_regulars": 0.6, "protein_dieters": 0.4},
        "tick_unit": "day",
        "horizon_ticks": 30,
        "interventions": [{"tick": 3, "kind": "launch"}],
    }
    payload.update(overrides)
    return payload


def run_config_payload(**overrides):
    payload = {
        "run_id": "run-01j7x9k2m3n4p5q6r7s8t9v0wx",
        "pins": PINS,
        "budget": {"max_cost": 20.0, "currency": "USD"},
        "brief_hash": "aa11" * 16,
        "ontology_hash": "bb22" * 16,
        "population_hash": "cc33" * 16,
        "scenarios": [scenario_payload()],
        "seeds": [4021, 917731],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("bad", ["", "latest", "*"])
def test_model_pins_refuse_empty_wildcarded_and_version_floating_ids(bad):
    with pytest.raises(ValidationError):
        ModelPins(tier_a=bad, tier_b="anthropic/claude-sonnet-4.5", embed="openai/text-embedding-3-small")


def test_model_pins_accept_provider_prefixed_ids():
    pins = ModelPins.model_validate(PINS)
    assert pins.embed == "openai/text-embedding-3-small"
    assert pins.safety is None


def test_budget_refuses_non_positive_cost():
    with pytest.raises(ValidationError):
        Budget(max_cost=0.0, currency="USD")


def test_run_config_pins_the_ontology_hash_alongside_the_brief_hash():
    config = RunConfig.model_validate(run_config_payload())
    edited = RunConfig.model_validate(run_config_payload(ontology_hash="dd44" * 16))
    assert config.ontology_hash != edited.ontology_hash
    assert canonical_hash(config) != canonical_hash(edited)


def test_config_hash_folds_the_contract_version(monkeypatch):
    config = RunConfig.model_validate(run_config_payload())
    before = canonical_hash(config)
    monkeypatch.setattr(base_module, "SCHEMA_VERSION", "9.9.9")
    assert canonical_hash(config) != before


def test_scenario_has_no_seed_field():
    assert "seed" not in Scenario.model_fields
    assert "world_seed" not in Scenario.model_fields


def test_one_scenario_pairs_with_different_replicate_seeds():
    scenario = scenario_payload()
    first = RunConfig.model_validate(run_config_payload(scenarios=[scenario], seeds=[4021]))
    second = RunConfig.model_validate(run_config_payload(scenarios=[scenario], seeds=[917731]))
    assert first.seeds != second.seeds


def test_world_id_is_stable_across_processes():
    own = derive_world_id("v1baseline", 4021, "cc33" * 16)
    code = (
        "from simcore.schemas import derive_world_id;"
        "print(derive_world_id('v1baseline', 4021, '{}'))"
    ).format("cc33" * 16)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == own


def test_world_identity_varies_by_replicate_and_variant():
    baseline = derive_world_id("v1baseline", 4021, "cc33" * 16)
    assert derive_world_id("v1baseline", 4021, "cc33" * 16) == baseline
    assert derive_world_id("v1baseline", 917731, "cc33" * 16) != baseline
    assert derive_world_id("v2premium", 4021, "cc33" * 16) != baseline
    assert derive_world_seed(4021, "v1baseline") != derive_world_seed(917731, "v1baseline")


def test_world_id_is_twelve_hex_characters():
    world_id = derive_world_id("v1baseline", 4021, "cc33" * 16)
    assert len(world_id) == 12
    int(world_id, 16)


def test_price_appears_on_the_scenario_only():
    for model in (ConceptCard, Intervention, ModelPins, Budget, RunConfig, SweepGrid):
        assert "Price" not in repr(model.model_fields), f"{model.__name__} carries a price"


def test_audience_weights_must_sum_to_one():
    with pytest.raises(ValidationError, match="sum to one"):
        Scenario.model_validate(scenario_payload(audience_weights={"gym_regulars": 0.5, "protein_dieters": 0.4}))
    with pytest.raises(ValidationError, match="sum to one"):
        Scenario.model_validate(scenario_payload(audience_weights={}))


def test_scenario_declares_tick_unit_and_horizon():
    scenario = Scenario.model_validate(scenario_payload())
    assert scenario.tick_unit is TickUnit.DAY
    assert scenario.horizon_ticks == 30
    with pytest.raises(ValidationError, match="horizon"):
        Scenario.model_validate(scenario_payload(interventions=[{"tick": 30, "kind": "promotion"}]))
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario_payload(interventions=[{"tick": 7, "kind": "webinar"}]))


def test_interventions_at_the_same_tick_compose():
    scenario = Scenario.model_validate(
        scenario_payload(interventions=[{"tick": 3, "kind": "launch"}, {"tick": 3, "kind": "promotion"}])
    )
    assert len(scenario.interventions) == 2
    assert {intervention.kind for intervention in scenario.interventions} == {"launch", "promotion"}


def test_run_config_round_trips_through_json():
    config = RunConfig.model_validate(run_config_payload())
    assert RunConfig.model_validate(config.model_dump(mode="json")) == config
    assert RunConfig.model_validate_json(config.model_dump_json()) == config


def grid_payload(**overrides):
    payload = {
        "scenarios": [
            scenario_payload(),
            scenario_payload(
                variant={
                    "variant_id": "v2premium",
                    "name": "Premium",
                    "description": "Same concept at a higher price",
                },
                price={"amount": 2.99, "currency": "USD"},
            ),
        ],
        "seeds": [4021, 917731],
        "budget": {"max_cost": 42.0, "currency": "USD"},
        "pins": PINS,
    }
    payload.update(overrides)
    return payload


def test_sweep_grid_validates_and_expands_to_distinct_world_identities():
    grid = SweepGrid.model_validate(grid_payload())
    world_ids = {
        derive_world_id(scenario.variant.variant_id, seed, "cc33" * 16)
        for scenario in grid.scenarios
        for seed in grid.seeds
    }
    assert len(world_ids) == len(grid.scenarios) * len(grid.seeds)
