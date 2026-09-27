"""Phase 9: nothing changed behind your back."""

from simcore.population import continue_blockers, fit_to_quotas
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import fake_cache


def _matrix(tmp_path):
    return build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))


def test_below_quota_moves_costliest_filter_with_counts(tmp_path):
    matrix = _matrix(tmp_path)
    [fitted] = fit_to_quotas(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "a", "share": 1.0, "filters": {"sex": ["female"], "urbanicity": ["rural"]}, "descriptions": []}],
        200,
    )
    assert fitted["below_quota"] is True  # one filter left and still short: Continue stays blocked
    assert len(fitted["changes"]) == 1
    change = fitted["changes"][0]
    assert change["attribute"] == "sex"  # removing it grows 0 → 2, the costliest
    assert (change["before"], change["after"]) == (0, 2)
    assert change["accepted"] is False
    assert "sex" in fitted["descriptions"]


def test_fitting_keeps_stated_shares(tmp_path):
    matrix = _matrix(tmp_path)
    [fitted] = fit_to_quotas(
        matrix, ("gss", "stackoverflow"), (),
        [{"name": "a", "share": 0.4, "filters": {}, "descriptions": []}], 200,
    )
    assert fitted["share"] == 0.4
    assert fitted["quota"] == 80


def test_continue_lists_everything_in_the_way(tmp_path):
    blockers = continue_blockers(
        None,
        [{"phrase": "wobbly", "choices": [], "applies_to": ["a"]}],
        [{"attribute": "urbanicity", "accepted": False}],
        [{"name": "a", "share": 0.5}, {"name": "b", "share": None}],
        [{"quota": 100, "head_count": 3}],
    )
    assert any("category" in blocker for blocker in blockers)
    assert any("wobbly" in blocker for blocker in blockers)
    assert any("urbanicity" in blocker for blocker in blockers)
    assert any("share" in blocker for blocker in blockers)
    assert any("below its quota" in blocker for blocker in blockers)


def test_shares_must_sum_to_all_of_it():
    assert any("100%" in blocker for blocker in continue_blockers(
        {"id": "x"}, [], [],
        [{"name": "a", "share": 0.4}, {"name": "b", "share": 0.4}],
        [{"quota": 80, "head_count": 80}, {"quota": 80, "head_count": 80}],
    ))


def test_a_fitting_audience_blocks_nothing():
    assert continue_blockers(
        {"id": "x"}, [], [],
        [{"name": "a", "share": 1.0}],
        [{"quota": 200, "head_count": 200}],
    ) == []


def test_no_audience_blocks_continue():
    assert any("audience" in blocker for blocker in continue_blockers({"id": "x"}, [], [], [], []))


def test_the_preview_route_counts_and_writes_the_ledger(tmp_path):
    # Every head count on the page arrives through this route; it once failed on every request.
    from fastapi.testclient import TestClient

    from simcore.ports.hf import HfCoresetSource
    from simcore.ports.matrix import build_matrix
    from simcore.web import create_app
    from tests.boundary.ports.test_index_catalog import COLUMNS, fake_cache

    cache = fake_cache(tmp_path)
    build_matrix(HfCoresetSource(cache_dir=cache))
    client = TestClient(create_app(runs_dir=tmp_path / "runs", ontology_dir=tmp_path / "ontologies", corpus_dir=cache))
    column = COLUMNS[0]
    body = client.post("/api/audiences/preview", json={
        "sources": ["gss", "stackoverflow"], "required": [], "study_size": 10,
        "audiences": [{"name": "a", "share": 1.0, "filters": {column["id"]: column["values"][:1]}}],
    })
    assert body.status_code == 200, body.text
    assert body.json()["audiences"][0]["quota"] == 10 and isinstance(body.json()["assumptions"], list)
