"""Phase 11: ready for a study, into launch."""

import pytest

from simcore.population import prepare_launch
from simcore.schemas import Assumption, Audience, CategoryOntology


def _before():
    return {
        "category": "study", "version": "1.0.0",
        "attribute_domains": {"sex": "demographic"},
        "conditioning_set": ["sex"],
        "completion_policy": {"completable_domains": ["economic"]},
        "ordinal_scales": [],
        "relevance_order": ["sex"],
        "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
        "targets": None, "drafting": None,
    }


class _Codebook:
    attributes = ("sex", "region")

    def vocabulary(self, attribute):
        return {"sex": ("female", "male"), "region": ("Africa", "Europe")}[attribute]

    def label(self, attribute):
        return attribute

    def category(self, attribute):
        return ""


def test_unchanged_reuse_reuses_the_version():
    out = prepare_launch(
        {"mode": "reuse", "id": "study"},
        [{"id": "sex", "domain": "demographic", "required": True}],
        [{"name": "a", "share": 1.0, "filters": {"sex": ["female"]}}],
        [{"text": "t", "source": "assumed"}],
        lambda category_id: _before(), _Codebook(),
    )
    assert out["action"] == "reused"
    assert out["ontology"]["version"] == "1.0.0"
    CategoryOntology.model_validate(out["ontology"])
    Audience.model_validate(out["audiences"][0])
    Assumption.model_validate(out["assumptions"][0])


def test_declaring_more_publishes_a_patch_with_conditioning_unchanged():
    out = prepare_launch(
        {"mode": "reuse", "id": "study"},
        [{"id": "sex", "domain": "demographic", "required": True},
         {"id": "region", "domain": "demographic", "required": False}],
        [{"name": "a", "share": 1.0, "filters": {"region": ["Africa"]}}],
        [],
        lambda category_id: _before(), _Codebook(),
    )
    assert out["action"] == "new_version"
    assert out["ontology"]["version"] == "1.0.1"
    assert out["ontology"]["conditioning_set"] == ["sex"]
    CategoryOntology.model_validate(out["ontology"])


def test_new_category_starts_at_1_0_0():
    out = prepare_launch(
        {"mode": "new", "id": "thing"},
        [{"id": "sex", "domain": "demographic", "required": True}],
        [{"name": "a", "share": 1.0, "filters": {}}],
        [],
        lambda category_id: None, _Codebook(),
    )
    assert out["action"] == "new_category"
    assert out["ontology"]["version"] == "1.0.0"
    CategoryOntology.model_validate(out["ontology"])


def test_audience_filters_outside_the_ontology_are_refused():
    with pytest.raises(ValueError, match="does not declare"):
        prepare_launch(
            {"mode": "new", "id": "thing"},
            [{"id": "sex", "domain": "demographic", "required": True}],
            [{"name": "a", "share": 1.0, "filters": {"region": ["Africa"]}}],
            [],
            lambda category_id: None, _Codebook(),
        )


def test_the_latest_version_is_the_highest_number_not_the_last_in_text_order(tmp_path):
    """Text order puts 1.0.10 before 1.0.2, so reuse would pick an old version from the tenth patch on."""
    from simcore.population._describe import ontology_versions

    for version in ("1.0.2", "1.0.10", "1.0.0"):
        (tmp_path / f"{version}.json").write_text("{}")
    assert [path.stem for path in ontology_versions(tmp_path)] == ["1.0.0", "1.0.2", "1.0.10"]


def test_an_attribute_marked_ordered_is_saved_with_its_scale():
    """The page's "ordered" was never sent and never saved: new categories always had no scales."""
    new = prepare_launch(
        {"mode": "new", "id": "thing"},
        [{"id": "sex", "domain": "demographic", "required": True},
         {"id": "region", "domain": "demographic", "required": False, "ordered": True}],
        [{"name": "a", "share": 1.0, "filters": {}}], [], lambda category_id: None, _Codebook(),
    )
    assert new["ontology"]["ordinal_scales"] == [
        {"attribute": "region", "bands": [{"label": "Africa", "midpoint": 0.0}, {"label": "Europe", "midpoint": 1.0}]}]
    reused = prepare_launch(
        {"mode": "reuse", "id": "study"},
        [{"id": "sex", "domain": "demographic", "required": True},
         {"id": "region", "domain": "demographic", "required": False, "ordered": True}],
        [{"name": "a", "share": 1.0, "filters": {}}], [], lambda category_id: _before(), _Codebook(),
    )
    assert [scale["attribute"] for scale in reused["ontology"]["ordinal_scales"]] == ["region"]
    assert reused["action"] == "new_version"


def test_a_machine_with_no_ontologies_folder_lists_none_and_the_first_save_makes_it(tmp_path):
    from fastapi.testclient import TestClient

    from simcore.web import create_app
    from tests.boundary.web.test_ontology import _fixture_corpus

    folder = tmp_path / "ontologies"
    client = TestClient(create_app(runs_dir=tmp_path / "runs", ontology_dir=folder, corpus_dir=_fixture_corpus(tmp_path)))
    assert client.get("/api/ontologies").json() == {"ontologies": []}
    assert client.get("/api/categories").json() == {"categories": []}
    saved = client.post("/api/ontologies", json={"ontology": {
        "category": "fresh", "version": "1.0.0", "attribute_domains": {"age_bracket": "demographic"},
        "conditioning_set": ["age_bracket"], "completion_policy": {"completable_domains": ["economic"]},
        "ordinal_scales": [], "relevance_order": ["age_bracket"], "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
    }})
    assert saved.status_code == 201 and (folder / "fresh" / "1.0.0.json").is_file()
    assert [o["category"] for o in client.get("/api/ontologies").json()["ontologies"]] == ["fresh"]
