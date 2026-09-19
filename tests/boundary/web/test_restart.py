"""A run outlives a restart of the server, and only a dead run is swept.

A study is a subprocess in its own session, so killing the server does not kill
it. The server that starts next has an empty process table: it must recognise the
survivor from the record the launch left, adopt it, and sweep only what is really
gone. Marking a live run partial would invite a resume onto a run that is still
writing its trace.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simcore.trace import TraceStore
from simcore.web import _lifecycle as lifecycle
from simcore.web import create_app
from tests.boundary.trace.support import seed_header_and_entry

RUN_ID = "run-00000000000000000000000001"


@pytest.fixture(autouse=True)
def _fresh_process_table():
    """Each test is a server that has just started: it remembers no process."""
    lifecycle._processes.clear()
    yield
    for proc in list(lifecycle._processes.values()):
        try:
            proc.kill()
        except Exception:
            pass
    lifecycle._processes.clear()


def _survivor(run_dir: Path) -> subprocess.Popen:
    """A stand-in for a study whose server died: its own session, the run id in its argv."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "--run-id", RUN_ID],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lifecycle.write_launch_record(run_dir, {"argv": ["study"], "cwd": ".", "pid": proc.pid})
    return proc


def _seed(tmp_path: Path) -> tuple[Path, TraceStore]:
    runs = tmp_path / "runs"
    store = TraceStore(runs / RUN_ID / "trace")
    _, entry = seed_header_and_entry(store)
    assert entry.config.run_id == RUN_ID and entry.status.value == "running"
    return runs, store


def test_a_surviving_run_is_adopted_not_swept(tmp_path):
    runs, store = _seed(tmp_path)
    proc = _survivor(runs / RUN_ID)
    try:
        swept = lifecycle.sweep_orphans(runs)
        assert RUN_ID not in swept
        assert store.registry.entry(RUN_ID).status.value == "running"
        assert lifecycle.is_live(RUN_ID), "the new server knows the survivor is still running"
    finally:
        proc.kill()
        proc.wait()


def test_a_survivor_that_dies_is_swept_on_the_next_start(tmp_path):
    runs, store = _seed(tmp_path)
    proc = _survivor(runs / RUN_ID)
    proc.kill()
    proc.wait()

    swept = lifecycle.sweep_orphans(runs)
    assert RUN_ID in swept
    assert store.registry.entry(RUN_ID).status.value == "partial"
    assert not lifecycle.is_live(RUN_ID)


def test_a_recycled_pid_is_not_mistaken_for_the_run(tmp_path):
    """The launch record's pid now belongs to something unrelated: the run is gone."""
    runs, store = _seed(tmp_path)
    bystander = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        lifecycle.write_launch_record(runs / RUN_ID, {"argv": ["study"], "cwd": ".", "pid": bystander.pid})
        swept = lifecycle.sweep_orphans(runs)
        assert RUN_ID in swept
        assert not lifecycle.is_live(RUN_ID)
    finally:
        bystander.kill()
        bystander.wait()


def test_an_adopted_run_can_be_cancelled_and_refuses_a_second_launch(tmp_path):
    runs, store = _seed(tmp_path)
    proc = _survivor(runs / RUN_ID)
    try:
        lifecycle.sweep_orphans(runs)
        with pytest.raises(ValueError):
            lifecycle.launch(RUN_ID, [sys.executable, "-c", "pass"], tmp_path)

        assert lifecycle.terminate(RUN_ID, timeout=10.0) is True
        assert proc.wait(timeout=10) is not None
        assert not lifecycle.is_live(RUN_ID)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_the_started_server_reports_the_survivor_running(tmp_path):
    from fastapi.testclient import TestClient

    runs, store = _seed(tmp_path)
    proc = _survivor(runs / RUN_ID)
    try:
        with TestClient(create_app(runs_dir=runs)) as client:
            detail = client.get(f"/api/runs/{RUN_ID}").json()
            assert detail["status"] == "running" and detail["live"] is True
            resumed = client.post(f"/api/runs/{RUN_ID}/resume")
            assert resumed.status_code == 409, "a live run is never relaunched under itself"
    finally:
        proc.kill()
        proc.wait()


def test_a_launch_records_the_pid_it_started(tmp_path):
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    lifecycle.write_launch_record(run_dir, {"argv": ["study"], "cwd": "."})
    proc = lifecycle.launch(
        RUN_ID, [sys.executable, "-c", "import time; time.sleep(30)", RUN_ID], tmp_path, run_dir=run_dir
    )
    try:
        record = json.loads((run_dir / "launch.json").read_text())
        assert record["pid"] == proc.pid
        assert record["argv"] == ["study"], "the relaunch argv is untouched"
    finally:
        lifecycle.terminate(RUN_ID, timeout=10.0)
        deadline = time.monotonic() + 5
        while lifecycle.is_live(RUN_ID) and time.monotonic() < deadline:
            time.sleep(0.1)
