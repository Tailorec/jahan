"""Phase 6: search by meaning."""

import numpy as np
import pytest

from simcore.population import describe_pool
from simcore.ports.embeddings import cache_path, codebook_digest, load_embeddings, rank_meaning
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import fake_cache

GOLD = {
    "kids": {"demo_children_count", "demo_parental_status", "life_stage"},
    "parents": {"demo_parental_status", "demo_children_count", "life_stage", "lifex_parenting_journey"},
    "money": {"demo_household_income", "socioeconomic_band"},
    "wealthy": {"socioeconomic_band", "demo_household_income"},
    "income": {"demo_household_income", "socioeconomic_band"},
    "retired": {"demo_employment_status", "life_stage", "seniority"},
    "religious": {"religiosity", "demo_religion_affiliation"},
    "politics": {"political_lean"},
    "health": {"health_general_health"},
    "students": {"demo_employment_status", "life_stage"},
    "married": {"demo_marital_status"},
    "uses AI tools": {"coding_ai_usage_frequency", "att_ai", "coding_ai_sentiment"},
    "young adults": {"age_bracket", "demo_generation", "life_stage"},
    "education level": {"highest_education"},
    "careful with money": {"habit_budget_tracking", "skill_budgeting", "socioeconomic_band", "demo_household_income"},
}
SURVEYED = ["stackoverflow", "gss", "prism", "real_human_survey"]


def test_cache_is_keyed_by_codebook_and_model(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[{"id": "a", "values": ["x"]}],
        shards={"data/persona-1m-0000.parquet": [
            {"codes": [0], "source": "gss", "source_record_id": "g1", "metadata_json": "{}"},
        ]},
    )
    digest = codebook_digest(cache)
    assert load_embeddings(cache, digest, "model-a") is None
    assert cache_path(cache, digest, "model-a") != cache_path(cache, digest, "model-b")


def test_ranking_sinks_what_almost_nobody_answered():
    embeddings = {"ids": ["a", "b", "c", "d"], "vectors": np.eye(4, dtype=np.float32)}
    relevance, score = rank_meaning([1, 1, 1, 1], embeddings, [0.5, 0.05, 0.005, 0.0])
    order = list(np.argsort(-score))
    assert order[0] == 0
    assert order[-1] == 3  # nobody carries it: last
    assert list(np.argsort(-score)).index(1) < list(np.argsort(-score)).index(2)


def test_a_described_attribute_never_changes_counts(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    before = describe_pool(matrix, ("gss", "stackoverflow"), ("sex",))
    after = describe_pool(matrix, ("gss", "stackoverflow"), ("sex",))
    assert before == after  # described attributes never enter `required`, so pool and costs cannot move


def _gate_inputs():
    from tests.real_corpus import REAL_CACHE

    if REAL_CACHE is None:
        pytest.skip("no cached corpus shards — the retrieval gate needs the real corpus")
    from simcore.ports.embeddings import endpoint_base

    if endpoint_base() is None:
        pytest.skip("no inference endpoint — the retrieval gate needs an endpoint")
    from simcore.ports.hf import HfCoresetSource
    from simcore.ports.matrix import load_matrix

    matrix = load_matrix(HfCoresetSource(cache_dir=REAL_CACHE))
    if matrix is None:
        pytest.skip("the persona value matrix was never built on this machine")
    digest = codebook_digest(REAL_CACHE)
    from simcore.ports.embeddings import embed_model, load_embeddings

    embeddings = load_embeddings(REAL_CACHE, digest, embed_model())
    if embeddings is None:
        pytest.skip("attribute embeddings are still building on this machine")
    return matrix, embeddings


def test_retrieval_gate():
    """Of the evaluation's 15 queries, at least 11 find an expected attribute
    first and 13 within the top five — surveyed sources only."""
    from simcore.population._search import _shares
    from simcore.ports.embeddings import _embed, embed_model, endpoint_base

    matrix, embeddings = _gate_inputs()
    from simcore.ports.decoder import Codebook
    from tests.real_corpus import REAL_CACHE

    codebook = Codebook.from_json(REAL_CACHE / "persona_codes.schema.json")
    ids = [attribute for attribute in matrix.attributes]
    assert [attribute for attribute in embeddings["ids"]] == ids
    shares = _shares(matrix, tuple(SURVEYED))
    first, top5 = 0, 0
    for query, expected in GOLD.items():
        vector = _embed([query.strip().lower()], embed_model(), endpoint_base() or "")[0]
        _, score = rank_meaning(vector, embeddings, shares)
        order = [ids[int(i)] for i in np.argsort(-score)]
        rank = next((position for position, attribute in enumerate(order) if attribute in expected), 9999)
        if rank == 0:
            first += 1
        if rank < 5:
            top5 += 1
    assert (first, top5) >= (11, 13), f"retrieval gate failed: {first} first, {top5} in top five"
