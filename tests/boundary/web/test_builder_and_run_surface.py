"""Who you study shows how populated an attribute is; the run page names a world only when it can;
a refused resume can be forced on purpose. Markers only — the checks that render these pages are in
`test_interface.py` and the unit tests under `frontend/test/`."""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_the_builder_shows_coverage_from_the_engine_and_polls_only_while_it_counts():
    page = (FRONTEND / "app" / "who" / "page.tsx").read_text()
    # Coverage now comes from the persona matrix: each search result says how many answered it, per source,
    # and the pool is asked again only while the matrix is still building.
    for marker in ("have answered it", "carry_by_source", "/api/pool", 'p.state === "building"'):
        assert marker in page, f"the page lacks {marker!r}"
    route = (FRONTEND / "app" / "api" / "corpus" / "coverage" / "route.ts").read_text()
    assert '"/api/corpus/coverage' in route or "/api/corpus/coverage" in route


def test_the_run_page_does_not_name_the_first_world_for_every_seed():
    page = (FRONTEND / "app" / "run" / "page.tsx").read_text()
    assert "worldForCell" in page
    assert "world_ids[0]" not in page, "a seed whose world has not finished was shown as the first world"


def test_a_forced_resume_is_offered_only_for_a_moved_input_and_confirms_first():
    page = (FRONTEND / "app" / "run" / "page.tsx").read_text()
    assert "movedInputRefusal(s.launch_error)" in page
    assert "window.confirm(FORCE_WARNING)" in page
    route = (FRONTEND / "app" / "api" / "runs" / "[id]" / "route.ts").read_text()
    assert "force" in route
