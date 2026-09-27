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
