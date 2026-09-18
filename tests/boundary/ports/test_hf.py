"""`HfCoresetSource`: the real shards, behind explicit fetching, digest-verified, and offline-safe."""

from collections import Counter
from pathlib import Path

import pytest

from tests.packed_fixture import MINI_COLUMNS, write_hf_cache
from tests.real_corpus import REAL_CACHE, real_corpus

from simcore.ports import CoresetSource
from simcore.ports.hf import (
    HfCoresetSource,
    MissingShard,
    ShardMismatch,
    default_cache_dir,
    fetch_command,
    tier_for,
)
from simcore.schemas import BandRange, Exactly, FieldOrigin, OneOf

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
        ("stackoverflow", "structured_claim", FieldOrigin.MEASURED),
        # A survey source's inferred value is a model's reading, not an answer.
        ("stackoverflow", "summary_inference", FieldOrigin.EXTRACTED),
        ("prism", "direct", FieldOrigin.MEASURED),
        ("prism", "unsupported", FieldOrigin.EXTRACTED),
        ("real_human_survey", None, FieldOrigin.MEASURED),
        ("amazon", "direct", FieldOrigin.EXTRACTED),
        ("wiki", "unsupported", FieldOrigin.EXTRACTED),
        ("amazon", "summary_inference", FieldOrigin.EXTRACTED),
        ("synthetic", "direct", FieldOrigin.SYNTHESIZED),
        # A source the adapter does not know never earns a measured claim by default.
        ("some_new_panel", "direct", FieldOrigin.EXTRACTED),
    ],
)
def test_tier_is_the_source_and_assignment_read_together(source, assignment, expected):
    assert tier_for(source, assignment) is expected


def test_a_rows_source_is_the_releases_own_column_not_a_guess_from_its_identifiers(tmp_path):
    """The source was once inferred from the shape of identifiers, on the mistaken belief that the release
    did not record it; an identifier the guess did not recognise fell through to a measured survey source."""
    cache = tmp_path / "cache"
    write_hf_cache(
        cache,
        codebook_columns=CODEBOOK_COLUMNS,
        shards={"data/persona-1m-0000.parquet": [
            {"codes": [3, 0, 0, 0, 0, 0, 0, 0], "source": "amazon", "source_record_id": "gss-looks-like-a-survey", "metadata_json": '{"user_id":"gss-1"}'},
        ]},
    )
    (row,) = HfCoresetSource(cache_dir=cache).rows(["persona-1m-0000:0"])
    assert row.source == "amazon"


# --- integration against the real shards, skipped when they are absent ------------------------


REAL = REAL_CACHE
real_only = real_corpus


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
def test_the_adapters_source_counts_match_the_manifest():
    """The survey sources all live in shards 0004 and 0005, so the adapter's counts over those two shards
    must reproduce the manifest's totals exactly — read through the adapter, not from the parquet."""
    import json as _json

    manifest = _json.loads((REAL / "manifest.json").read_text())
    shards = [f"data/persona-1m-{n}.parquet" for n in ("0004", "0005")]
    if not all((REAL / shard).is_file() for shard in shards):
        pytest.skip("shards 0004 and 0005 are not both cached")
    counts = HfCoresetSource(cache_dir=REAL, shards=shards).count({}, [], by_source=True)
    for source in ("stackoverflow", "gss", "prism", "real_human_survey"):
        assert counts[source] == manifest["sources"][source]


@pytest.mark.parametrize(
    "predicates",
    [{}, {"age_bracket": OneOf(values=("18-24", "25-34"))}, {"age_bracket": BandRange(first="13-17", last="25-34"), "region": Exactly(value="Europe")}],
)
def test_counts_by_source_agree_with_reading_the_matched_rows(fake_cache, predicates):
    """Counting by source once revisited every matched row one slice at a time — 3.4s against 0.01s on one
    real shard. It now counts from the shard masks, and must agree with a row-by-row reading."""
    source = source_for(fake_cache)
    rows = list(source.rows(source.matching(predicates, present=["age_bracket"])))
    assert source.count(predicates, ["age_bracket"], by_source=True) == dict(Counter(row.source for row in rows))
    assert source.count(predicates, ["age_bracket"], by_source=False) == len(rows)


def _grounding_chunks(rows_per_chunk):
    """A grounding column in several chunks, as a parquet reader hands back a large shard."""
    import pyarrow as pa

    kind = pa.list_(pa.struct([("field_index", pa.int32()), ("assignment_type", pa.string())]))
    return pa.chunked_array([pa.array(rows, type=kind) for rows in rows_per_chunk], type=kind)


def test_inferred_rows_are_numbered_across_chunks():
    """Each chunk numbers its rows from zero; the shard numbers them from the start of the shard."""
    from simcore.ports.hf import _inferred_rows

    column = _grounding_chunks([
        [[{"field_index": 3, "assignment_type": "inferred"}], [{"field_index": 3, "assignment_type": "direct"}]],
        [[{"field_index": 3, "assignment_type": "inferred"}]],
    ])
    assert {field: sorted(int(row) for row in rows) for field, rows in _inferred_rows(column).items()} == {3: [0, 2]}


class _Unjoinable:
    """A chunked column whose chunks cannot be concatenated, as Arrow refuses past 2 GB."""

    def __init__(self, column):
        self._column = column
        self.chunks = list(column.chunks)

    def __len__(self):
        return len(self._column)

    def combine_chunks(self):
        import pyarrow as pa

        raise pa.lib.ArrowInvalid("offset overflow while concatenating arrays")


def test_a_shard_too_large_to_combine_is_still_read():
    """`grounding` on the release's largest shard holds more than two gigabytes of child data, and
    combining its chunks into one array overflows Arrow's 32-bit string offsets: the first real
    population draw died with `ArrowInvalid: offset overflow while concatenating arrays`. The
    fixtures are small, and the real-corpus tests read the first 25 rows of a batch, so nothing
    ever combined a whole shard's column."""
    from simcore.ports.hf import _inferred_rows

    column = _Unjoinable(_grounding_chunks([
        [[{"field_index": 1, "assignment_type": "inferred"}]],
        [[{"field_index": 1, "assignment_type": "direct"}], [{"field_index": 2, "assignment_type": "inferred"}]],
    ]))
    assert {field: sorted(int(row) for row in rows) for field, rows in _inferred_rows(column).items()} == {1: [0], 2: [2]}


def test_a_loaded_shard_does_not_retain_the_parquet_table(fake_cache):
    """A shard was kept as the whole Arrow table so single rows could be sliced out of it lazily.
    The release's largest shard holds over two gigabytes in its `grounding` column alone, and a
    draw loads every shard it may match against at once: a 200-persona draw over four cached
    shards took a 16 GB machine into swap and froze it. Nothing but the packed arrays is kept."""
    import pyarrow as pa

    source = source_for(fake_cache)
    ids = source.matching({}, present=[])
    arrays = source._arrays(ids[0].rsplit(":", 1)[0])
    held = [name for name, value in vars(arrays).items() if isinstance(value, (pa.Table, pa.ChunkedArray))]
    assert held == [], f"the shard still holds {held}"


def test_rows_decode_the_same_without_the_table(fake_cache):
    """What the decode returns is unchanged: the same values, the same tiers, the same sources."""
    source = source_for(fake_cache)
    ids = source.matching({}, present=[])
    decoded = {row.row_id: row for row in source.rows(ids)}
    assert decoded
    for row in decoded.values():
        assert row.values
        assert set(row.tiers) == set(row.values)


def test_only_the_grounding_leaves_a_tier_depends_on_are_read():
    """`grounding` carries an `evidence` text three gigabytes wide on the release's largest shard,
    and a tier depends on two small leaves of it. Reading the column whole is what took a draw
    past the memory of the machine it ran on."""
    source_text = (REPO_ROOT / "simcore" / "ports" / "hf.py").read_text()
    assert '"grounding.list.element.field_index"' in source_text
    assert '"grounding.list.element.assignment_type"' in source_text
    assert '\n            "grounding",' not in source_text, "the whole grounding column is read again"


def test_an_attribute_the_corpus_does_not_carry_is_refused_by_name(fake_cache):
    """A study names the attributes it conditions and filters on, and nothing checked them against
    the codebook: the first real draw died with `KeyError: 'age'` from inside a numpy mask, after
    reading four shards. The corpus carries `age_bracket`, and saying so is the whole job."""
    from simcore.schemas import GateFailure

    source = source_for(fake_cache)
    with pytest.raises(GateFailure, match="age_brackets_typo"):
        source.matching({}, present=["age_brackets_typo"])
    with pytest.raises(GateFailure, match="nonesuch"):
        source.matching({"nonesuch": Exactly(value="x")}, present=[])


def test_a_refusal_suggests_the_names_the_codebook_does_have(fake_cache):
    from simcore.schemas import GateFailure

    source = source_for(fake_cache)
    with pytest.raises(GateFailure) as raised:
        source.matching({}, present=["age"])
    assert "age_bracket" in str(raised.value)


def test_membership_of_an_inferred_row_costs_no_memory():
    """A field can be inferred on most of a shard's hundred thousand rows, and a shard carries
    1,290 fields. Answering "was this row's field inferred?" by building a set of row numbers per
    field is how the second real draw died — `MemoryError`, inside the decode of one persona."""
    import numpy as np

    from simcore.ports.hf import _ShardArrays

    rows = np.arange(0, 200_000, 2, dtype=np.int64)
    arrays = _ShardArrays(
        row_ids=(), attributes=np.zeros((1, 1), dtype=np.uint8), bitmap=None,
        vocabulary_sizes=np.zeros(1, dtype=np.int16), sources=np.empty(0, dtype=object),
        counts=np.zeros(1, dtype=np.int32), overrides={}, inferred={3: rows},
    )
    assert arrays.inferred_at(3, 0) is True
    assert arrays.inferred_at(3, 4) is True
    assert arrays.inferred_at(3, 5) is False
    assert arrays.inferred_at(3, 199_998) is True
    assert arrays.inferred_at(3, 200_000) is False
    assert arrays.inferred_at(7, 4) is False
    assert not any(isinstance(value, (set, dict)) and value for name, value in vars(arrays).items()
                   if name.startswith("_")), "a per-field index of rows was materialised"
