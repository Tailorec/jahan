"""Phase 7: describe, then confirm the category."""

import json

from simcore.population import describe, list_categories, match_category, read_description
from simcore.population._describe import PARSE_SYSTEM


class _Codebook:
    def __init__(self, attributes):
        self.attributes = tuple(attributes)

    def vocabulary(self, attribute):
        return ("x",)

    def label(self, attribute):
        return attribute

    def category(self, attribute):
        return ""


def _chat(parsed, verdict=None):
    def run(system, user, max_tokens):
        if "existing study category" in system:
            return dict(verdict or {})
        return dict(parsed)
    return run


def test_guess_words_are_topics_whatever_the_model_returned():
    reading = read_description(
        _chat({
            "product": "savings app",
            "audiences": [{"name": "parents", "share": 0.5, "traits": ["has young children", "possibly health-conscious"]}],
            "everyone": ["might retire soon"],
            "matters": ["trust in apps"],
        }),
        "parents who are possibly health-conscious",
    )
    assert reading.groups[0].traits == ("has young children",)
    assert "possibly health-conscious" in reading.topics
    assert "might retire soon" in reading.topics
    assert reading.everyone == ()


def test_category_match_is_a_closed_choice():
    categories = [{"id": "education_savings", "version": "1.0.0", "products": []}]
    match, _ = match_category(_chat({}, {"match": "education_savings"}), "savings app", categories)
    assert match is not None and match["id"] == "education_savings"
    match, new_id = match_category(_chat({}, {"match": "something_else"}), "savings app", categories)
    assert match is None
    assert new_id


def test_only_categories_the_codebook_carries_are_offered(tmp_path):
    root = tmp_path / "ontologies"
    (root / "good").mkdir(parents=True)
    (root / "good" / "1.0.0.json").write_text(json.dumps({
        "category": "good", "version": "1.0.0",
        "attribute_domains": {"age_bracket": "demographic"},
        "conditioning_set": ["age_bracket"],
        "relevance_order": ["age_bracket"],
    }))
    (root / "beverage_protein").mkdir()
    (root / "beverage_protein" / "1.0.0.json").write_text(json.dumps({
        "category": "beverage_protein", "version": "1.0.0",
        "attribute_domains": {"age": "demographic", "sex": "demographic"},
        "conditioning_set": ["age"],
        "relevance_order": ["age", "sex"],
    }))
    offered = list_categories(root, None, _Codebook(["age_bracket"]))
    assert [category["id"] for category in offered] == ["good"]


def test_a_follow_up_naming_one_group_reads_as_one_group():
    reading = read_description(
        _chat({
            "product": None,
            "audiences": [{"name": "students", "share": None, "traits": ["studies"]}],
            "everyone": [],
            "matters": [],
        }),
        "add a group of students too",
    )
    assert len(reading.groups) == 1
    assert "young_urban_professionals" not in PARSE_SYSTEM
    assert "Return only the groups the description itself names" in PARSE_SYSTEM


def test_describe_returns_reading_before_any_draft(tmp_path):
    root = tmp_path / "ontologies"
    root.mkdir()
    out = describe(
        _chat(
            {"product": "savings app",
             "audiences": [{"name": "parents", "share": 0.4, "traits": ["has young children"]}],
             "everyone": [], "matters": ["trust"]},
            {"match": None, "new_id": "savings"},
        ),
        "savings app for parents",
        root, None, _Codebook(["age_bracket"]),
    )
    assert out["reading"]["groups"][0]["traits"] == ["has young children"]
    assert out["reading"]["topics"] == ["trust"]
    assert out["match"] is None
    assert "draft" not in out and "audiences" not in out
