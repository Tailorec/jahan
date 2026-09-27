"""Phase 6: the ontology builder — what can be studied, bounded by the data.

The codebook's attributes are searchable with their declared value sets, from
the corpus rather than from a copy. An attribute the corpus does not carry is
refused as it is entered, naming what resembles it. Ordinal scales are built
from the codebook's own labels in the codebook's order. Saving produces a new
version and leaves every existing version untouched. A draft authored without
the corpus present cannot be pinned until it validates against one.
"""

import json
from pathlib import Path

import pytest

from simcore.brief._codebook import suggest_attributes, validate_against_codebook
from simcore.ports.decoder import Codebook
from simcore.schemas import CategoryOntology
from simcore.web import create_app

REPO = Path(__file__).resolve().parents[3]


def _corpus_schema() -> Path:
    """The corpus's own schema from the default cache. Nothing here requires
    the dataset: tests that need it skip where no corpus is cached."""
    from simcore.ports.hf import default_cache_dir

    return default_cache_dir() / "persona_codes.schema.json"


def _corpus_present() -> bool:
    from simcore.ports.hf import default_cache_dir

    return (default_cache_dir() / "persona_codes.schema.json").is_file()


needs_corpus = pytest.mark.skipif(not _corpus_present(), reason="no corpus cached here")


def _ontology_payload(**overrides) -> dict:
    base = json.loads((REPO / "ontologies" / "beverage_protein_persona1m" / "1.0.0.json").read_text())
    base.update(overrides)
    return base


@needs_corpus
def test_the_codebook_comes_from_the_corpus():
    codebook = Codebook.from_json(_corpus_schema())
    assert codebook.field_count == 1290
    assert codebook.vocabulary("age_bracket") is not None
    assert codebook.vocabulary("no_such_attribute") is None


@needs_corpus
def test_an_attribute_the_corpus_does_not_carry_is_refused_with_suggestions():
    codebook = Codebook.from_json(_corpus_schema())
    ontology = CategoryOntology.model_validate(_ontology_payload())
    domains = {**dict(ontology.attribute_domains), "agge_bracket": "demographic"}
    ranking = [*ontology.relevance_order, "agge_bracket"]
    try:
        validate_against_codebook(
            CategoryOntology.model_validate({
                **ontology.model_dump(mode="json"),
                "attribute_domains": domains,
                "relevance_order": ranking,
            }),
            codebook,
        )
    except ValueError as exc:
        assert "agge_bracket" in str(exc) and "age_bracket" in str(exc)
    else:
        raise AssertionError("an unknown attribute must be refused")
    assert "age_bracket" in suggest_attributes("agge_bracket", codebook)


@needs_corpus
def test_ordinal_scales_use_the_codebooks_own_labels():
    codebook = Codebook.from_json(_corpus_schema())
    ontology = CategoryOntology.model_validate(_ontology_payload())
    validate_against_codebook(ontology, codebook)  # the shipped ontology passes
    scale = ontology.ordinal_scales[0]
    labels = [band.label for band in scale.bands]
    assert len(labels) >= 2
    invented = ontology.model_copy(update={
        "ordinal_scales": [{**scale.model_dump(mode="json"), "bands": [
            {"label": labels[0], "midpoint": 0.0}, {"label": "not a value", "midpoint": 1.0}]}]
    })
    try:
        validate_against_codebook(CategoryOntology.model_validate(invented.model_dump(mode="json")), codebook)
    except ValueError as exc:
        assert "not a value" in str(exc)
    else:
        raise AssertionError("an invented band must be refused")


def _client(tmp_path: Path, corpus: Path | None):
    from fastapi.testclient import TestClient

    return TestClient(create_app(
        runs_dir=tmp_path / "runs",
        ontology_dir=tmp_path / "ontologies",
        corpus_dir=corpus,
    ))


def _fixture_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "persona_codes.schema.json").write_text(json.dumps({"columns": [
        {"id": "age_bracket", "values": ["18-24", "25-34", "35-44"]},
        {"id": "exercise_frequency", "values": ["never", "weekly", "daily"]},
        {"id": "protein_habit", "values": ["low", "high"]},
    ]}))
    return corpus


def test_codebook_search_serves_declared_value_sets(tmp_path):
    client = _client(tmp_path, _fixture_corpus(tmp_path))
    body = client.get("/api/codebook", params={"query": "age"}).json()
    assert body["total"] == 1
    assert body["attributes"][0]["id"] == "age_bracket"
    assert body["attributes"][0]["values"] == ["18-24", "25-34", "35-44"]
    assert "label" in body["attributes"][0] and "measures" in body["attributes"][0]
    assert client.get("/api/codebook", params={"query": "nope"}).json()["attributes"] == []


def test_nothing_pins_without_the_corpus_present(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    client = _client(tmp_path, tmp_path / "no-corpus")
    assert client.get("/api/codebook").status_code == 409
    response = client.post("/api/ontologies/validate", json={"ontology": _ontology_payload()})
    assert response.status_code == 409


def test_saving_creates_a_new_version_and_leaves_the_old_one(tmp_path):
    corpus = _fixture_corpus(tmp_path)
    ontology_dir = tmp_path / "ontologies"
    category_dir = ontology_dir / "snacks"
    category_dir.mkdir(parents=True)
    first = {
        "category": "snacks", "version": "1.0.0",
        "attribute_domains": {"age_bracket": "demographic", "protein_habit": "psychographic"},
        "conditioning_set": ["age_bracket"],
        "relevance_order": ["age_bracket", "protein_habit"],
        "completion_policy": {"completable_domains": []},
        "ordinal_scales": [{"attribute": "age_bracket", "bands": [
            {"label": "18-24", "midpoint": 21.0}, {"label": "25-34", "midpoint": 29.5}]}],
        "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
    }
    client = _client(tmp_path, corpus)
    assert client.post("/api/ontologies", json={"ontology": first}).status_code == 201
    before = (category_dir / "1.0.0.json").read_bytes()
    # An unknown attribute is refused as it is entered, naming what resembles it.
    bad = json.loads(json.dumps(first).replace("protein_habit", "protein_habbit"))
    refused = client.post("/api/ontologies", json={"ontology": bad})
    assert refused.status_code == 422 and "protein_habit" in refused.json()["detail"]
    # Saving the same version again refuses; a new version lands beside the old.
    assert client.post("/api/ontologies", json={"ontology": first}).status_code == 409
    second = {**first, "version": "1.1.0"}
    assert client.post("/api/ontologies", json={"ontology": second}).status_code == 201
    assert (category_dir / "1.0.0.json").read_bytes() == before
    assert {path.name for path in category_dir.iterdir()} == {"1.0.0.json", "1.1.0.json"}


def test_a_study_names_the_version_it_ran_on(tmp_path, monkeypatch):
    """The run directory carries the ontology version the study ran on."""
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "77"
    code, output = run_command(*fake_args(out, run_id))
    assert code == 0, output
    stored = json.loads((out / run_id / "ontology.json").read_text())
    shipped = json.loads((REPO / "ontologies" / "beverage_protein" / "1.0.0.json").read_text())
    assert stored["category"] == shipped["category"] and stored["version"] == shipped["version"]
    assert set(stored["conditioning_set"]) == set(shipped["conditioning_set"])
