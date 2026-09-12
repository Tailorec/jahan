"""Joining the URL an author cites to what the sidecar recorded was retrieved."""

import json
from pathlib import Path

import pytest
import yaml

from simcore.brief import load_brief
from simcore.schemas import GateFailure, canonical_hash
from tests.study_builders import load_ontology

PINNED = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "hash_stability.json").read_text())
PINNED_BRIEF_HASH = PINNED["example_brief"]["hash"]


NUTRITION_PANEL = "https://example.com/nutrition-panel"
CATEGORY_REPORT = "https://example.com/category-report"


def payload_of(example_brief) -> dict:
    return yaml.safe_load(example_brief.read_text())


def sidecar_of(*urls: str) -> dict:
    """A sidecar recording a plausible retrieval for each url given."""
    return {url: {"content_hash": "ab" * 32, "fetched_at": "2026-09-01T00:00:00Z"} for url in (urls or (NUTRITION_PANEL, CATEGORY_REPORT))}


def test_a_cited_url_loads_with_the_evidence_the_sidecar_carries(example_brief, authored):
    path, ontology_dir = authored(payload_of(example_brief), load_ontology())
    first, _, third = load_brief(path, ontology_dir).brief.claims
    assert str(first.evidence.url) == "https://example.com/nutrition-panel"
    assert third.evidence is not None
    assert len(third.evidence.content_hash) == 64


def test_a_cited_url_absent_from_the_sidecar_is_refused(example_brief, authored):
    sidecar = {
        "https://example.com/nutrition-panel": {"content_hash": "ab" * 32, "fetched_at": "2026-09-01T00:00:00Z"}
    }
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    with pytest.raises(GateFailure) as raised:
        load_brief(path, ontology_dir)
    assert "category-report" in str(raised.value) and "never fetched" in str(raised.value)


def test_a_claim_records_the_url_it_cited(example_brief, authored):
    """A sidecar may restate the url it fetched, but what a claim records is what the brief cites."""
    sidecar = sidecar_of()
    sidecar[NUTRITION_PANEL]["url"] = NUTRITION_PANEL
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    assert str(load_brief(path, ontology_dir).brief.claims[0].evidence.url) == NUTRITION_PANEL


def test_a_sidecar_entry_naming_a_different_url_is_refused(example_brief, authored):
    sidecar = sidecar_of()
    sidecar[NUTRITION_PANEL]["url"] = "https://elsewhere.example/copy"
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    with pytest.raises(GateFailure, match="names a different url"):
        load_brief(path, ontology_dir)


def test_a_sidecar_entry_no_claim_cites_is_ignored(example_brief, authored):
    entry = {"content_hash": "ab" * 32, "fetched_at": "2026-09-01T00:00:00Z"}
    sidecar = {
        "https://example.com/nutrition-panel": entry,
        "https://example.com/category-report": entry,
        "https://example.com/uncited": entry,
    }
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    assert [claim.evidence is not None for claim in load_brief(path, ontology_dir).brief.claims] == [True, False, True]


def test_a_claim_carrying_no_url_loads_without_evidence(example_brief, authored):
    payload = payload_of(example_brief)
    for claim in payload["claims"]:
        claim.pop("evidence_url", None)
    payload["claims"][2]["source"] = "user_asserted"
    path, ontology_dir = authored(payload, load_ontology(), sidecar=None)
    assert all(claim.evidence is None for claim in load_brief(path, ontology_dir).brief.claims)


def test_a_brief_that_authors_a_claim_id_is_refused(example_brief, authored):
    payload = payload_of(example_brief)
    payload["claims"][0]["id"] = "C1"
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match=r"claims\[0\]\.id.*assigned by position"):
        load_brief(path, ontology_dir)


def test_a_brief_that_authors_evidence_is_refused(example_brief, authored):
    payload = payload_of(example_brief)
    payload["claims"][2]["evidence"] = {
        "url": "https://example.com/category-report",
        "fetched_at": "2026-09-01T00:00:00Z",
        "content_hash": "ab" * 32,
    }
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match=r"claims\[2\]\.evidence.*supplied by the sidecar"):
        load_brief(path, ontology_dir)


def test_the_example_brief_hashes_to_the_pinned_representative_study(example_brief, ontologies):
    assert canonical_hash(load_brief(example_brief, ontologies).brief) == PINNED_BRIEF_HASH


# --- the sidecar itself ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "match"),
    [("ab" * 32, "not text"), ([], "not a list"), (7, "not a number")],
    ids=["a-hash-on-its-own", "a-list", "a-number"],
)
def test_a_sidecar_entry_that_is_not_a_mapping_is_refused(example_brief, authored, entry, match):
    sidecar = {**sidecar_of(), NUTRITION_PANEL: entry}
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    with pytest.raises(GateFailure, match=f"must be a mapping of what was retrieved, {match}"):
        load_brief(path, ontology_dir)


@pytest.mark.parametrize("cited", [None, "", "   "], ids=["null", "empty", "whitespace"])
def test_a_citation_that_names_no_url_is_refused(example_brief, authored, cited):
    payload = payload_of(example_brief)
    payload["claims"][0]["evidence_url"] = cited
    path, ontology_dir = authored(payload, load_ontology(), sidecar=sidecar_of())
    with pytest.raises(GateFailure, match=r"claims\[0\]\.evidence_url: cite a url or leave the field out"):
        load_brief(path, ontology_dir)


def test_a_missing_sidecar_is_refused_as_such(example_brief, authored):
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=None)
    with pytest.raises(GateFailure, match=r"sidecar .*is missing"):
        load_brief(path, ontology_dir)


def test_a_malformed_sidecar_is_refused_as_such(example_brief, authored):
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar="{not json")
    with pytest.raises(GateFailure, match="is not valid JSON"):
        load_brief(path, ontology_dir)


def test_a_sidecar_that_is_not_a_mapping_is_refused(example_brief, authored):
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar="[1, 2]")
    with pytest.raises(GateFailure, match="must be a mapping of cited URLs"):
        load_brief(path, ontology_dir)


def test_a_malformed_sidecar_entry_is_refused(example_brief, authored):
    sidecar = {
        "https://example.com/nutrition-panel": {"content_hash": "ab" * 32, "fetched_at": "2026-09-01T00:00:00Z"},
        "https://example.com/category-report": {"content_hash": "not-a-hash", "fetched_at": "2026-09-01T00:00:00Z"},
    }
    path, ontology_dir = authored(payload_of(example_brief), load_ontology(), sidecar=sidecar)
    with pytest.raises(GateFailure, match="content_hash"):
        load_brief(path, ontology_dir)
