"""`HfCoresetSource`: the real shards, behind explicit fetching, digest-verified, and offline-safe."""

import os
from collections import Counter
from pathlib import Path

import pytest

from tests.packed_fixture import MINI_COLUMNS, write_hf_cache

from simcore.ports import CoresetSource
from simcore.ports.hf import (
    HfCoresetSource,
    MissingShard,
    ShardMismatch,
    default_cache_dir,
    derive_source,
    fetch_command,
    tier_for,
)
from simcore.schemas import FieldOrigin

REPO_ROOT = Path(__file__).resolve().parents[3]

CODEBOOK_COLUMNS = [
    {"id": "age_bracket", "values": ["Under 5", "5-12", "13-17", "18-24", "25-34"]},
    {"id": "region", "values": ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]},
    {"id": "sex", "values": ["female", "male"]},
    {"id": "trait_optimism", "values": ["low", "medium", "high"]},
    {"id": "spend_band", "values": ["0_5", "5_10", "10_20", "20_50"]},
    {"id": "coding_days", "values": ["none", "one_to_three", "four_plus"]},
    {"id": "urbanicity", "values": ["rural", "suburban", "urban"]},
    {"id": "employment", "values": ["student", "employed", "unemployed", "retired"]},
]


@pytest.fixture
def fake_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=CODEBOOK_COLUMNS,
        shards={
            "data/shard-a.parquet": [
                {"codes": [3, 0, 0, 0, 0, 0, 0, 0], "source": "wiki", "source_record_id": "Q42", "metadata_json": '{"qid":"Q42","title":"X"}', "grounding": [(0, "direct")]},
                {"codes": [4, 1, 0, 0, 0, 0, 0, 0], "source": "wiki", "source_record_id": "Q43", "metadata_json": '{"qid":"Q43","title":"Y"}', "grounding": [(0, "unsupported")]},
                {"codes": [2, 5, 1, 0, 0, 0, 0, 0], "source": "gss", "source_record_id": "gss-2024-7", "metadata_json": '{"user_id":"gss-2024-7"}', "grounding": []},
                {"codes": [1, 2, 0, 0, 0, 0, 0, 0], "source": "amazon", "source_record_id": "AFTJOXGXMUMEN6", "metadata_json": '{"review_count":9,"user_bucket":"c1","user_id":"AFTJOXGXMUMEN6"}', "grounding": [(1, "summary_inference")]},
            ],
            "data/shard-b.parquet": [
                {"codes": [4, 3, 0, 0, 0, 0, 0, 0], "source": "synthetic", "source_record_id": None, "metadata_json": None},
                {"codes": [3, 2, 1, 2, 0, 1, 2, 3], "source": "stackoverflow", "source_record_id": "stackoverflow_2024_1_1", "metadata_json": '{"user_id":"stackoverflow_2024_1_1","review_count":1}', "grounding": [(0, "direct")]},
            ],
        },
    )
    return cache


def source_for(cache: Path, shards=None) -> HfCoresetSource:
    return HfCoresetSource(cache_dir=cache, shards=shards, codebook=cache / "persona_codes.schema.json")


# --- the offline unit behaviour ---------------------------------------------------------------


def test_the_shard_source_satisfies_the_coreset_protocol(fake_cache):
    assert isinstance(source_for(fake_cache), CoresetSource)


def test_matching_returns_ids_and_rows_decodes_only_those(fake_cache):
    source = source_for(fake_cache)
    ids = source.matching({}, present=["age_bracket", "sex"])
    assert ids and all(":0" in row_id or ":" in row_id for row_id in ids)
    row = next(source.rows(ids[:1]))
    assert row.source in {"wiki", "gss", "amazon", "synthetic", "stackoverflow"}
    assert "age_bracket" in row.values


def test_a_rows_source_is_derived_from_its_identifiers(fake_cache):
    source = source_for(fake_cache)
    ids = source.matching({}, present=[])
    derived = Counter(source._arrays(row_id.rsplit(":", 1)[0]).sources[int(row_id.rsplit(":", 1)[1])] for row_id in ids)
    assert derived == Counter({"wiki": 2, "gss": 1, "amazon": 1, "synthetic": 1, "stackoverflow": 1})


def test_a_field_is_graded_from_its_source_and_assignment_type(fake_cache):
    source = source_for(fake_cache)
    gss_id = _id_where(source, "gss")
    gss_row = next(source.rows([gss_id]))
    # gss carried age_bracket with an empty grounding list: no evidence, still measured.
    assert gss_row.tiers["age_bracket"] is FieldOrigin.MEASURED
    wiki_row = next(source.rows([_id_where(source, "wiki")]))
    assert wiki_row.tiers["age_bracket"] is FieldOrigin.EXTRACTED


def test_a_synthetic_skeleton_grades_as_synthesized(fake_cache):
    source = source_for(fake_cache)
    row = next(source.rows([_id_where(source, "synthetic")]))
    assert all(tier is FieldOrigin.SYNTHESIZED for tier in row.tiers.values())


def _id_where(source, wanted):
    for shard_entry in source._entries.values():
        arrays = source._arrays(Path(str(shard_entry["path"])).stem)
        for index, source_name in enumerate(arrays.sources):
            if str(source_name) == wanted:
                return arrays.row_ids[index]
    raise AssertionError(f"no {wanted!r} row in the fake cache")


def test_an_absent_shard_is_refused_with_the_command_that_fetches_it(fake_cache, tmp_path):
    (fake_cache / "data/shard-b.parquet").unlink()
    source = source_for(fake_cache)
    with pytest.raises(MissingShard, match="hf download"):
        source.matching({}, present=["age_bracket"])


def test_fetch_command_names_the_shard_and_never_runs(tmp_path):
    command = fetch_command("repo/x", "data/persona-1m-0005.parquet", tmp_path)
    assert "hf download repo/x" in command and "data/persona-1m-0005.parquet" in command and "--local-dir" in command


def test_every_cached_file_is_verified_against_the_digest_on_each_use(fake_cache):
    source_for(fake_cache).matching({}, present=["age_bracket"])  # loads and verifies, no error
    target = fake_cache / "data/shard-a.parquet"
    original = target.read_bytes()
    target.write_bytes(original + b"\x00")
    with pytest.raises(ShardMismatch):
        source_for(fake_cache).matching({}, present=["age_bracket"])
    target.write_bytes(original)


def test_the_default_cache_lives_outside_the_repository():
    resolved = default_cache_dir().resolve()
    assert REPO_ROOT not in resolved.parents and resolved != REPO_ROOT


def test_the_adapter_never_reaches_the_network():
    text = (REPO_ROOT / "simcore" / "ports" / "hf.py").read_text()
    for forbidden in ("import requests", "urllib", "httpx", "hf_hub_download", "socket", "subprocess"):
        assert forbidden not in text


@pytest.mark.parametrize(
    ("source", "assignment", "expected"),
    [
        ("gss", "direct", FieldOrigin.MEASURED),
        ("gss", None, FieldOrigin.MEASURED),
        ("stackoverflow", "direct", FieldOrigin.MEASURED),
        ("amazon", "direct", FieldOrigin.EXTRACTED),
        ("wiki", "unsupported", FieldOrigin.EXTRACTED),
        ("amazon", "summary_inference", FieldOrigin.EXTRACTED),
        ("synthetic", "direct", FieldOrigin.SYNTHESIZED),
    ],
)
def test_tier_is_the_source_and_assignment_read_together(source, assignment, expected):
    assert tier_for(source, assignment) is expected


@pytest.mark.parametrize(
    ("record_id", "metadata", "expected"),
    [
        ("Q37340", '{"qid":"Q37340"}', "wiki"),
        ("gss-2024-1", None, "gss"),
        ("stackoverflow_2024_1_1", None, "stackoverflow"),
        ("AFTJOXGXMUMEN6", '{"review_count":9,"user_bucket":"c1"}', "amazon"),
        (None, None, "synthetic"),
        (None, '{"user_id":"user123"}', "prism"),
    ],
)
def test_the_source_of_a_row_is_derived_from_its_identifiers(record_id, metadata, expected):
    assert derive_source(record_id, metadata) == expected


# --- integration against the real shards, skipped when they are absent ------------------------


def _real_cache() -> Path | None:
    candidates = []
    if os.environ.get("CONSUMERSIM_CORESET_CACHE"):
        candidates.append(Path(os.environ["CONSUMERSIM_CORESET_CACHE"]))
    candidates.append(default_cache_dir())
    for cache in candidates:
        if (cache / "manifest.json").is_file() and any((cache / "data").glob("persona-1m-*.parquet")):
            return cache
    return None


REAL = _real_cache()
real_only = pytest.mark.skipif(REAL is None, reason="the corpus shards are not cached locally")


@real_only
@pytest.mark.parametrize("shard", ["0000", "0004", "0005", "0009"])
def test_real_rows_decode_from_each_cached_shard(shard):
    import pyarrow.parquet as pq

    from simcore.ports.decoder import Codebook, decode_row

    codebook = Codebook.from_json(REAL / "persona_codes.schema.json")
    path = REAL / f"data/persona-1m-{shard}.parquet"
    reader = pq.ParquetFile(path)
    batch = next(reader.iter_batches(batch_size=25))
    for record in batch.to_pylist():
        assert derive_source(record["source_record_id"], record["metadata_json"]) == record["source"]
        overrides = [(int(item["field_index"]), str(item["value"])) for item in (record.get("attribute_overrides") or ())]
        values = decode_row(
            codebook,
            record["attributes"],
            record.get("null_bitmap"),
            overrides,
            int(record["populated_attribute_count"]),
            row_id=record["source_record_id"] or "x",
        )
        assert len(values) > 0


@real_only
def test_derived_sources_match_the_manifest_source_counts():
    import json as _json

    import pyarrow.parquet as pq

    manifest = _json.loads((REAL / "manifest.json").read_text())
    derived = Counter()
    for entry in manifest["files"]:
        path = REAL / entry["path"]
        if not path.is_file():
            continue
        table = pq.read_table(path, columns=["source_record_id", "metadata_json"])
        ids = table["source_record_id"].to_pylist()
        metas = table["metadata_json"].to_pylist()
        derived.update(derive_source(ids[i], metas[i]) for i in range(table.num_rows))
    manifest_counts = manifest["sources"]
    # Stack Overflow is the one fully-cached, instrument source; its derived count proves the derivation.
    assert derived["stackoverflow"] == manifest_counts["stackoverflow"]
    for source in ("gss", "prism", "real_human_survey"):
        assert derived[source] == manifest_counts[source]
