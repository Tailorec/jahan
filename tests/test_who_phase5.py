"""Phase 5: text sources and the ledger."""

from pathlib import Path

from simcore.population import assumption_entries, preview_audiences
from simcore.population._audiences import TEXT_LABEL
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from simcore.schemas import Assumption
from tests.boundary.ports.test_index_catalog import fake_cache
from tests.real_corpus import REAL_CACHE, real_corpus

REPO = Path(__file__).resolve().parents[1]


def test_text_sources_are_off_by_default_and_labelled():
    source = (REPO / "frontend" / "app" / "who" / "page.tsx").read_text()
    assert '["stackoverflow", "gss", "prism", "real_human_survey"]' in source
    assert "read by a model from text, not surveyed" in source
    assert TEXT_LABEL == "read by a model from text, not surveyed"


def test_below_quota_reports_what_text_sources_would_add(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[{"id": "a", "values": ["x", "y"]}],
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [0], "source": "gss", "source_record_id": "g1", "metadata_json": "{}"},
                {"codes": [1], "source": "amazon", "source_record_id": "a1", "metadata_json": "{}"},
                {"codes": [1], "source": "wiki", "source_record_id": "w1", "metadata_json": "{}"},
            ],
        },
    )
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    [got] = preview_audiences(
        matrix, ("gss",), (),
        [{"name": "ys", "share": 0.5, "filters": {"a": ["y"]}}], 200,
    )
    assert got.head_count == 0
    assert got.text_would_add == {"amazon": 1, "wiki": 1}


def test_admitting_a_text_source_writes_an_assumed_entry(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[{"id": "a", "values": ["x", "y"]}],
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [0], "source": "gss", "source_record_id": "g1", "metadata_json": "{}"},
                {"codes": [1], "source": "amazon", "source_record_id": "a1", "metadata_json": "{}"},
            ],
        },
    )
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    audiences = [{"name": "all", "share": 1.0, "filters": {}}]
    previews = preview_audiences(matrix, ("gss", "amazon"), (), audiences, 200)
    entries = assumption_entries(matrix, ("gss", "amazon"), (), audiences, previews)
    assert len(entries) == 1
    Assumption.model_validate(entries[0])
    assert entries[0]["source"] == "assumed"
    assert "amazon" in entries[0]["text"]


def test_split_surveys_produce_an_assumed_entry_naming_both(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    audiences = [
        {"name": "gss folk", "share": 0.5, "filters": {"urbanicity": ["suburban"]}},
        {"name": "devs", "share": 0.5, "filters": {"urbanicity": ["rural"]}},
    ]
    previews = preview_audiences(matrix, ("gss", "stackoverflow"), (), audiences, 200)
    assert previews[0].dominant_source == "gss"
    assert previews[1].dominant_source == "stackoverflow"
    entries = assumption_entries(matrix, ("gss", "stackoverflow"), (), audiences, previews)
    assert len(entries) == 1
    Assumption.model_validate(entries[0])
    assert "gss folk" in entries[0]["text"] and "devs" in entries[0]["text"]
    assert "gss" in entries[0]["text"] and "stackoverflow" in entries[0]["text"]


@real_corpus
def test_text_sources_would_add_to_parents():
    from simcore.ports.matrix import load_matrix

    matrix = load_matrix(HfCoresetSource(cache_dir=REAL_CACHE))
    assert matrix is not None
    [got] = preview_audiences(
        matrix, ("stackoverflow", "gss"), (),
        [{"name": "parents", "share": 0.5, "filters": {"life_stage": ["Parent of young kids"]}}], 200,
    )
    assert got.text_would_add["amazon"] > 0
    assert got.text_would_add["wiki"] > 0
