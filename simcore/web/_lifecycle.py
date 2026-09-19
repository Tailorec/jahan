"""Run lifecycle: studies as subprocesses, watched while they work.

Runs are subprocesses because the trace is already the status channel and a
tick is recorded whole or not at all: cancelling loses at most the tick in
flight and resuming is a re-run with the same id. The registry is authoritative
for what happened; the process table below is only for whether a run is still
running. Orphans left by a killed session are swept into a truthful status on
server start. Progress is polled — a tick takes tens of seconds and streaming
buys nothing.

Execution configuration stays in the environment: the subprocess inherits it,
so a key is never accepted in a browser. Model pins and prices are study
inputs, recorded and hashed.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

_processes: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def _prune() -> None:
    """Forget processes that already exited; the registry says what they did."""
    with _lock:
        for run_id in list(_processes):
            if _processes[run_id].poll() is not None:
                del _processes[run_id]


def live_process(run_id: str) -> subprocess.Popen | None:
    """The running process for a run, if this server started one and it lives."""
    _prune()
    with _lock:
        return _processes.get(run_id)


def is_live(run_id: str) -> bool:
    return live_process(run_id) is not None


def launch(run_id: str, argv: list[str], cwd: str | Path) -> subprocess.Popen:
    """Start a study as a subprocess. A live process for the run refuses a second."""
    _prune()
    with _lock:
        if run_id in _processes:
            raise ValueError(f"run {run_id} is already running under this server")
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _processes[run_id] = proc
        return proc


def terminate(run_id: str, timeout: float = 10.0) -> bool:
    """Stop a run, losing at most the tick in flight. True when something was stopped."""
    proc = live_process(run_id)
    if proc is None:
        return False
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=timeout)
    _prune()
    return True


def launch_record(run_dir: Path) -> dict | None:
    """The `launch.json` a start wrote: the argv a resume re-runs with the same id."""
    try:
        return json.loads(Path(run_dir, "launch.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_launch_record(run_dir: Path, record: dict) -> None:
    payload = json.dumps(record, indent=2, sort_keys=True)
    Path(run_dir, "launch.json").write_text("\n".join([payload, ""]), encoding="utf-8")


def mark_interrupted(run_dir: Path, run_id: str) -> bool:
    """A cancelled or orphaned run keeps its completed ticks and says it stopped.

    Worlds that reached their horizon stay completed; the run's status becomes
    what its record shows — partial while any world stopped short — so a resume
    picks up after the last closed tick and skips finished worlds.
    """
    from simcore.schemas import RunStatus
    from simcore.trace import TraceStore

    if not Path(run_dir, "trace", "registry.db").is_file():
        return False
    try:
        store = TraceStore(Path(run_dir, "trace"))
    except Exception:
        return False
    entry = store.registry.entry(run_id)
    if entry is None or entry.status.value == RunStatus.COMPLETED.value:
        return False
    try:
        store.registry.update(entry.model_copy(update={"status": RunStatus.PARTIAL}))
        return True
    except Exception:
        return False


def sweep_orphans(runs_dir: str | Path) -> list[str]:
    """Orphans from a killed session into a truthful status, at server start.

    Any run the registry still calls running, with no live process under this
    server, died with its session: its trace stays valid and its status becomes
    partial, which is what a resume continues from.
    """
    swept: list[str] = []
    root = Path(runs_dir)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not is_live(child.name):
                if mark_interrupted(child, child.name):
                    swept.append(child.name)
    return swept


def wait_for_exit(run_id: str, timeout: float) -> bool:
    """True when the run's process exits within the timeout (tests and watchers)."""
    proc = live_process(run_id)
    if proc is None:
        return True
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    _prune()
    return proc.poll() is not None


__all__ = [
    "is_live",
    "launch",
    "launch_record",
    "live_process",
    "mark_interrupted",
    "sweep_orphans",
    "terminate",
    "wait_for_exit",
    "write_launch_record",
]
