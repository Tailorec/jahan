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
    assert "brief" in route and "check" in route


def test_study_states_task_and_scale():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    for marker in ("what personas answer", "purchase intent", "Anchor version", "anchor_versions"):
        assert marker in text, f"intake lacks {marker!r}"


def test_endpoint_status_without_keys():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    assert "/api/status" in text
    assert "no endpoint — fake only" in text or "endpoint configured" in text
    for page in list((FRONTEND / "app").rglob("*.tsx")) + list((FRONTEND / "app").rglob("*.ts")):
        content = page.read_text()
        for marker in ("API_KEY", "api_key", 'type="password"', "secret"):
            assert marker not in content, f"{page.name} handles a key: {marker!r}"
