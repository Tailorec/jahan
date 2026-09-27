"""Phase 10: follow-ups."""

from simcore.population import Group, Reading, apply_followup
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import COLUMNS, fake_cache
from tests.test_who_phase8 import _VALUES, _Codebook, _wordy_chat


def _followup_chat():
    def run(system, user, max_tokens):
        if "audiences" in system and "traits" in system:
            if "group of students" in user:
                return {
                    "product": None,
                    "audiences": [{"name": "students", "share": None, "traits": ["sex folk"]}],
                    "everyone": [], "matters": [],
                }
            if "North America" in user:
                return {
                    "product": None, "audiences": [],
                    "everyone": ["region folk"], "matters": [],
                }
            return {"product": None, "audiences": [], "everyone": [], "matters": ["trust"]}
        return _wordy_chat(_VALUES)(system, user, max_tokens)

    return run


def test_adding_a_group_adds_one_audience_and_asks_for_share(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    existing = [{"name": "parents", "share": 0.5, "filters": {}, "descriptions": []}]
    out = apply_followup(
        _followup_chat(), "add a group of students", existing,
        ("gss", "stackoverflow"), matrix, _Codebook(COLUMNS), None,
    )
    assert out["added"] == ["students"]
    assert len(out["audiences"]) == 2
    students = out["audiences"][1]
    assert students["share"] is None  # the new group waits for its share
    assert existing[0]["share"] == 0.5  # stated shares are kept


def test_refining_all_adds_filters_and_no_audience(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    existing = [
        {"name": "a", "share": 0.5, "filters": {}, "descriptions": []},
        {"name": "b", "share": 0.5, "filters": {}, "descriptions": []},
    ]
    out = apply_followup(
        _followup_chat(), "all of them in North America", existing,
        ("gss", "stackoverflow"), matrix, _Codebook(COLUMNS), None,
    )
    assert out["added"] == []
    assert len(out["audiences"]) == 2
    for audience in out["audiences"]:
        assert "region" in audience["filters"]


def test_followup_never_changes_the_category(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    out = apply_followup(
        _followup_chat(), "add a group of students",
        [{"name": "a", "share": 1.0, "filters": {}, "descriptions": []}],
        ("gss",), matrix, _Codebook(COLUMNS), None,
    )
    assert "category" not in out and "conditioning" not in " ".join(out.keys())


def test_conversation_shows_matching_and_what_could_not_be_found(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    out = apply_followup(
        _followup_chat(), "I also care about xyzzy",
        [{"name": "a", "share": 1.0, "filters": {}, "descriptions": []}],
        ("gss",), matrix, _Codebook(COLUMNS), None,
    )
    assert "fits" in out and "unmatched" in out
