"""Phase 5: the population page — who was drawn and whether the draw was sound.

Every gate result shows its statistic, its threshold and its verdict;
requested and achieved mix render together with relaxations; the synthesized
share and completable domains are stated; sample personas come from the
population's own records with origins; audiences and communities are distinct;
a failed gate stays readable. The interface speaks the glossary: population,
never cohort.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_gates_show_statistic_threshold_and_verdict_in_words():
    text = (FRONTEND / "app" / "population" / "page.tsx").read_text()
    for marker in ("words.question", "words.result", "words.rule", "words.raw", "words.failed"):
        assert marker in text, f"population page lacks {marker!r}"
    words = (FRONTEND / "lib" / "gates.ts").read_text()
    # The statistic stays beside the words, so the call can still be recomputed.
    for marker in ("Passes when that chance is above", "Passes at similarity", "χ²", "KS D", "Needs at least"):
        assert marker in words, f"gate words lack {marker!r}"


def test_requested_achieved_relaxations_synthesized_and_completion():
    text = (FRONTEND / "app" / "population" / "page.tsx").read_text()
    for marker in (
        "Asked for", "Reached", "relaxation", "explainRelaxation(",
        "Synthesized", "May be filled in", "Never filled in",
    ):
        assert marker in text, f"population page lacks {marker!r}"


def test_sample_personas_render_records_with_origins():
    text = (FRONTEND / "app" / "population" / "page.tsx").read_text()
    for marker in ("personas.json", "origins", "conditioning", "beliefs →"):
        assert marker in text, f"population page lacks {marker!r}"
    assert "manifest.persona_ids.slice" not in text, "sample must render records, not bare ids"


def test_audiences_and_communities_are_different_things():
    text = (FRONTEND / "app" / "population" / "page.tsx").read_text()
    for marker in (
        "Audiences vs communities",
        "cut across audiences",
        "No communities formed",
        "polarization_reason",
        "audience_divergence",
    ):
        assert marker in text, f"population page lacks {marker!r}"


def test_a_failed_gate_stays_readable():
    text = (FRONTEND / "app" / "population" / "page.tsx").read_text()
    assert "This study never ran" in text
    assert "gate && !gate.overall" in text


def test_the_interface_speaks_the_glossary():
    """Population, not cohort. Audience and Community, never segment."""
    pages = list((FRONTEND / "app").rglob("page.tsx"))
    for page in pages:
        if page.parent.name == "cohort":
            continue
        text = page.read_text()
        assert "Cohort" not in text and "cohort" not in text.replace("cohort?run", "").replace("/cohort", ""), (
            f"{page.parent.name} says cohort"
        )
        assert "segment" not in text.lower(), f"{page.parent.name} says segment"
    redirect = (FRONTEND / "app" / "cohort" / "page.tsx").read_text()
    assert "/population" in redirect
