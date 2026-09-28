"""Phase 3: audience head counts against quotas."""

import pytest

from simcore.population import preview_audiences
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import fake_cache
from tests.real_corpus import REAL_CACHE, real_corpus


def _matrix(tmp_path):
    return build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))


def test_quota_is_share_of_study_size(tmp_path):
    matrix = _matrix(tmp_path)
    [got] = preview_audiences(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "a", "share": 0.4, "filters": {}}], 200,
    )
    assert got.quota == 80
    assert got.head_count == 3
    assert got.to_json()["quota"] == 80


def test_source_mix_and_dominant_survey_are_shown(tmp_path):
    matrix = _matrix(tmp_path)
    [got] = preview_audiences(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "gss-only", "share": 0.5, "filters": {"sex": ["female"]}}], 200,
    )
    assert got.by_source == {"gss": 1}
    assert got.dominant_source == "gss"
    [one] = preview_audiences(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "g", "share": 0.5, "filters": {"urbanicity": ["rural"]}}], 200,
    )
    assert one.by_source == {"stackoverflow": 2}
    assert one.dominant_source == "stackoverflow"


def test_filter_costs_name_removal_with_both_counts(tmp_path):
    matrix = _matrix(tmp_path)
    [got] = preview_audiences(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "a", "share": 0.5, "filters": {"sex": ["female"], "urbanicity": ["rural"]}}], 200,
    )
    assert got.head_count == 0
    assert got.filter_costs["sex"] == 2
    assert got.filter_costs["urbanicity"] == 1


def test_empty_audience_names_the_unshared_answers(tmp_path):
    matrix = _matrix(tmp_path)
    [got] = preview_audiences(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "a", "share": 0.5, "filters": {"sex": ["female"], "urbanicity": ["rural"]}}], 200,
    )
    assert got.empty_note is not None
    assert "never gave" in got.empty_note


def test_unknown_values_are_refused(tmp_path):
    matrix = _matrix(tmp_path)
    with pytest.raises(ValueError, match="no such value"):
        preview_audiences(
            matrix, ("gss",), (),
            [{"name": "a", "share": 0.5, "filters": {"sex": ["nope"]}}], 200,
        )


@real_corpus
def test_parent_of_young_kids_reference_counts():
    from simcore.ports.matrix import load_matrix

    matrix = load_matrix(HfCoresetSource(cache_dir=REAL_CACHE))
    assert matrix is not None, "the persona value matrix was never built on this machine"
    [got] = preview_audiences(
        matrix, ("stackoverflow", "gss"), (),
        [{"name": "parents", "share": 0.5, "filters": {"life_stage": ["Parent of young kids"]}}], 200,
    )
    assert got.by_source.get("stackoverflow") == 1017
    assert got.by_source.get("gss", 0) == 0


def test_the_design_weighs_each_pool_by_how_many_of_it_answered():
    # Half the study from a pool where everyone answered "x", half from one where one in ten answered "y":
    # the drawn answers are about ten "x" to one "y", and that is what the design must expect.
    from types import SimpleNamespace

    from simcore.population._assess import _expected

    everyone = [SimpleNamespace(values={"a": "x"}) for _ in range(100)]
    few = [SimpleNamespace(values={"a": "y"}) for _ in range(10)] + [SimpleNamespace(values={}) for _ in range(90)]
    expected = _expected([(0.5, everyone), (0.5, few)], "a", ["x", "y"])
    assert abs(expected[0] / expected.sum() - 1 / 1.1) < 1e-9
