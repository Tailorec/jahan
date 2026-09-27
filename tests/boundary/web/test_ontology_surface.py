"""M0: Who you study — what can be studied, bounded by the data.

The step replaced the ontology builder and the intake audience panel: one
page where a description becomes audiences and an ontology version the engine
accepts, with every count read from the corpus.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
ENGINE = Path(__file__).resolve().parents[3] / "simcore" / "population"


def test_codebook_search_with_declared_value_sets():
    text = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    for marker in ("/api/codebook", "values.join", "kids"):
        assert marker in text, f"page lacks {marker!r}"


def test_names_are_checked_as_typed_with_suggestions():
    text = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    for marker in ("Could not find", "/api/draft"):
        assert marker in text, f"page lacks {marker!r}"
    # The check itself is the engine's, and is asserted where it lives: test_ontology.py
    # (the refusal and its suggestions) and test_interface.py (that the reason reaches the browser).
    api = (FRONTEND / "app" / "api" / "ontologies" / "validate" / "route.ts").read_text()
    assert '"/api/ontologies/validate"' in api


def test_scales_come_from_codebook_labels_in_codebook_order():
    launch = (ENGINE / "_launch.py").read_text()
    # A reused category carries its own ordinal scales; the order stays the
    # conditioning set first, as the schema requires.
    assert "ordinal_scales" in launch and "conditioning" in launch
    page = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    assert "ordered" in page and "yes?" in page


def test_saving_makes_a_new_version():
    text = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    for marker in ("Save ontology", "never overwritten", "Ready for a study"):
        assert marker in text, f"page lacks {marker!r}"
    # That a saved version never overwrites one is the engine's rule, asserted in test_ontology.py
    # and, through the interface's own route, in test_interface.py.
    route = (FRONTEND / "app" / "api" / "ontologies" / "route.ts").read_text()
    assert 'engineFetch("/api/ontologies"' in route


def test_draft_without_corpus_cannot_pin():
    text = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    assert "No corpus cached here" in text
    assert "nobody to count" in text


def test_conditioning_set_is_explained_with_its_cost():
    text = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    assert "Candidate pool" in text
    for marker in ("removes", "have every required answer"):
        assert marker in text, f"page lacks {marker!r}"
