"""Builders for valid study payloads, grounded in the representative brief and ontology fixtures.

Each returns plain JSON-shaped data so a test can break exactly one thing and assert the refusal.
"""

import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PERSONA_IDS = ["p-000001", "p-000002", "p-000003", "p-000004"]


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def ontology_payload() -> dict:
    """The example ontology, extended with an economic attribute that completion may synthesize."""
    ontology = load_fixture("example_ontology.json")
    ontology["attribute_domains"]["spend_band"] = "economic"
    return ontology


def pack_payload(**brief_overrides) -> dict:
    brief = load_fixture("example_brief.json")
    brief.update(brief_overrides)
    return {"brief": brief, "ontology": ontology_payload()}


def persona_payload(index: int = 0, **overrides) -> dict:
    payload = {
        "persona_id": PERSONA_IDS[index],
        "source": ["gss", "gss", "amazon", "synthetic"][index],
        "conditioning": {"age": "25_34", "sex": "female", "exercise_frequency": "3_plus_weekly"},
        "attributes": {"diet_protein_focus": "high", "spend_band": "5_10"},
        "origins": {
            "age": "grounded",
            "sex": "grounded",
            "exercise_frequency": "grounded",
            "diet_protein_focus": "grounded",
            "spend_band": "synthesized",
        },
        "embedding": {"model_id": "text-embedding-3-small", "dim": 1536, "index": index},
    }
    payload.update(overrides)
    return payload


def gate_report_payload(**overrides) -> dict:
    payload = {
        "results": [
            {"kind": "ordinal", "attribute": "exercise_frequency", "ks_statistic": 0.1, "ks_similarity": 0.9},
            {"kind": "categorical", "attribute": "age", "chi_square": 3.2, "degrees_of_freedom": 4, "p_value": 0.52},
        ],
        "source_mix": {"gss": 0.5, "amazon": 0.25, "synthetic": 0.25},
    }
    payload.update(overrides)
    return payload


def population_payload(**overrides) -> dict:
    payload = {
        "pack": pack_payload(),
        "manifest": {
            "population_hash": "ab12" * 16,
            "population_seed": 4021,
            "persona_ids": list(PERSONA_IDS),
            "achieved_mix": {"gym_regulars": 0.5, "protein_dieters": 0.5},
        },
        "personas": [persona_payload(index) for index in range(len(PERSONA_IDS))],
        "gate_report": gate_report_payload(),
        "graph": {
            "graph_hash": "cd34" * 16,
            "edges": [
                {"u": "p-000001", "v": "p-000002", "weight": 0.8},
                {"u": "p-000003", "v": "p-000004", "weight": 0.6},
                {"u": "p-000002", "v": "p-000003", "weight": 0.2},
            ],
        },
        "communities": [
            {"community_id": "community-1", "member_ids": ["p-000001", "p-000002"]},
            {"community_id": "community-2", "member_ids": ["p-000003", "p-000004"]},
        ],
    }
    payload.update(copy.deepcopy(overrides))
    return payload
