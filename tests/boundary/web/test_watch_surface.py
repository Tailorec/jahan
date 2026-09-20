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
    for marker in ('"/api/runs"', "Horizon", "Watch", "studyRequest("):
        assert marker in text, f"intake never offers {marker!r}"
    # What the request says lives in `lib/study.ts`, where the unit tests pin it.
    builder = (FRONTEND / "lib" / "study.ts").read_text()
    for marker in ("brief_yaml", 'fake: form.mode === "fake"'):
        assert marker in builder, f"the study request never says {marker!r}"


def test_fake_studies_are_marked_in_every_view():
    assert "fake study" in (FRONTEND / "app" / "run" / "page.tsx").read_text()
    assert "fake study" in (FRONTEND / "app" / "report" / "page.tsx").read_text()
    assert "fake" in (FRONTEND / "app" / "intake" / "page.tsx").read_text()


def test_run_entries_carry_liveness_fakery_and_progress():
    engine = (FRONTEND / "lib" / "engine.ts").read_text()
    for marker in ("fake?: boolean", "live?: boolean", "progress?: WorldProgress[]"):
        assert marker in engine, f"engine types lack {marker!r}"


def test_launch_cancel_and_resume_are_proxied_to_the_engine():
    runs = (FRONTEND / "app" / "api" / "runs" / "route.ts").read_text()
    assert "export async function POST" in runs and '"/api/runs"' in runs
    detail = (FRONTEND / "app" / "api" / "runs" / "[id]" / "route.ts").read_text()
    assert "export async function DELETE" in detail
    assert 'action !== "resume"' in detail and "/resume" in detail


def test_the_interface_starts_and_stops_nothing_itself():
    """One implementation of a run's lifecycle, and it is the engine's: the interface holds no
    process, no pid, no run directory. It had its own launcher, a second id minter that disagreed
    with the engine's about how long an id is, and a cancel marker only it understood."""
    forbidden = ("node:child_process", "spawn(", "execFile", "process.kill", "launch.json", "cancelled.json", "mintRunId")
    for path in list((FRONTEND / "app").rglob("*.ts*")) + list((FRONTEND / "lib").rglob("*.ts*")):
        text = path.read_text()
        for marker in forbidden:
            assert marker not in text, f"{path.relative_to(FRONTEND)} runs things itself: {marker!r}"
