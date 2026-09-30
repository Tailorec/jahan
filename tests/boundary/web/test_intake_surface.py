"""Phase 7 intake surface: glossary terms, the ledger, the task and the scale,
endpoint status without keys."""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_glossary_terms_with_definitions_where_set():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    for marker in (
        "atomic unit of stimulus",
        "named slices of the target market",
        "taken as true without evidence",
    ):
        assert marker in text, f"intake lacks {marker!r}"


def test_assumption_ledger_assembled_before_a_run():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    for marker in (
        "Validate brief",
        "/api/briefs/validate",
        "Assumption ledger",
        "stated, assumed and unstated",
    ):
        assert marker in text, f"intake lacks {marker!r}"
    route = (FRONTEND / "app" / "api" / "briefs" / "validate" / "route.ts").read_text()
    assert '"/api/briefs/validate"' in route


def test_study_states_task_and_scale():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    for marker in ("Channels — what spreads information", "purchase-intent question", "Survey every k ticks", "Anchor version"):
        assert marker in text, f"intake lacks {marker!r}"
    # The request that carries them is built in one plain module the unit tests exercise, and the page must
    # go through it: a page that writes its own body can drift from the one that is tested.
    assert "studyRequest(" in text, "intake builds its own request instead of using lib/study"
    assert "anchor_versions" in (FRONTEND / "lib" / "study.ts").read_text()


def test_endpoint_status_without_keys():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    assert "/api/status" in text
    assert "no endpoint — studies cannot run" in text and "endpoint configured" in text
    for page in list((FRONTEND / "app").rglob("*.tsx")) + list((FRONTEND / "app").rglob("*.ts")):
        content = page.read_text()
        for marker in ("API_KEY", "api_key", 'type="password"', "secret"):
            assert marker not in content, f"{page.name} handles a key: {marker!r}"


def test_no_page_prints_an_icon_as_text():
    """An icon is an element, not text. Interpolated into a template string it prints `[object Object]`, and
    the two most important buttons on the intake page — run the gate, run the study — said exactly that."""
    for page in (FRONTEND / "app").rglob("*.tsx"):
        assert "${ICONS" not in page.read_text(), f"{page.relative_to(FRONTEND)} interpolates an icon into a string"


def test_a_study_starts_from_a_saved_audience_set_never_an_ontology_alone():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    assert 'audience_1' not in text, "no placeholder audience a study could launch with"
    assert "form.audiences.length ? [] :" in text, "no audience set blocks the gate and the launch"
    assert '"/api/audience-sets"' in text and "applySet(" in text, "choosing a set brings its audiences and ontology together"
    assert "localStorage" not in text, "who is studied is saved by the engine, not held in one browser"
