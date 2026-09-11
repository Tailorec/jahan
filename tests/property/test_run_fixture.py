import json
from pathlib import Path

from simcore.schemas import SweepGrid, derive_world_id

REPO_ROOT = Path(__file__).resolve().parents[2]

POPULATION_HASH = "cc33" * 16


def test_representative_sweep_grid_file_validates():
    fixture = json.loads((REPO_ROOT / "tests" / "fixtures" / "example_sweep_grid.json").read_text())
    grid = SweepGrid.model_validate(fixture)
    assert [scenario.variant.variant_id for scenario in grid.scenarios] == [
        "v1baseline",
        "v2premium",
        "v3fitnessemphasis",
    ]
    assert grid.budget.max_cost == 42.0


def test_representative_sweep_grid_expands_to_distinct_world_identities():
    fixture = json.loads((REPO_ROOT / "tests" / "fixtures" / "example_sweep_grid.json").read_text())
    grid = SweepGrid.model_validate(fixture)
    world_ids = {
        derive_world_id(scenario.variant.variant_id, seed, POPULATION_HASH)
        for scenario in grid.scenarios
        for seed in grid.seeds
    }
    assert len(world_ids) == len(grid.scenarios) * len(grid.seeds) == 6
    assert all(len(world_id) == 12 for world_id in world_ids)
