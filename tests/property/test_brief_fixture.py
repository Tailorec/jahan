import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from simcore.schemas import BriefPack, CategoryOntology, ProductBrief, canonical_hash

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ONTOLOGY = Path(__file__).resolve().parents[2] / "ontologies" / "beverage_protein" / "1.0.0.json"


def load(name: str) -> dict:
    if name == "example_ontology.json":
        return json.loads(ONTOLOGY.read_text())
    return json.loads((FIXTURES / name).read_text())


def pinned(name: str) -> str:
    return load("hash_stability.json")[name]["hash"]


def test_representative_brief_file_validates():
    brief = ProductBrief.model_validate(load("example_brief.json"))
    assert [claim.id for claim in brief.claims] == ["C1", "C2", "C3"]
    assert brief.product.name == "Protein water"
    assert brief.audiences_declared is True


def test_representative_brief_file_with_unknown_key_refused():
    payload = load("example_brief.json")
    payload["unexpected_key"] = True
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(payload)


def test_representative_ontology_file_validates():
    ontology = CategoryOntology.model_validate(load("example_ontology.json"))
    assert ontology.conditioning_set >= {"age", "sex", "exercise_frequency"}


def test_representative_brief_packs_with_its_ontology():
    packed = BriefPack.model_validate({"brief": load("example_brief.json"), "ontology": load("example_ontology.json")})
    assert packed.ontology.version == packed.brief.ontology_version


def test_representative_brief_hash_is_pinned():
    assert canonical_hash(ProductBrief.model_validate(load("example_brief.json"))) == pinned("example_brief")


def test_representative_ontology_ranks_its_attributes_and_names_its_anchor_sets():
    ontology = CategoryOntology.model_validate(load("example_ontology.json"))
    assert ontology.relevance_order[: len(ontology.conditioning_set)] == ("age", "sex", "exercise_frequency")
    assert set(ontology.relevance_order) == set(ontology.attribute_domains)
    assert ontology.anchor_sets == {"purchase_intent": "purchase-intent-v1"}


def test_representative_ontology_hash_is_pinned():
    assert canonical_hash(CategoryOntology.model_validate(load("example_ontology.json"))) == pinned("example_ontology")


def test_an_ontology_records_its_drafting_provenance_without_moving_its_hash():
    payload = load("example_ontology.json")
    payload["drafting"] = {
        "model_id": "claude-sonnet-4-5",
        "codebook": "matraix-codebook-v1",
        "drafted_at": "2026-09-01T00:00:00Z",
    }
    drafted = CategoryOntology.model_validate(payload)
    assert (drafted.drafting.model_id, drafted.drafting.codebook) == ("claude-sonnet-4-5", "matraix-codebook-v1")
    assert canonical_hash(drafted) == pinned("example_ontology")


def test_pinned_brief_hash_survives_whitespace_key_order_and_refetched_evidence():
    payload = load("example_brief.json")
    payload["product"]["name"] = "  Protein water  "
    payload["audiences"][0]["attribute_filters"] = dict(reversed(list(payload["audiences"][0]["attribute_filters"].items())))
    payload["claims"][0]["evidence"]["fetched_at"] = "2026-09-10T08:00:00+05:30"
    assert canonical_hash(ProductBrief.model_validate(payload)) == pinned("example_brief")


def test_pinned_brief_hash_moves_when_claim_order_changes():
    payload = load("example_brief.json")
    payload["claims"] = [payload["claims"][1], payload["claims"][0], payload["claims"][2]]
    assert canonical_hash(ProductBrief.model_validate(payload)) != pinned("example_brief")


def test_representative_brief_evidence_is_typed():
    brief = ProductBrief.model_validate(load("example_brief.json"))
    evidenced = [claim for claim in brief.claims if claim.evidence is not None]
    assert len(evidenced) == 2
    for claim in evidenced:
        assert isinstance(claim.evidence.fetched_at, datetime)
        assert claim.evidence.fetched_at.tzinfo is not None
        assert len(claim.evidence.content_hash) == 64
