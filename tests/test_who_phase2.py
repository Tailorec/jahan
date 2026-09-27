"""Phase 2: the candidate pool, and what each requirement costs."""

import json

import numpy as np

from simcore.population import describe_pool
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import MISSING, build_matrix, load_matrix
from tests.boundary.ports.test_index_catalog import ATTRIBUTES, COLUMNS, fake_cache
from tests.real_corpus import REAL_CACHE, real_corpus


def test_matrix_agrees_with_the_adapter_field_by_field(tmp_path):
    cache = fake_cache(tmp_path)
    source = HfCoresetSource(cache_dir=cache)
    matrix = build_matrix(source)
    assert set(matrix.attributes) == set(ATTRIBUTES)
    # Synthetic rows are left out, as a study leaves them out.
    assert "synthetic" not in matrix.sources
    assert sum(matrix.totals.values()) == 4
    fresh = HfCoresetSource(cache_dir=cache)
    for entry in fresh._entries.values():
        from pathlib import Path

        arrays = fresh._arrays(Path(str(entry["path"])).stem)
        shard_sources = np.asarray(arrays.sources, dtype=object)
        for attribute in ATTRIBUTES:
            labels = fresh.labels(arrays, attribute)
            vocabulary = fresh.values(attribute)
            for position, (label, name) in enumerate(zip(labels, shard_sources)):
                if name == "synthetic":
                    continue
                rows = np.nonzero(matrix.row_source == matrix.sources.index(name))[0]
                assert len(rows), f"no matrix rows for {name}"
                code = matrix.codes[ATTRIBUTES.index(attribute)]
                if label is None:
                    assert (code[rows] == MISSING).any()
                else:
                    assert vocabulary[code[rows[0]]] == label or label in vocabulary


def test_matrix_presence_matches_the_adapter_exactly(tmp_path):
    cache = fake_cache(tmp_path)
    source = HfCoresetSource(cache_dir=cache)
    matrix = build_matrix(source)
    fresh = HfCoresetSource(cache_dir=cache)
    for attribute in ATTRIBUTES:
        present = matrix.codes[ATTRIBUTES.index(attribute)] != MISSING
        # `matching` scans every row including synthetic ones the matrix leaves out.
        assert int(present.sum()) + 1 == len(fresh.matching({}, present=[attribute]))


def test_a_changed_shard_rebuilds_rather_than_answering_stale(tmp_path):
    cache = fake_cache(tmp_path)
    source = HfCoresetSource(cache_dir=cache)
    assert load_matrix(source) is None
    build_matrix(source)
    assert load_matrix(HfCoresetSource(cache_dir=cache)) is not None
    manifest = cache / "manifest.json"
    body = json.loads(manifest.read_text())
    body["files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(body))
    assert load_matrix(HfCoresetSource(cache_dir=cache)) is None


def test_each_cost_is_per_source_and_emptied_surveys_are_named(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[
            {"id": "a", "values": ["x", "y"]},
            {"id": "b", "values": ["x", "y"]},
        ],
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [0, 1], "source": "gss", "source_record_id": "g1", "metadata_json": "{}"},
                {"codes": [1, 0], "source": "stackoverflow", "source_record_id": "s1", "metadata_json": "{}", "missing": [1]},
            ],
        },
    )
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    pool = describe_pool(matrix, ("gss", "stackoverflow"), ("a", "b"))
    assert pool.pool == 1
    assert pool.pool_by_source == {"gss": 1}
    by_name = {cost.attribute: cost for cost in pool.costs}
    assert by_name["b"].removes == 1
    assert by_name["b"].removes_by_source == {"stackoverflow": 1}
    assert by_name["b"].emptied_sources == ("stackoverflow",)


def test_unknown_attributes_and_sources_are_refused(tmp_path):
    import pytest

    cache = fake_cache(tmp_path)
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    with pytest.raises(ValueError, match="no such attribute"):
        describe_pool(matrix, ("gss",), ("nope",))
    with pytest.raises(ValueError, match="no such source"):
        describe_pool(matrix, ("nope",), ("sex",))
