"""Phase 6: the ontology builder — what can be studied, bounded by the data."""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_codebook_search_with_declared_value_sets():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    for marker in ("/api/codebook", "values.join", "1,290 attributes"):
        assert marker in text, f"builder lacks {marker!r}"


def test_names_are_checked_as_typed_with_suggestions():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    for marker in ("/api/ontologies/validate", "Refused", "did you mean"):
        assert marker in text or "resembl" in text, f"builder lacks {marker!r}"
    api = (FRONTEND / "app" / "api" / "ontologies" / "validate" / "route.ts").read_text()
    assert "ontology" in api and ("ontology" in api and "check" in api)


def test_scales_come_from_codebook_labels_in_codebook_order():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    assert "codebook labels in codebook order" in text
    assert "bands" in text and "midpoint" in text


def test_saving_makes_a_new_version():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    for marker in ("Save new version", "never overwritten", "Load existing to edit"):
        assert marker in text, f"builder lacks {marker!r}"
    route = (FRONTEND / "app" / "api" / "ontologies" / "route.ts").read_text()
    assert "already exists: save as a new version" in route


def test_draft_without_corpus_cannot_pin():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    assert "No corpus cached here" in text
    assert "cannot be pinned until it validates" in text or "pinning needs the corpus" in text


def test_conditioning_set_is_explained_with_its_cost():
    text = (FRONTEND / "app" / "ontology" / "page.tsx").read_text()
    assert "The conditioning set" in text
    for marker in ("differ from one another", "fifty-seven", "costs the study its population"):
        assert marker in text, f"builder lacks {marker!r}"
