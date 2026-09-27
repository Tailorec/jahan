"""Phase 4: editing filters by picking values."""

from pathlib import Path

from simcore.population import alternatives, value_counts
from simcore.ports.decoder import Codebook
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import fake_cache

REPO = Path(__file__).resolve().parents[1]


def test_values_cover_every_value_with_per_source_counts(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    counts = value_counts(matrix, ("gss", "stackoverflow"), (), "sex")
    assert [entry["value"] for entry in counts] == ["female", "male"]
    assert counts[0] == {"value": "female", "n": 1, "by_source": {"gss": 1}}
    assert counts[1]["by_source"] == {"stackoverflow": 2}


def test_values_are_among_the_candidate_pool(tmp_path):
    matrix = build_matrix(HfCoresetSource(cache_dir=fake_cache(tmp_path)))
    counts = value_counts(matrix, ("gss", "stackoverflow"), ("sex",), "urbanicity")
    total = sum(entry["n"] for entry in counts)
    assert total == 3  # the three gss/stackoverflow rows carrying sex, per value and source


def test_also_asks_lists_alternatives_with_head_counts(tmp_path):
    from tests.packed_fixture import write_hf_cache

    cache = tmp_path / "coreset"
    write_hf_cache(
        cache,
        codebook_columns=[
            {"id": "demo_children_count", "label": "Number of children", "category": "Demographic: Core", "values": ["None", "One"]},
            {"id": "demo_parental_status", "label": "Parental status", "category": "Demographic: Core", "values": ["Parent", "Not parent"]},
            {"id": "region", "label": "Region", "category": "Demographic: Core", "values": ["East", "West"]},
        ],
        shards={
            "data/persona-1m-0000.parquet": [
                {"codes": [1, 0, 0], "source": "gss", "source_record_id": "g1", "metadata_json": "{}"},
                {"codes": [0, 1, 1], "source": "stackoverflow", "source_record_id": "s1", "metadata_json": "{}"},
            ],
        },
    )
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    codebook = Codebook.from_json(cache / "persona_codes.schema.json")
    found = alternatives(matrix, codebook, ("gss", "stackoverflow"), "demo_children_count")
    assert [entry["id"] for entry in found] == ["demo_parental_status", "region"]
    assert found[0]["n"] == 2
    assert found[0]["by_source"] == {"gss": 1, "stackoverflow": 1}


def test_no_value_can_be_typed_in_the_picker():
    source = (REPO / "frontend" / "app" / "who" / "page.tsx").read_text()
    picker = source[source.index("Tick values"):]
    picker = picker[:picker.index("The corpus also asks this as")]
    assert 'type="checkbox"' in picker
    assert 'type="text"' not in picker
    assert "<textarea" not in picker
