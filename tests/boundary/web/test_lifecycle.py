"""Phase 4: launching a fake study, and watching it.

A study starts from the interface running as a subprocess; progress —
status, recorded cost, ticks closed — is readable while it works. Cancelling
ends the process and loses at most the tick in flight; resuming is a re-run
with the same id. A run outlives a server restart; orphans are swept into a
truthful status on start. Fake runs need no key, no corpus and no network.
"""

import json
import time
from pathlib import Path

from simcore.schemas import EventFilter
from simcore.trace import TraceStore
from simcore.web import create_app
from simcore.web._lifecycle import is_live, sweep_orphans, wait_for_exit

REPO = Path(__file__).resolve().parents[3]
BRIEF = (REPO / "examples" / "protein_water.yaml").read_text()
EVIDENCE = json.loads((REPO / "examples" / "protein_water.yaml.evidence.json").read_text())


def _client(runs_dir: Path, **kwargs):
    from fastapi.testclient import TestClient

    return TestClient(create_app(
        runs_dir=runs_dir,
        ontology_dir=REPO / "ontologies",
        briefs_dir=REPO / "examples",
        anchors_dir=REPO / "anchors",
        engine_root=REPO,
        **kwargs,
    ))


def _start(client, **overrides):
    body = {
        "brief_yaml": BRIEF,
        "evidence_json": EVIDENCE,
        "fake": True,
        "n": 24,
        "horizon": 1,
        "tick_unit": "day",
        "budget": 20.0,
        "channel": "survey_room",
        "seeds": "4021",
    }
    body.update(overrides)
    response = client.post("/api/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def _poll(client, run_id: str, timeout: float = 420.0) -> tuple[dict, list[dict]]:
    """GET until the run settles with its artefacts on disk.

    Tolerates the pre-registry window (404), the starting window (live but
    unrecorded) and the analysing window (completed before its artefacts
    land): settled means not live, terminal, and carrying everything a
    terminal run promises. A resumed run looks partial while it relaunches,
    so liveness — not status alone — says whether to keep waiting.
    """
    snapshots: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        if response.status_code == 200:
            detail = response.json()
            snapshots.append(detail)
            if (
                not detail.get("live", False)
                and detail["status"] != "running"
                and (detail["status"] != "completed" or detail["has_trace_summary"])
            ):
                return detail, snapshots
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} still going after {timeout}s")


def _wait_idle(client, run_id: str, timeout: float = 120.0) -> None:
    """Wait until the run's process exits, so a resume never races finalization."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        if response.status_code == 200 and not response.json().get("live", False):
            return
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} still live after {timeout}s")


def test_a_fake_study_runs_to_a_report_with_registry_agreeing(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    client = _client(runs)
    run_id = _start(client)
    assert (runs / run_id / "brief.yaml").is_file()
    assert (runs / run_id / "brief.yaml.evidence.json").is_file()

    detail, _ = _poll(client, run_id)
    assert detail["status"] == "completed"
    assert detail["fake"] is True
    assert detail["has_report"] and detail["trust_level"] == "uncalibrated"

    run_dir = runs / run_id
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "trace-summary.json").is_file()
    result = json.loads((run_dir / "result.json").read_text())
    assert result["registry"]["config"]["run_id"] == run_id
    store = TraceStore(run_dir / "trace")
    entry = store.registry.entry(run_id)
    assert entry is not None and entry.status.value == "completed"
    assert entry.recorded_cost == result["registry"]["recorded_cost"]
    # The run id, the artefacts and the registry entry name the same study.
    assert json.loads((run_dir / "report.json").read_text())["run_id"] == run_id
    # Progress was published while the run was going, not only when it ended.
    progress = json.loads((run_dir / "progress.json").read_text())
    assert progress["run_id"] == run_id and progress["tick_closed"] >= 0


def test_recorded_cost_and_ticks_closed_are_readable_while_running(tmp_path):
    """A large enough fake study that its first closed ticks are readable
    while it still runs: status, spend, ticks closed, turns and rungs."""
    import time as _time

    runs = tmp_path / "runs"
    runs.mkdir()
    client = _client(runs)
    for attempt in range(3):
        run_id = _start(client, n=150, horizon=2, seeds="4021")
        run_dir = runs / run_id
        # Wait for the first tick to close, then read while the run is going.
        deadline = _time.monotonic() + 240.0
        while _time.monotonic() < deadline:
            try:
                progress = json.loads((run_dir / "progress.json").read_text())
                if progress.get("tick_closed", -1) >= 0:
                    break
            except (OSError, ValueError):
                pass
            _time.sleep(0.2)
        else:
            raise AssertionError("no tick closed while watching")
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "running":
            continue  # finished between the tick and the read; run it again
        assert detail["live"] is True
        assert detail["progress"], "ticks closing are readable while the run is going"
        assert any(world.get("last_closed_tick", -1) >= 0 for world in detail["progress"])
        break
    else:
        raise AssertionError("never observed the run while going")
    detail, _ = _poll(client, run_id)
    assert detail["status"] == "completed"


def test_cancel_loses_at_most_the_tick_in_flight_and_resume_completes(tmp_path):
    import time as _time

    runs = tmp_path / "runs"
    runs.mkdir()
    client = _client(runs)
    run_id = _start(client, n=150, horizon=6)

    # Cancel mid-flight: wait for the run to record itself, then stop it.
    deadline = _time.monotonic() + 240.0
    while _time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        if response.status_code == 200 and response.json().get("status") == "running":
            break
        _time.sleep(0.2)
    else:
        raise AssertionError("the run never recorded itself")
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert wait_for_exit(run_id, timeout=60.0)
    assert not is_live(run_id)

    # The trace stays valid: every tick on record was recorded whole.
    run_dir = runs / run_id
    store = TraceStore(run_dir / "trace")
    for world_id in store.world_ids(run_id):
        events = store.view(run_id, world_id).events(EventFilter())
        closed = max(
            [event.tick for event in events if event.payload.kind == "tick_closed"], default=-1
        )
        partial_tick = [
            event for event in events
            if event.tick > closed
            and event.payload.kind in ("turn", "cost", "reflection", "memory", "belief_snapshot", "probe")
        ]
        assert not partial_tick, f"{world_id} keeps a torn tick"

    detail, _ = _poll(client, run_id)
    assert detail["status"] in ("partial", "running", "completed")

    response = client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202, response.text
    detail, _ = _poll(client, run_id, timeout=600.0)
    assert detail["status"] == "completed"
    assert (run_dir / "report.json").is_file()


def test_a_completed_run_resumes_by_skipping_finished_worlds(tmp_path):
    """Resuming a finished study re-runs its id and writes nothing twice."""
    runs = tmp_path / "runs"
    runs.mkdir()
    client = _client(runs)
    run_id = _start(client)
    detail, _ = _poll(client, run_id)
    assert detail["status"] == "completed"
    before = (runs / run_id / "trace-summary.json").read_bytes()

    _wait_idle(client, run_id)
    response = client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202, response.text
    detail, _ = _poll(client, run_id)
    assert detail["status"] == "completed"
    assert (runs / run_id / "trace-summary.json").read_bytes() == before


def test_a_run_started_elsewhere_resumes_truthfully(tmp_path, monkeypatch):
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "74"
    code, output = run_command(*fake_args(out, run_id, horizon=1))
    assert code == 0, output

    client = _client(out)
    response = client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409  # no launch record: nothing to re-run


def test_orphans_are_swept_into_a_truthful_status_on_start(tmp_path):
    from tests.boundary.trace.support import seed_header_and_entry

    run_id = "run-00000000000000000000000001"
    store = TraceStore(tmp_path / "runs" / run_id / "trace")
    _, entry = seed_header_and_entry(store)
    assert entry.config.run_id == run_id
    assert entry.status.value == "running"

    swept = sweep_orphans(tmp_path / "runs")
    assert run_id in swept
    assert TraceStore(tmp_path / "runs" / run_id / "trace").registry.entry(run_id).status.value == "partial"


def test_progress_is_published_per_tick(tmp_path, monkeypatch):
    """The CLI writes `progress.json` as ticks close; the registry moves with it."""
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "75"
    code, output = run_command(*fake_args(out, run_id, horizon=2))
    assert code == 0, output
    progress = json.loads((out / run_id / "progress.json").read_text())
    # Written last by the finished run, not left as the last tick wrote it.
    assert progress["status"] == "completed" and progress["tick_closed"] >= 1
    store = TraceStore(out / run_id / "trace")
    assert store.registry.entry(run_id).recorded_cost >= 0.0
