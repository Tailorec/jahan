"""Pinned identities of the representative study, keyed by contract version.

Every hashed shape feeds a world id or a replay pin. If a hashed shape changes, these pins break: either the
change was a mistake, or it is a new contract — bump SCHEMA_VERSION and pin the new identities under it.
"""

import json
from pathlib import Path

from simcore.schemas import SCHEMA_VERSION, BriefPack, Population, RunConfig, SweepGrid, canonical_hash, derive_world_id
from tests.study_builders import ANCHOR_SET_HASHES, TEMPLATE_HASHES, load_fixture, pack_payload, population_payload, ulid

PINS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "hash_stability.json"


def representative_identities() -> dict:
    pack = BriefPack.model_validate(pack_payload())
    population = Population.model_validate(population_payload())
    grid = SweepGrid.model_validate(load_fixture("example_sweep_grid.json"))
    config = RunConfig.model_validate(
        {
            "run_id": f"run-{ulid(1)}",
            "pins": grid.pins.model_dump(mode="json"),
            "budget": grid.budget.model_dump(mode="json"),
            "brief_hash": canonical_hash(pack.brief),
            "ontology_hash": canonical_hash(pack.ontology),
            "population_hash": population.population_hash,
            "graph_hash": population.graph.graph_hash,
            "scenarios": [scenario.model_dump(mode="json") for scenario in grid.scenarios],
            "seeds": list(grid.seeds),
            "template_hashes": TEMPLATE_HASHES,
            "anchor_set_hashes": ANCHOR_SET_HASHES,
        }
    )
    return {
        "population_hash": population.population_hash,
        "graph_hash": population.graph.graph_hash,
        "config_hash": canonical_hash(config),
        "world_ids": sorted(derive_world_id(s, seed, population.population_hash) for s in config.scenarios for seed in config.seeds),
    }


def test_identities_are_pinned_for_the_current_contract_version():
    pins = json.loads(PINS_PATH.read_text())["replay_pins"]
    assert SCHEMA_VERSION in pins, f"no identities pinned for contract {SCHEMA_VERSION}: pin them before releasing it"
    assert representative_identities() == pins[SCHEMA_VERSION], (
        "a hashed shape changed under an unchanged contract version: undo the change, or bump SCHEMA_VERSION and pin the new identities"
    )
