import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from simcore.schemas import ProductBrief, canonical_hash

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_example_brief() -> dict:
    return json.loads((FIXTURES / "example_brief.json").read_text())


def test_representative_brief_file_validates():
    brief = ProductBrief.model_validate(load_example_brief())
    assert [claim.id for claim in brief.claims] == ["C1", "C2", "C3"]
    assert brief.product.name == "Protein water"
    assert brief.audiences_declared is True
    assert brief.ontology.conditioning_set >= {"age", "sex", "exercise_frequency"}


def test_representative_brief_file_with_unknown_key_refused():
    payload = load_example_brief()
    payload["unexpected_key"] = True
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(payload)


def test_representative_brief_hash_is_pinned():
    brief = ProductBrief.model_validate(load_example_brief())
    pinned = json.loads((FIXTURES / "hash_stability.json").read_text())["example_brief"]["hash"]
    assert canonical_hash(brief) == pinned


def test_pinned_brief_hash_survives_whitespace_and_key_insertion_order():
    payload = load_example_brief()
    payload["product"]["name"] = "  Protein water  "
    payload["audiences"][0]["attribute_filters"] = dict(
        reversed(list(payload["audiences"][0]["attribute_filters"].items()))
    )
    assert payload["product"]["name"] != load_example_brief()["product"]["name"]
    brief = ProductBrief.model_validate(payload)
    pinned = json.loads((FIXTURES / "hash_stability.json").read_text())["example_brief"]["hash"]
    assert canonical_hash(brief) == pinned


def test_pinned_brief_hash_moves_when_claim_order_changes():
    payload = load_example_brief()
    payload["claims"] = [payload["claims"][1], payload["claims"][0], payload["claims"][2]]
    brief = ProductBrief.model_validate(payload)
    pinned = json.loads((FIXTURES / "hash_stability.json").read_text())["example_brief"]["hash"]
    assert canonical_hash(brief) != pinned


def test_representative_brief_evidence_is_typed():
    brief = ProductBrief.model_validate(load_example_brief())
    evidenced = [claim for claim in brief.claims if claim.evidence is not None]
    assert len(evidenced) == 2
    for claim in evidenced:
        assert isinstance(claim.evidence.fetched_at, datetime)
        assert len(claim.evidence.content_hash) == 64
