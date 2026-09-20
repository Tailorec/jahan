"""Coverage: how populated each attribute is, per source, counted once and saved beside the release."""

from pathlib import Path

from simcore.ports.coverage import count_coverage, coverage_table, load_coverage
from simcore.ports.hf import HfCoresetSource
from tests.boundary.ports.test_index_catalog import ATTRIBUTES, fake_cache  # noqa: F401  (a fixture's home)


def _source(cache: Path) -> HfCoresetSource:
    return HfCoresetSource(cache_dir=cache)


def test_presence_is_counted_per_attribute_and_per_source(tmp_path):
    cache = fake_cache(tmp_path)
    saved = count_coverage(_source(cache))
    assert saved["totals"] == {"gss": 1, "stackoverflow": 2, "synthetic": 1, "wiki": 1}
    # Every fixture row carries every field, so each attribute is present in every row of its source.
    assert saved["present"]["age_bracket"] == {"gss": 1, "stackoverflow": 2, "synthetic": 1, "wiki": 1}
    assert set(saved["present"]) == set(ATTRIBUTES)


def test_the_recorded_pool_leaves_synthetic_rows_out_and_says_the_share_itself(tmp_path):
    cache = fake_cache(tmp_path)
    table = coverage_table(count_coverage(_source(cache)))
    recorded = table["age_bracket"]["recorded"]
    assert recorded == {"present": 4, "total": 4, "share": 1.0}
    assert set(table["age_bracket"]["by_source"]) == {"gss", "stackoverflow", "wiki"}
    assert table["age_bracket"]["by_source"]["stackoverflow"] == {"present": 2, "total": 2, "share": 1.0}


def test_a_field_a_source_leaves_blank_is_counted_as_absent(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[{"id": "a", "values": ["x", "y"]}, {"id": "b", "values": ["x", "y"]}],
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [0, 1], "source": "gss", "source_record_id": "g1", "metadata_json": "{}", "missing": [1]},
                {"codes": [1, 0], "source": "gss", "source_record_id": "g2", "metadata_json": "{}"},
            ],
        },
    )
    table = coverage_table(count_coverage(_source(cache)))
    assert table["a"]["recorded"]["share"] == 1.0
    assert table["b"]["recorded"] == {"present": 1, "total": 2, "share": 0.5}


def test_a_saved_count_is_reused_and_a_changed_release_recounts(tmp_path):
    cache = fake_cache(tmp_path)
    source = _source(cache)
    assert load_coverage(source) is None
    saved = count_coverage(source)
    assert load_coverage(_source(cache)) == saved

    shard = cache / "data" / "persona-1m-0000.parquet"
    shard.write_bytes(shard.read_bytes() + b"x")
    manifest = cache / "manifest.json"
    import json

    body = json.loads(manifest.read_text())
    for entry in body["files"]:
        if entry["path"] == "data/persona-1m-0000.parquet":
            entry["sha256"] = "0" * 64
    manifest.write_text(json.dumps(body))
    assert load_coverage(_source(cache)) is None


def test_counting_does_not_keep_every_attributes_labels(tmp_path):
    cache = fake_cache(tmp_path)
    source = _source(cache)
    count_coverage(source)
    assert source._cache == {}, "a shard's decoded labels were kept, which at full width holds a gigabyte each"
