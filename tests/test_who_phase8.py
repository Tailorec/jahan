"""Phase 8: drafting from the description."""

import json
import re

from simcore.population import Reading, cross_survey_core, draft
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import COLUMNS, fake_cache

EXAMPLES = [
    "A children's education savings app. Three groups: parents of young kids (40%), people early in their career (30%) and retirees (30%), all in North America. I care about how careful they are with money and how much they trust technology.",
    "An AI code-review tool. Software developers who use AI coding assistants every day, compared with developers who never use them. I want to know how much they trust AI output.",
    "A premium meal-kit subscription. Busy parents who work full time, compared with retirees who cook every day. I want to know how price-sensitive they are.",
]


class _Codebook:
    def __init__(self, columns):
        self._columns = columns
        self.attributes = tuple(c["id"] for c in columns)

    def vocabulary(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return tuple(c["values"])
        return None

    def label(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return c.get("label") or attribute
        return attribute

    def category(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return c.get("category") or ""
        return ""


def _wordy_chat(values=None):
    """A deterministic stand-in for the model: picks the first candidate
    sharing a word with the phrase, else null — good enough to prove the
    server checks whatever it is told."""
    values = values or {}

    def run(system, user, max_tokens):
        candidates = re.findall(r"^([a-z0-9_]+):", user, re.M)
        phrase = user.split("Researcher means:")[-1].strip().lower()
        words = set(re.findall(r"[a-z0-9]+", phrase))
        picking_values = "value(s)" in system
        for candidate in candidates:
            hay = set(re.findall(r"[a-z0-9]+", candidate.replace("_", " ")))
            if any(term in word or word in term for term in words for word in hay if len(word) > 2):
                if picking_values:
                    return {"id": candidate, "values": values.get(candidate)}
                return {"id": candidate}
        return {"id": None}

    return run


def _reading():
    from simcore.population import Group

    return Reading(
        product="savings app",
        groups=(
            Group(name="parents", share=0.5, traits=("sex folk",)),
            Group(name="devs", share=0.5, traits=("region folk",)),
        ),
        everyone=("urban dwellers",),
        topics=("trust",),
    )


_VALUES = {"sex": ["female"], "region": ["Africa"], "urbanicity": ["rural"]}


def test_reused_conditioning_set_is_kept_and_locked(tmp_path):
    from simcore.population import Group

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    ontology = {
        "category": "study", "version": "1.0.0",
        "attribute_domains": {"sex": "demographic", "region": "demographic"},
        "conditioning_set": ["sex"],
        "relevance_order": ["sex", "region"],
    }
    drafted = draft(
        _wordy_chat(_VALUES), "sex-segregated study", _reading(),
        {"mode": "reuse", "id": "study"}, ("gss", "stackoverflow"),
        matrix, codebook, None, lambda category_id: ontology,
    )
    required = [entry["id"] for entry in drafted.attributes if entry["required"]]
    assert required == ["sex"]
    assert all(entry["locked"] for entry in drafted.attributes if entry["role"] == "category")


def test_new_category_defaults_to_the_cross_survey_core(tmp_path):
    from simcore.population import Group

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    drafted = draft(
        _wordy_chat(_VALUES), "a new study",
        Reading(product="thing", groups=(Group(name="a", share=1.0, traits=()),), everyone=(), topics=()),
        {"mode": "new", "id": "thing"}, ("gss", "stackoverflow"),
        matrix, codebook, None, lambda category_id: None,
    )
    required = [entry["id"] for entry in drafted.attributes if entry["required"]]
    assert required == cross_survey_core(matrix)
    assert set(required) == set(COLUMNS[i]["id"] for i in range(len(COLUMNS)))


def test_shared_traits_are_filters_never_requirements(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    ontology = {
        "category": "study", "version": "1.0.0",
        "attribute_domains": {"sex": "demographic"},
        "conditioning_set": ["sex"],
        "relevance_order": ["sex"],
    }
    drafted = draft(
        _wordy_chat(_VALUES), "urban study", _reading(),
        {"mode": "reuse", "id": "study"}, ("gss", "stackoverflow"),
        matrix, codebook, None, lambda category_id: ontology,
    )
    required = {entry["id"] for entry in drafted.attributes if entry["required"]}
    assert required == {"sex"}  # the shared trait never enters the conditioning set
    for audience in drafted.audiences:
        assert "urbanicity" in audience["filters"]  # but filters each audience


def test_invented_ids_and_out_of_list_values_are_refused(tmp_path):
    from simcore.population import Group

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    reading = Reading(
        product="thing",
        groups=(Group(name="a", share=1.0, traits=("invented trait", "bad sex value")),),
        everyone=(), topics=(),
    )

    def lying(system, user, max_tokens):
        if "invented trait" in user:
            return {"id": "att_made_up", "values": ["x"]}
        return {"id": "sex", "values": ["nope"]}

    drafted = draft(
        lying, "a study", reading,
        {"mode": "new", "id": "thing"}, ("gss",),
        matrix, codebook, None, lambda category_id: None,
    )
    assert drafted.audiences[0]["filters"] == {}
    missing = {item["phrase"]: item["missing"] for item in drafted.unmatched}
    assert "was not offered" in missing["invented trait"]
    assert "no value from its list" in missing["bad sex value"]


def test_disagreement_becomes_a_question_and_applies_everywhere(tmp_path):
    from simcore.population import Group

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    reading = Reading(
        product="thing",
        groups=(
            Group(name="a", share=0.5, traits=("sex region wobbly",)),
            Group(name="b", share=0.5, traits=("sex region wobbly",)),
        ),
        everyone=(), topics=(),
    )

    def wobbly(system, user, max_tokens):
        if "Whole description:" in user:
            return {"id": "sex", "values": ["female"]}
        return {"id": "region", "values": ["Africa"]}

    drafted = draft(
        wobbly, "a wobbly study", reading,
        {"mode": "new", "id": "thing"}, ("gss", "stackoverflow"),
        matrix, codebook, None, lambda category_id: None,
    )
    assert drafted.audiences[0]["filters"] == {}
    assert len(drafted.questions) == 1
    question = drafted.questions[0]
    assert question.phrase == "sex region wobbly"
    assert question.applies_to == ("a", "b")  # one answer applies wherever it was asked
    assert {choice["attribute"] for choice in question.choices} == {"sex", "region"}
    assert all("n_alone" in choice for choice in question.choices)


def test_three_example_briefs_draft_only_codebook_names(tmp_path):
    from simcore.population import Group, read_description

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    codebook = _Codebook(COLUMNS)
    ontology = {
        "category": "study", "version": "1.0.0",
        "attribute_domains": {"sex": "demographic"},
        "conditioning_set": ["sex"],
        "relevance_order": ["sex"],
    }

    def echoing(system, user, max_tokens):
        if "audiences" in system:
            return {
                "product": "thing",
                "audiences": [{"name": "group_a", "share": 0.5, "traits": ["sex folk"]}],
                "everyone": [], "matters": ["urbanicity life"],
            }
        return _wordy_chat(_VALUES)(system, user, max_tokens)

    for text in EXAMPLES:
        reading = read_description(echoing, text)
        drafted = draft(
            echoing, text, reading,
            {"mode": "reuse", "id": "study"}, ("gss", "stackoverflow"),
            matrix, codebook, None, lambda category_id: ontology,
        )
        for audience in drafted.audiences:
            for attribute, values in audience["filters"].items():
                assert attribute in codebook.attributes
                assert set(values) <= set(codebook.vocabulary(attribute))


def test_by_hand_needs_no_model_and_keeps_the_categorys_scales(tmp_path):
    # Without an endpoint the page authors by hand: an empty reading drafts only the category's own attributes.
    def no_model(*_):
        raise AssertionError("nothing to read, so no model is asked")

    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    ontology = {
        "category": "study", "version": "1.0.0",
        "attribute_domains": {"sex": "demographic", "region": "demographic"},
        "conditioning_set": ["sex"], "relevance_order": ["sex", "region"],
        "ordinal_scales": [{"attribute": "region", "bands": []}],
    }
    drafted = draft(
        no_model, "", Reading(product=None, groups=(), everyone=(), topics=()),
        {"mode": "reuse", "id": "study"}, ("gss",), matrix, _Codebook(COLUMNS), None, lambda _: ontology,
    )
    assert drafted.audiences == () and drafted.questions == ()
    assert {entry["id"]: entry["ordered"] for entry in drafted.attributes} == {"sex": False, "region": True}
