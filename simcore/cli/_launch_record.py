"""What a study leaves so a server can recognise it while it runs and relaunch it afterwards.

A study started from the interface already has this record, written by the server that started it. A study
started from the command line had none, so a server could not tell that it was alive, marked it `partial` when
it started, and could not resume it. The command line writes the same `launch.json`: the argv that reruns it
under the same id, where it ran, and which process it is.

The process is named by its pid and its start time together: a pid alone proves nothing once the number has
been reused. The record is plain JSON so `simcore.web` reads it without this module.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def process_start(pid: int) -> str | None:
    """When the process began, in the kernel's own ticks; `None` where `/proc` is not there to say."""
    try:
        stat = Path("/proc", str(pid), "stat").read_text()
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def record_launch(run_dir: Path, run_id: str, command: list[str], *, cwd: Path | None = None) -> None:
    """Write `launch.json` for this process, keeping the argv a server already recorded for it."""
    path = Path(run_dir, "launch.json")
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    argv = existing.get("argv")
    if not isinstance(argv, list):
        argv = [sys.executable, "-m", "simcore.cli", *command]
        if not any(part == "--run-id" or part.startswith("--run-id=") for part in argv):
            argv += ["--run-id", run_id]
    record = {
        **existing,
        "argv": argv,
        "cwd": existing.get("cwd") or str(cwd or Path.cwd()),
        "pid": os.getpid(),
        "started": process_start(os.getpid()),
    }
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
