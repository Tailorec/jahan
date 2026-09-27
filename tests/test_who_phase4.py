"""Phase 4: editing filters by picking values."""

from pathlib import Path

import pytest

from simcore.population import alternatives, value_counts
from simcore.ports.decoder import Codebook
from simcore.ports.hf import HfCoresetSource
from simcore.ports.matrix import build_matrix
from tests.boundary.ports.test_index_catalog import fake_cache
from tests.real_corpus import REAL_CACHE, real_corpus

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
    # Sharing the category "Demographic: Core" is not asking the same question: by words, nothing is offered.
    assert alternatives(matrix, codebook, ("gss", "stackoverflow"), "demo_children_count") == []
    import numpy as np

    ids = list(matrix.attributes)
    order = {a: i for i, a in enumerate(("demo_children_count", "demo_parental_status", "region"))}
    vectors = np.array([[1.0, 0.0], [0.9, 0.44], [0.0, 1.0]], dtype=np.float32)[[order[a] for a in ids]]
    found = alternatives(matrix, codebook, ("gss", "stackoverflow"), "demo_children_count", embeddings={"ids": ids, "vectors": vectors})
    assert found[0]["id"] == "demo_parental_status"
    assert found[0]["n"] == 2
    assert found[0]["by_source"] == {"gss": 1, "stackoverflow": 1}


def test_no_value_can_be_typed_in_the_picker():
    source = (REPO / "frontend" / "app" / "who" / "page.tsx").read_text()
    picker = source[source.index("Tick values"):]
    picker = picker[:picker.index("The corpus also asks this as")]
    assert 'type="checkbox"' in picker
    assert 'type="text"' not in picker
    assert "<textarea" not in picker


def test_alternatives_rank_by_meaning_and_skip_a_shared_wording_template(tmp_path):
    """Word overlap offered Citizenship and Driving status for Parenthood ("status"); neighbours by meaning,
    minus attributes with an identical value list (a template, not the same question), do not."""
    import numpy as np

    from simcore.population._pool import alternatives
    from simcore.ports.decoder import Codebook

    cache = fake_cache(tmp_path)
    matrix = build_matrix(HfCoresetSource(cache_dir=cache))
    codebook = Codebook.from_json(cache / "persona_codes.schema.json")
    ids = list(matrix.attributes)
    vectors = np.eye(len(ids), dtype=np.float32)
    target, twin, near = ids[0], ids[1], ids[2]
    vectors[ids.index(near)] = vectors[ids.index(target)] * 0.9 + 0.1   # closest in meaning
    vectors[ids.index(twin)] = vectors[ids.index(target)]               # even closer, but see below
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    same_values = tuple(codebook.vocabulary(twin)) == tuple(codebook.vocabulary(target))
    got = [a["id"] for a in alternatives(matrix, codebook, tuple(matrix.sources), target, embeddings={"ids": ids, "vectors": vectors})]
    assert near in got[:2]
    assert (twin not in got) == same_values


@real_corpus
def test_parenthood_is_offered_children(tmp_path):
    from simcore.population._pool import alternatives
    from simcore.ports.decoder import Codebook
    from simcore.ports.embeddings import codebook_digest, embed_model, load_embeddings
    from simcore.ports.matrix import load_matrix

    embeddings = load_embeddings(REAL_CACHE, codebook_digest(REAL_CACHE), embed_model())
    if embeddings is None:
        pytest.skip("attribute embeddings are not built on this machine")
    matrix = load_matrix(HfCoresetSource(cache_dir=REAL_CACHE))
    codebook = Codebook.from_json(REAL_CACHE / "persona_codes.schema.json")
    got = alternatives(matrix, codebook, ("stackoverflow", "gss", "prism", "real_human_survey"), "demo_parental_status", embeddings=embeddings)
    assert "demo_children_count" in [a["id"] for a in got]
