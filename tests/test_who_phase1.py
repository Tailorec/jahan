"""Phase 1: the codebook in plain words — labels, categories, measures, word search."""

from pathlib import Path

from simcore.brief._codebook import kind_of, measures_of, word_search
from simcore.ports.decoder import Codebook
from tests.real_corpus import REAL_CACHE, real_corpus

REPO = Path(__file__).resolve().parents[1]


class _Stub:
    def __init__(self, columns):
        self._columns = columns
        self.attributes = tuple(c["id"] for c in columns)

    def vocabulary(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return tuple(c["values"])
        return None

    def label(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return c.get("label") or attribute
        return attribute

    def category(self, attribute):
        for c in self._columns:
            if c["id"] == attribute:
                return c.get("category") or ""
        return ""


def test_word_search_covers_labels_and_categories():
    codebook = _Stub([
        {"id": "demo_children_count", "label": "Number of children", "category": "Demographic: Core", "values": ["None", "One", "Two"]},
        {"id": "demo_household_income", "label": "Household income band", "category": "Demographic: Money & work", "values": ["Low", "High"]},
        {"id": "socioeconomic_band", "label": "Socioeconomic band", "category": "Demographic: Wealth", "values": ["Low", "High income"]},
        {"id": "att_ev", "label": "Attitude to electric vehicles", "category": "Interests: Transport", "values": ["Likes", "Dislikes"]},
    ])
    assert "demo_children_count" in word_search("kids", codebook)
    assert "demo_household_income" in word_search("money", codebook)
    assert "socioeconomic_band" in word_search("wealthy", codebook)


def test_measures_marks_feelings_not_doings():
    assert measures_of("att_ev", "Attitude to electric vehicles", "Interests") == "how people feel rather than what they do"
    assert "feel" in measures_of("val_community", "Value: Community", "Values & Motivation")
    assert "feel" in measures_of("topic_health", "Interest: Fitness", "Interests")
    assert measures_of("age_bracket", "Age bracket", "Demographic: Core") == "a fact about the person"


def test_kind_in_plain_words():
    assert kind_of("age_bracket", "Age bracket", "Demographic: Core") == "Who they are"
    assert kind_of("demo_household_income", "Household income", "Demographic: Money") == "Money & work"


def test_interface_uses_glossary_words():
    source = (REPO / "frontend" / "lib" / "coverage.ts").read_text()
    assert "dense" not in source and "sparse" not in source
    for page in ["frontend/app/ontology/page.tsx", "frontend/app/who/page.tsx"]:
        text = (REPO / page).read_text()
        assert "dense" not in text and "sparse" not in text


def test_who_page_is_step_zero():
    shell = (REPO / "frontend" / "components" / "shell.tsx").read_text()
    assert '"/who"' in shell
    assert (REPO / "frontend" / "app" / "who" / "page.tsx").is_file()


@real_corpus
def test_real_codebook_word_search_top_five():
    codebook = Codebook.from_json(REAL_CACHE / "persona_codes.schema.json")
    for query in ("kids", "money", "wealthy"):
        assert word_search(query, codebook, limit=5), f"{query!r} finds nothing in the top five"
