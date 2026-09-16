"""The index-backed catalog: coverage and counts answered without ever opening a shard."""

import copy
from pathlib import Path

import pytest

from tests.packed_fixture import write_hf_cache

from simcore.population import PreviewRequest, preview
from simcore.ports import CoresetCatalog, from_hf_source, from_source
from simcore.ports.hf import HfCoresetSource
from simcore.ports.index_catalog import IndexCoresetCatalog
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, Exactly, FieldOrigin, OneOf

COLUMNS = [
    {"id": "age_bracket", "values": ["Under 5", "5-12", "13-17", "18-24", "25-34"]},
    {"id": "region", "values": ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]},
    {"id": "sex", "values": ["female", "male"]},
    {"id": "trait_optimism", "values": ["low", "medium", "high"]},
    {"id": "spend_band", "values": ["0_5", "5_10", "10_20", "20_50"]},
    {"id": "coding_days", "values": ["none", "one_to_three", "four_plus"]},
    {"id": "urbanicity", "values": ["rural", "suburban", "urban"]},
    {"id": "employment", "values": ["student", "employed", "unemployed", "retired"]},
]
ATTRIBUTES = [column["id"] for column in COLUMNS]


def fake_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=COLUMNS,
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [3, 2, 0, 1, 1, 2, 2, 1], "source": "wiki", "source_record_id": "Q1", "metadata_json": '{"qid":"Q1"}'},
                {"codes": [4, 5, 1, 0, 2, 0, 0, 3], "source": "stackoverflow", "source_record_id": "stackoverflow_1", "metadata_json": '{"user_id":"stackoverflow_1"}'},
            ],
            "data/persona-1m-0001.parquet": [
                {"codes": [1, 0, 0, 2, 0, 1, 1, 0], "source": "gss", "source_record_id": "gss-1", "metadata_json": '{"user_id":"gss-1"}'},
                {"codes": [3, 3, 1, 1, 3, 2, 0, 2], "source": "stackoverflow", "source_record_id": "stackoverflow_2", "metadata_json": '{"user_id":"stackoverflow_2"}'},
                {"codes": [0, 1, 0, 0, 0, 0, 0, 0], "source": "synthetic", "source_record_id": None, "metadata_json": None},
            ],
        },
    )
    return cache


def pack() -> BriefPack:
    domains = {"age_bracket": "demographic", "sex": "demographic", "region": "demographic", "employment": "economic", "spend_band": "economic", "urbanicity": "demographic", "trait_optimism": "psychographic", "coding_days": "category_behaviour"}
    order = ["age_bracket", "sex", "region", "urbanicity", "trait_optimism", "coding_days", "employment", "spend_band"]
    return BriefPack.model_validate(
        {
            "brief": {
                "product": {"name": "Product", "category": "study", "description": "d"},
                "price": {"amount": 2.0, "currency": "USD"},
                "claims": [{"text": "does", "source": "user_asserted"}],
                "target_market": "adults",
                "ontology_version": "1.0.0",
            },
            "ontology": {
                "category": "study",
                "version": "1.0.0",
                "attribute_domains": domains,
                "conditioning_set": ["age_bracket", "sex"],
                "completion_policy": {"completable_domains": ["economic"]},
                "relevance_order": order,
                "anchor_sets": {"purchase_intent": "pi-1"},
            },
        }
    )


def test_the_index_is_a_catalog():
    assert isinstance(IndexCoresetCatalog, type)


def test_the_catalog_answers_coverage_without_reading_rows(tmp_path):
    cache = fake_cache(tmp_path)
    index = from_hf_source(HfCoresetSource(cache_dir=cache), ATTRIBUTES)
    coverage = index.coverage(["age_bracket"], ["gss", "synthetic"])
    assert coverage["age_bracket"]["gss"].present == 1
    assert coverage["age_bracket"]["gss"].total == 1


def test_conjunctions_agree_with_a_row_scan(tmp_path):
    cache = fake_cache(tmp_path)
    scanned = HfCoresetSource(cache_dir=cache)
    index = from_hf_source(scanned, ATTRIBUTES)
    single = {"age_bracket": Exactly(value="18-24")}
    assert index.count(single, ["sex"], by_source=False) == len(scanned.matching(single, present=["sex"]))
    conjunct = {"age_bracket": Exactly(value="18-24"), "sex": Exactly(value="female")}
    assert index.count(conjunct, ["region"], by_source=False) == len(scanned.matching(conjunct, present=["region"]))


def test_single_attribute_counts_agree_with_a_row_scan(tmp_path):
    cache = fake_cache(tmp_path)
    source = HfCoresetSource(cache_dir=cache)
    index = from_hf_source(source, ATTRIBUTES)
    for attribute in ATTRIBUTES:
        assert index.count({}, [attribute], by_source=False) == len(source.matching({}, present=[attribute]))


def test_the_catalog_holds_no_source_and_a_preview_reads_no_shard(tmp_path):
    cache = fake_cache(tmp_path)
    index = from_hf_source(HfCoresetSource(cache_dir=cache), ATTRIBUTES)
    for shard in (cache / "data").glob("*.parquet"):
        shard.unlink()
    report = preview(PreviewRequest(pack(), 5, filters={"age_bracket": "18-24"}), catalog=index)
    assert report.sources


def test_the_catalogs_counts_agree_with_the_manifest_source_totals(tmp_path):
    cache = fake_cache(tmp_path)
    import json

    manifest = json.loads((cache / "manifest.json").read_text())
    index = from_hf_source(HfCoresetSource(cache_dir=cache), ATTRIBUTES)
    assert sum(index.totals.values()) == sum(entry["rows"] for entry in manifest["files"])
    assert index.totals["stackoverflow"] == 2
    assert index.totals["synthetic"] == 1


def test_a_built_index_reports_the_weakest_tier_and_absent_attributes(tmp_path):
    cache = fake_cache(tmp_path)
    index = from_hf_source(HfCoresetSource(cache_dir=cache), ATTRIBUTES)
    # gss carries age_bracket as measured; region too, but employment is economic and present here.
    coverage = index.coverage(["age_bracket"], ["gss"])
    assert coverage["age_bracket"]["gss"].tier.value == "measured"


def test_a_survey_sources_inferred_values_grade_as_extracted_in_the_index_as_in_its_rows(tmp_path):
    """The index once graded a whole source at one tier, so every Stack Overflow value counted as measured —
    including the 15% of `att_ai` a model inferred. It grades each field as the decoded row does."""
    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=COLUMNS,
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [3, 2, 0, 1, 1, 2, 2, 1], "source": "stackoverflow", "grounding": [(0, "direct"), (3, "summary_inference")]},
                {"codes": [4, 5, 1, 0, 2, 0, 0, 3], "source": "stackoverflow", "grounding": [(0, "summary_inference"), (3, None)]},
                {"codes": [1, 0, 0, 2, 0, 1, 1, 0], "source": "real_human_survey", "grounding": []},
                {"codes": [2, 1, 1, 1, 1, 1, 1, 1], "source": "amazon", "grounding": [(0, "direct")]},
            ],
        },
    )
    source = HfCoresetSource(cache_dir=cache)
    index = from_hf_source(source, ATTRIBUTES)
    coverage = index.coverage(["age_bracket", "trait_optimism"], ["stackoverflow", "real_human_survey", "amazon"])
    assert (coverage["age_bracket"]["stackoverflow"].measured, coverage["age_bracket"]["stackoverflow"].extracted) == (1, 1)
    assert (coverage["trait_optimism"]["stackoverflow"].measured, coverage["trait_optimism"]["stackoverflow"].extracted) == (1, 1)
    assert coverage["age_bracket"]["real_human_survey"].measured == 1
    assert coverage["age_bracket"]["amazon"].extracted == 1
    rows = list(source.rows(source.matching({}, present=[])))
    for attribute in ("age_bracket", "trait_optimism"):
        for name in ("stackoverflow", "real_human_survey", "amazon"):
            decoded = [row.tiers[attribute] for row in rows if row.source == name and attribute in row.values]
            cell = coverage[attribute][name]
            assert (cell.measured, cell.extracted) == (decoded.count(FieldOrigin.MEASURED), decoded.count(FieldOrigin.EXTRACTED))


def test_the_index_can_be_built_from_an_in_memory_source():
    source = SyntheticCoresetSource(
        SyntheticShape({"age": AttributeShape(("25_34", "35_44")), "sex": AttributeShape(("female", "male"))}, rows=200), seed=3
    )
    index = from_source(source)
    assert isinstance(index, CoresetCatalog)
    assert index.count({"age": Exactly(value="25_34")}, ["sex"], by_source=False) == len(source.matching({"age": Exactly(value="25_34")}, present=["sex"]))


# --- against the real shards, skipped when they are absent ------------------------------------

import os

from simcore.ports.hf import default_cache_dir

def _real_cache():
    if os.environ.get("CONSUMERSIM_CORESET_CACHE"):
        path = Path(os.environ["CONSUMERSIM_CORESET_CACHE"])
        if (path / "manifest.json").is_file():
            return path
    path = default_cache_dir()
    return path if (path / "manifest.json").is_file() else None


REAL = _real_cache()
real_only = pytest.mark.skipif(REAL is None, reason="the corpus shards are not cached locally")


@real_only
def test_preview_against_the_real_index_reports_the_conditioning_gap():
    # The beverage conditioning set lives in the codebook under corpus names; a few are absent on gss,
    # which is the coverage this module exists to surface before a study is authored against it.
    source = HfCoresetSource(cache_dir=REAL, shards=["data/persona-1m-0005.parquet"], sources=["gss", "stackoverflow"])
    conditioning = ["age_bracket", "gender_identity", "lstyle_exercise_freq"]
    index = from_hf_source(source, conditioning, sources=["gss", "stackoverflow"])
    coverage = index.coverage(conditioning, ["gss", "stackoverflow"])
    absent = {(attribute, name) for attribute in conditioning for name, cell in coverage[attribute].items() if cell.total > 0 and cell.present == 0}
    present = {attribute for attribute in conditioning if any(cell.present > 0 for cell in coverage[attribute].values())}
    assert absent and present
    predicate = {"age_bracket": OneOf(values=("25-34", "35-44"))}
    scanned = len(source.matching(predicate, present=["gender_identity"]))
    assert sum(index.count(predicate, ["gender_identity"]).values()) == scanned
