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

A study runs in its own session, so it outlives the server that started it. The
launch leaves its pid in `launch.json`; the server that starts next recognises a
survivor from that record (and the run id in the process's own argv, so a
recycled pid is never mistaken for it), adopts it, and sweeps only what is gone.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

# How often a survivor's exit is looked for: a process this server did not start has
# no `wait` of its own, so it is watched, not waited on.
_POLL_STEP = 0.05


class _Survivor:
    """A study this server did not start and that is still running: known by its pid and when it began.

    It answers the three questions the lifecycle asks of a process — has it
    exited, wait for it, and which process is it — the way a `Popen` does. It is
    a study an earlier server started, or one started from the command line.
    """

    def __init__(self, pid: int, run_id: str, started: str | None = None) -> None:
        self.pid = pid
        self._run_id = run_id
        self._started = started

    def poll(self) -> int | None:
        return None if _is_the_run(self.pid, self._run_id, self._started) else 0

    def wait(self, timeout: float | None = None) -> int:
        waited = 0.0
        while self.poll() is None:
            if timeout is not None and waited >= timeout:
                raise subprocess.TimeoutExpired(cmd=self._run_id, timeout=timeout)
            time.sleep(_POLL_STEP)
            waited += _POLL_STEP
        return 0

    def kill(self) -> None:
        _signal(self.pid, signal.SIGKILL)


_processes: dict[str, subprocess.Popen | _Survivor] = {}
_lock = threading.Lock()


def process_start(pid: int) -> str | None:
    """When the process began, in the kernel's own ticks; `None` where `/proc` is not there to say."""
    try:
        return Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _signal(pid: int, sig: int) -> None:
    """Signal a study. Its whole group only when it leads one: a study this server started is its own
    session, but a study run from a terminal shares the shell's group, and signalling that would take the
    shell and everything piped beside it."""
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _is_the_run(pid: int, run_id: str, started: str | None = None) -> bool:
    """True when `pid` is alive and is this run's study, not whatever inherited the number.

    A pid alone proves nothing after a reboot or a long uptime. The study's argv
    carries its run id, so a process that names it is the study; a study run from
    the command line may have minted its id and not carry it, and is known instead
    by the start time its launch record kept. Where `/proc` is absent the signal
    probe is all the platform offers.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    try:
        state = Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()[0]
        if state in ("Z", "X"):
            return False
        argv = Path("/proc", str(pid), "cmdline").read_bytes().split(b"\0")
    except (OSError, IndexError):
        return True
    if run_id.encode("utf-8") in argv:
        return True
    return started is not None and process_start(pid) == started


def _prune() -> None:
    """Forget processes that already exited; the registry says what they did."""
    with _lock:
        for run_id in list(_processes):
            if _processes[run_id].poll() is not None:
                del _processes[run_id]


def live_process(run_id: str) -> subprocess.Popen | _Survivor | None:
    """The running process for a run, if this server started one and it lives."""
    _prune()
    with _lock:
        return _processes.get(run_id)


def is_live(run_id: str) -> bool:
    return live_process(run_id) is not None


def launch(
    run_id: str, argv: list[str], cwd: str | Path, *, run_dir: Path | None = None
) -> subprocess.Popen:
    """Start a study as a subprocess. A live process for the run refuses a second.

    With a `run_dir` the study's output lands in `launch.log` there — a study
    that dies before it records anything otherwise leaves nothing to explain
    itself — and its pid goes into `launch.json`, which is how a later server
    recognises it as still running.
    """
    _prune()
    with _lock:
        if run_id in _processes:
            raise ValueError(f"run {run_id} is already running under this server")
        log = open(Path(run_dir, "launch.log"), "ab") if run_dir is not None else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=log,
                stderr=subprocess.STDOUT if run_dir is not None else subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            if run_dir is not None:
                log.close()
        _processes[run_id] = proc
    if run_dir is not None:
        record = launch_record(run_dir) or {}
        write_launch_record(run_dir, {**record, "pid": proc.pid})
    return proc


def log_tail(run_dir: Path, hide: tuple[str, ...] = (), lines: int = 4) -> str | None:
    """What a study said last before it stopped — the reason, without the paths.

    A validation error ends in a link to its documentation, which explains
    nothing; it is left out so the lines that do are the ones shown.
    """
    try:
        written = Path(run_dir, "launch.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    said = [line.strip() for line in written if line.strip() and not line.strip().startswith("For further information")]
    if not said:
        return None
    tail = "\n".join(said[-lines:])
    for prefix in hide:
        tail = tail.replace(prefix, "…")
    return tail


def terminate(run_id: str, timeout: float = 10.0) -> bool:
    """Stop a run, losing at most the tick in flight. True when something was stopped."""
    proc = live_process(run_id)
    if proc is None:
        return False
    _signal(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal(proc.pid, signal.SIGKILL)
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

    A study outlives the server that started it, so a run the registry still
    calls running is first looked for in the process table by the pid its launch
    recorded: a survivor is adopted and left alone. Only a run whose process is
    gone died with its session — its trace stays valid and its status becomes
    partial, which is what a resume continues from.
    """
    swept: list[str] = []
    root = Path(runs_dir)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not is_live(child.name):
                if adopt(child):
                    continue
                if mark_interrupted(child, child.name):
                    swept.append(child.name)
    return swept


def adopt(run_dir: Path) -> bool:
    """Take over a study this server did not start, if its process is still running.

    Its launch record names the process: an earlier server wrote it, or the command line did.
    """
    if live_process(run_dir.name) is not None:
        return True
    record = launch_record(run_dir)
    pid = (record or {}).get("pid")
    started = (record or {}).get("started")
    started = started if isinstance(started, str) else None
    if not isinstance(pid, int) or not _is_the_run(pid, run_dir.name, started):
        return False
    with _lock:
        _processes.setdefault(run_dir.name, _Survivor(pid, run_dir.name, started))
    return True


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
    "adopt",
    "is_live",
    "launch",
    "launch_record",
    "live_process",
    "log_tail",
    "mark_interrupted",
    "process_start",
    "sweep_orphans",
    "terminate",
    "wait_for_exit",
    "write_launch_record",
]
