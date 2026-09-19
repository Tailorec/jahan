"""Phase 4: a study started from the interface, watched while it works.

The run page polls while a run is live and shows ticks closing, turns
landing, spend against the budget and the rung in force, with cancel and
resume beside it. Fake studies are marked in every view of them; intake
launches the first (fake) study; the engine API carries liveness, fakery
and per-world progress on every run entry.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_the_run_page_watches_a_live_run():
    text = (FRONTEND / "app" / "run" / "page.tsx").read_text()
    for marker in (
        "setInterval",  # progress is polled; streaming buys nothing
        "Cancel run",
        "Resume run",
        "Last closed tick",
        "Turns landed",
        "Rung in force",
        "fake study",
        "live progress",
    ):
        assert marker in text, f"run page never shows {marker!r}"


def test_intake_launches_a_fake_study():
    text = (FRONTEND / "app" / "intake" / "page.tsx").read_text()
    for marker in ('"/api/runs"', "brief_yaml", "Horizon", "fake: true", "Watch"):
        assert marker in text, f"intake never offers {marker!r}"


def test_fake_studies_are_marked_in_every_view():
    assert "fake study" in (FRONTEND / "app" / "run" / "page.tsx").read_text()
    assert "fake study" in (FRONTEND / "app" / "report" / "page.tsx").read_text()
    assert "fake" in (FRONTEND / "app" / "intake" / "page.tsx").read_text()


def test_run_entries_carry_liveness_fakery_and_progress():
    engine = (FRONTEND / "lib" / "engine.ts").read_text()
    for marker in ("fake?: boolean", "live?: boolean", "progress?: WorldProgress[]"):
        assert marker in engine, f"engine types lack {marker!r}"


def test_launch_cancel_and_resume_have_server_routes():
    runs = (FRONTEND / "app" / "api" / "runs" / "route.ts").read_text()
    assert "export async function POST" in runs
    assert "launch.json" in runs
    detail = (FRONTEND / "app" / "api" / "runs" / "[id]" / "route.ts").read_text()
    assert "export async function DELETE" in detail
    assert 'action !== "resume"' in detail
    assert "cancelled.json" in detail


def test_disk_reads_merge_published_progress():
    server = (FRONTEND / "lib" / "server.ts").read_text()
    assert "progress.json" in server
    assert "cancelled.json" in server
