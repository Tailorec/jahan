from simcore.schemas import SweepGrid, SweepPlan, derive_world_id
from tests.study_builders import load_fixture, pack_payload

POPULATION_HASH = "cc33" * 16


def test_representative_sweep_grid_file_validates():
    grid = SweepGrid.model_validate(load_fixture("example_sweep_grid.json"))
    assert [scenario.variant.variant_id for scenario in grid.scenarios] == ["v1baseline", "v2premium", "v3fitnessemphasis"]
    assert grid.budget.max_cost == 42.0


def test_representative_sweep_grid_expands_to_distinct_world_identities():
    grid = SweepGrid.model_validate(load_fixture("example_sweep_grid.json"))
    world_ids = {derive_world_id(scenario, seed, POPULATION_HASH) for scenario in grid.scenarios for seed in grid.seeds}
    assert len(world_ids) == len(grid.scenarios) * len(grid.seeds) == 6


def test_representative_sweep_grid_is_consistent_with_the_representative_brief():
    plan = SweepPlan.model_validate({"pack": pack_payload(), "grid": load_fixture("example_sweep_grid.json")})
    assert plan.pack.brief.ontology_version == plan.pack.ontology.version
