"""Audience sets: what Who you study finishes with, saved once and chosen by a study."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from simcore.population import list_audience_sets, load_audience_set, save_audience_set
from simcore.web import create_app

ONTOLOGY = {
    "category": "savings_app", "version": "1.0.1",
    "attribute_domains": {"age_bracket": "demographic", "region": "demographic"},
    "conditioning_set": ["age_bracket"], "completion_policy": {"completable_domains": ["economic"]},
    "ordinal_scales": [], "relevance_order": ["age_bracket", "region"],
    "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
}


def _ontologies(tmp_path):
    root = tmp_path / "ontologies"
    (root / "savings_app").mkdir(parents=True)
    (root / "savings_app" / "1.0.1.json").write_text(json.dumps(ONTOLOGY))
    return root


def _body(**overrides):
    body = {
        "category": "savings_app", "ontology_version": "1.0.1", "name": "parents vs retirees",
        "description": "A savings app for parents and retirees.",
        "audiences": [
            {"name": "parents", "share": 0.6, "attribute_filters": {"region": "North America"}},
            {"name": "retirees", "share": 0.4, "attribute_filters": {"age_bracket": ["65-74", "75+"]}},
        ],
        "assumptions": [{"text": "survey differences are people differences", "source": "assumed"}],
        "sources": ["gss", "stackoverflow"], "study_size": 200,
    }
    body.update(overrides)
    return body


def test_a_set_round_trips_through_the_routes(tmp_path):
    client = TestClient(create_app(runs_dir=tmp_path / "runs", ontology_dir=_ontologies(tmp_path), audience_dir=tmp_path / "audiences"))
    assert client.get("/api/audience-sets").json() == {"audience_sets": []}  # no folder yet is no sets yet
    saved = client.post("/api/audience-sets", json=_body())
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["category"] == "savings_app" and record["ontology_version"] == "1.0.1"
    listed = client.get("/api/audience-sets").json()["audience_sets"]
    assert [item["id"] for item in listed] == [record["id"]]
    again = client.get(f"/api/audience-sets/savings_app/{record['id']}").json()
    assert again["audiences"] == _body()["audiences"] and again["study_size"] == 200 and again["sources"] == ["gss", "stackoverflow"]
    assert client.get("/api/audience-sets/savings_app/20260101-000000-nope").status_code == 404


@pytest.mark.parametrize("overrides, refusal", [
    ({"ontology_version": "1.0.2"}, "no saved ontology"),
    ({"audiences": [{"name": "a", "share": 1.0, "attribute_filters": {"income": "high"}}]}, "does not declare"),
    ({"audiences": [{"name": "a", "share": 0.5, "attribute_filters": {}}]}, "add to 100%"),
    ({"audiences": []}, "at least one audience"),
    ({"study_size": 0}, "study_size"),
])
def test_a_set_that_does_not_fit_its_ontology_is_refused(tmp_path, overrides, refusal):
    with pytest.raises(ValueError, match=refusal):
        save_audience_set(tmp_path / "audiences", _ontologies(tmp_path), _body(**overrides))
    assert not (tmp_path / "audiences").exists() or not list((tmp_path / "audiences").rglob("*.json"))


def test_a_saved_set_is_never_overwritten_and_the_newest_lists_first(tmp_path):
    ontologies, root = _ontologies(tmp_path), tmp_path / "audiences"
    first = save_audience_set(root, ontologies, _body(), now=datetime(2026, 9, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="already exists"):
        save_audience_set(root, ontologies, _body(), now=datetime(2026, 9, 1, tzinfo=timezone.utc))
    second = save_audience_set(root, ontologies, _body(name="students only"), now=datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert [item["id"] for item in list_audience_sets(root)] == [second["id"], first["id"]]
    assert load_audience_set(root, "savings_app", first["id"])["name"] == "parents vs retirees"
    assert load_audience_set(root, "../etc", first["id"]) is None
