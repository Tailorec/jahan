import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

import simcore.schemas.base as base_module
from simcore.schemas import (
    Budget,
    ConceptCard,
    Intervention,
    ModelPins,
    RunConfig,
    Scenario,
    SweepGrid,
    SweepPlan,
    TickUnit,
    canonical_hash,
    derive_world_id,
    derive_world_seed,
)
from tests.study_builders import ANCHOR_SET_HASHES, TEMPLATE_HASHES, pack_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
POPULATION_HASH = "cc33" * 16

PINS = {
    "tier_a": "openrouter/camel-ai/persona-8b",
    "tier_b": "anthropic/claude-sonnet-4-5-20250929",
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


def priced(amount: float) -> dict:
    return scenario_payload(price={"amount": amount, "currency": "USD"})


def run_config_payload(**overrides):
    payload = {
        "run_id": "run-01j7x9k2m3n4p5q6r7s8t9v0wx",
        "pins": PINS,
        "budget": {"max_cost": 20.0, "currency": "USD"},
        "brief_hash": "aa11" * 16,
        "ontology_hash": "bb22" * 16,
        "population_hash": POPULATION_HASH,
        "scenarios": [scenario_payload()],
        "seeds": [4021, 917731],
        "template_hashes": TEMPLATE_HASHES,
        "anchor_set_hashes": ANCHOR_SET_HASHES,
    }
    payload.update(overrides)
    return payload


def grid_payload(**overrides):
    payload = {"scenarios": [priced(2.49), priced(2.99)], "seeds": [4021, 917731], "budget": {"max_cost": 42.0, "currency": "USD"}, "pins": PINS}
    payload.update(overrides)
    return payload


# --- pins and budget -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "*", "latest", "gpt-4o-latest", "openai/gpt-4o:latest", "anthropic/claude-3-5-sonnet-LATEST", "model@latest", "embed.latest"]
)
def test_model_pins_refuse_empty_wildcarded_and_version_floating_ids(bad):
    with pytest.raises(ValidationError):
        ModelPins.model_validate({**PINS, "tier_a": bad})


@pytest.mark.parametrize("pin", ["openai/text-embedding-3-small", "anthropic/claude-sonnet-4-5-20250929", "vllm/latestmodel-1.2"])
def test_model_pins_accept_fixed_versions(pin):
    assert ModelPins.model_validate({**PINS, "tier_a": pin}).tier_a == pin


def test_budget_refuses_non_positive_cost():
    with pytest.raises(ValidationError):
        Budget(max_cost=0.0, currency="USD")


# --- run configuration -----------------------------------------------------------------------


def test_run_config_pins_the_ontology_hash_alongside_the_brief_hash():
    config = RunConfig.model_validate(run_config_payload())
    edited = RunConfig.model_validate(run_config_payload(ontology_hash="dd44" * 16))
    assert canonical_hash(config) != canonical_hash(edited)


def test_config_hash_folds_the_contract_version(monkeypatch):
    config = RunConfig.model_validate(run_config_payload())
    before = canonical_hash(config)
    monkeypatch.setattr(base_module, "SCHEMA_VERSION", "9.9.9")
    assert canonical_hash(config) != before


def test_identical_configurations_hash_identically_whatever_their_run_id():
    first = RunConfig.model_validate(run_config_payload())
    second = RunConfig.model_validate(run_config_payload(run_id="run-01j7x9k2m3n4p5q6r7s8t9v0wy"))
    assert first.run_id != second.run_id
    assert canonical_hash(first) == canonical_hash(second)


def test_scenario_has_no_seed_and_pairs_with_different_replicate_seeds():
    assert not {"seed", "world_seed"} & set(Scenario.model_fields)
    first = RunConfig.model_validate(run_config_payload(seeds=[4021]))
    second = RunConfig.model_validate(run_config_payload(seeds=[917731]))
    assert first.scenarios == second.scenarios and first.seeds != second.seeds


@pytest.mark.parametrize("model", [RunConfig, SweepGrid], ids=["run", "grid"])
def test_repeated_replicate_seeds_refused(model):
    payload = run_config_payload(seeds=[4021, 4021]) if model is RunConfig else grid_payload(seeds=[4021, 4021])
    with pytest.raises(ValidationError, match="seeds repeated"):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [RunConfig, SweepGrid], ids=["run", "grid"])
def test_repeated_scenarios_refused(model):
    scenarios = [scenario_payload(), scenario_payload()]
    payload = run_config_payload(scenarios=scenarios) if model is RunConfig else grid_payload(scenarios=scenarios)
    with pytest.raises(ValidationError, match="scenarios repeated"):
        model.model_validate(payload)


def test_one_variant_id_naming_two_concept_cards_refused():
    other = scenario_payload(variant={"variant_id": "v1baseline", "name": "Something else", "description": "d"}, price={"amount": 2.99, "currency": "USD"})
    with pytest.raises(ValidationError, match="two different concept cards"):
        SweepGrid.model_validate(grid_payload(scenarios=[scenario_payload(), other]))


def test_scenarios_mixing_tick_units_refused():
    hourly = scenario_payload(variant={"variant_id": "v2hourly", "name": "Hourly", "description": "d"}, tick_unit="hour", horizon_ticks=720)
    with pytest.raises(ValidationError, match="share a tick unit"):
        SweepGrid.model_validate(grid_payload(scenarios=[scenario_payload(), hourly]))


def test_run_config_round_trips_through_json():
    config = RunConfig.model_validate(run_config_payload())
    assert RunConfig.model_validate(config.model_dump(mode="json")) == config
    assert RunConfig.model_validate_json(config.model_dump_json()) == config


# --- world identity --------------------------------------------------------------------------


def test_world_id_is_stable_across_processes():
    scenario = Scenario.model_validate(scenario_payload())
    code = (
        "import json, sys;"
        "from simcore.schemas import Scenario, derive_world_id;"
        "print(derive_world_id(Scenario.model_validate(json.loads(sys.argv[1])), 4021, sys.argv[2]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(scenario_payload()), POPULATION_HASH],
        capture_output=True, text=True, cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == derive_world_id(scenario, 4021, POPULATION_HASH)


def test_world_id_varies_by_replicate_scenario_and_population_and_nothing_else():
    baseline = Scenario.model_validate(scenario_payload())
    world = derive_world_id(baseline, 4021, POPULATION_HASH)
    assert derive_world_id(Scenario.model_validate(scenario_payload()), 4021, POPULATION_HASH) == world
    assert derive_world_id(baseline, 917731, POPULATION_HASH) != world
    assert derive_world_id(baseline, 4021, "dd44" * 16) != world
    assert len(world) == 12 and int(world, 16) >= 0


@pytest.mark.parametrize(
    "change",
    [{"price": {"amount": 2.99, "currency": "USD"}}, {"audience_weights": {"gym_regulars": 1.0}}, {"interventions": []}],
    ids=["price", "audience-weights", "interventions"],
)
def test_changing_any_scenario_condition_changes_the_world_id(change):
    baseline = Scenario.model_validate(scenario_payload())
    changed = Scenario.model_validate(scenario_payload(**change))
    assert derive_world_id(baseline, 4021, POPULATION_HASH) != derive_world_id(changed, 4021, POPULATION_HASH)


def test_price_points_of_one_variant_share_their_random_draws():
    assert derive_world_seed(4021, "v1baseline") == derive_world_seed(4021, "v1baseline")
    assert derive_world_seed(4021, "v1baseline") != derive_world_seed(917731, "v1baseline")
    assert derive_world_seed(4021, "v1baseline") != derive_world_seed(4021, "v2premium")


def test_price_sweep_over_one_concept_expands_to_distinct_world_identities():
    grid = SweepGrid.model_validate(grid_payload())
    world_ids = {derive_world_id(scenario, seed, POPULATION_HASH) for scenario in grid.scenarios for seed in grid.seeds}
    assert len(world_ids) == len(grid.scenarios) * len(grid.seeds) == 4


# --- scenarios -------------------------------------------------------------------------------


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
    assert (scenario.tick_unit, scenario.horizon_ticks) == (TickUnit.DAY, 30)
    with pytest.raises(ValidationError, match="horizon"):
        Scenario.model_validate(scenario_payload(interventions=[{"tick": 30, "kind": "promotion"}]))
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario_payload(interventions=[{"tick": 7, "kind": "webinar"}]))


def test_interventions_at_the_same_tick_compose():
    scenario = Scenario.model_validate(scenario_payload(interventions=[{"tick": 3, "kind": "launch"}, {"tick": 3, "kind": "promotion"}]))
    assert {intervention.kind for intervention in scenario.interventions} == {"launch", "promotion"}


# --- sweep plan ------------------------------------------------------------------------------


def plan(**grid_overrides) -> SweepPlan:
    return SweepPlan.model_validate({"pack": pack_payload(), "grid": grid_payload(**grid_overrides)})


def test_sweep_plan_validates_a_grid_against_its_brief():
    assert len(plan().grid.scenarios) == 2


@pytest.mark.parametrize(
    ("scenario", "match"),
    [
        (scenario_payload(audience_weights={"gym_regular": 1.0}), "does not declare"),
        (scenario_payload(variant={"variant_id": "v1baseline", "name": "Baseline", "description": "d", "emphasized_claims": ["C9"]}), "does not make"),
        (scenario_payload(price={"amount": 2.49, "currency": "EUR"}), "priced in EUR"),
    ],
    ids=["unknown-audience", "unknown-claim", "other-currency"],
)
def test_sweep_plan_refuses_names_the_brief_does_not_contain(scenario, match):
    with pytest.raises(ValidationError, match=match):
        plan(scenarios=[scenario])


def test_sweep_plan_leaves_audience_names_open_when_the_brief_declares_none():
    pack = pack_payload(audiences=[])
    parsed = SweepPlan.model_validate({"pack": pack, "grid": grid_payload(scenarios=[scenario_payload(audience_weights={"women_25_34": 1.0})])})
    assert set(parsed.grid.scenarios[0].audience_weights) == {"women_25_34"}


# --- replay pins ------------------------------------------------------------------------------


def test_run_config_pins_templates_anchor_sets_and_graph():
    config = RunConfig.model_validate(run_config_payload(graph_hash="ee55" * 16))
    assert dict(config.template_hashes) == TEMPLATE_HASHES
    assert dict(config.anchor_set_hashes) == ANCHOR_SET_HASHES
    assert config.graph_hash == "ee55" * 16


def test_run_config_without_template_hashes_refused():
    with pytest.raises(ValidationError, match="template"):
        RunConfig.model_validate(run_config_payload(template_hashes={}))
    payload = run_config_payload()
    del payload["template_hashes"]
    with pytest.raises(ValidationError, match="template_hashes"):
        RunConfig.model_validate(payload)


@pytest.mark.parametrize("field", ["template_hashes", "anchor_set_hashes", "graph_hash"])
def test_every_replay_pin_moves_the_config_hash(field):
    base_config = RunConfig.model_validate(run_config_payload())
    changed = {"template_hashes": {**TEMPLATE_HASHES, "persona_turn": "00" * 32},
               "anchor_set_hashes": {**ANCHOR_SET_HASHES, "pi-beverage-v1": "11" * 32},
               "graph_hash": "22" * 32}[field]
    assert canonical_hash(base_config) != canonical_hash(RunConfig.model_validate(run_config_payload(**{field: changed})))


def test_scenario_exposure_budget_defaults_to_three_and_is_a_condition():
    assert Scenario.model_validate(scenario_payload()).exposure_budget == 3
    wider = Scenario.model_validate(scenario_payload(exposure_budget=5))
    assert derive_world_id(wider, 4021, POPULATION_HASH) != derive_world_id(Scenario.model_validate(scenario_payload()), 4021, POPULATION_HASH)
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario_payload(exposure_budget=0))
