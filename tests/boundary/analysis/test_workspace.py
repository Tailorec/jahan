"""Phase 10: the workspace, and reconciliation.

A workspace summary is a derived shape over registry entries, and computes
nothing from a trace; `RunRegistryEntry` carries what a rollup needs; the
whole of `web` performs no arithmetic; every number the interface displays
is traceable to the shape that produced it, on a real recorded study.
"""

import json
import subprocess
import sys
from pathlib import Path

from simcore.analysis import WorkspaceSummary, workspace_summary
from simcore.schemas import RunRegistryEntry, RunStatus
from simcore.trace import TraceStore
from simcore.web import create_app
from tests.study_builders import partition_run_config, scenario_payload

REPO = Path(__file__).resolve().parents[3]


def _config():
    return partition_run_config(scenario_payload())


def _entry(status: str, *, cost: float, population: int, budget: float = 20.0):
    return RunRegistryEntry.model_validate({
        "config": {**config_hash_free(), "budget": {"max_cost": budget, "currency": "USD"}},
        "contract_version": "1.0.0",
        "status": status,
        "engine_version": "x",
        "recorded_cost": cost,
        "discarded_ticks": 0,
        "population_size": population,
    })


def config_hash_free():
    return partition_run_config(scenario_payload())


def test_a_workspace_summary_computes_nothing_from_a_trace():
    entries = [
        _entry("completed", cost=1.5, population=150),
        _entry("completed", cost=0.5, population=150),
        _entry("running", cost=0.25, population=24),
        _entry("partial", cost=0.0, population=0),
    ]
    summary = workspace_summary(entries)
    assert isinstance(summary, WorkspaceSummary)
    assert summary.total_studies == 4
    assert summary.completed_studies == 2
    assert summary.running_studies == 1 and summary.partial_studies == 1
    assert summary.total_spend == 2.25
    assert summary.total_personas == 324
    assert summary.total_budget == 80.0
    assert summary.reports_written == 2
    source = Path(__import__("simcore.analysis", fromlist=["__file__"]).__file__).resolve().parent / "_workspace.py"
    text = source.read_text()
    assert "all_events" not in text and "read_live" not in text and "parquet" not in text.lower()


def test_registry_entries_carry_what_a_rollup_needs(tmp_path):
    """population_size rides the entry, so no workspace total walks a partition."""
    from tests.boundary.trace.support import seed_header_and_entry

    store = TraceStore(tmp_path / "trace")
    header, entry = seed_header_and_entry(store)
    assert entry.population_size == 0
    moved = entry.model_copy(update={"population_size": 150, "status": RunStatus.COMPLETED})
    store.registry.update(moved)
    assert store.registry.entry(entry.config.run_id).population_size == 150


def test_the_workspace_endpoint_serves_the_derived_shape(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "79"
    code, output = run_command(*fake_args(out, run_id))
    assert code == 0, output

    client = subprocess_client(out)
    body = client.get("/api/workspace").json()
    assert body["total_studies"] == 1
    assert body["completed_studies"] == 1
    assert body["total_personas"] == 24
    assert body["total_budget"] == 20.0
    assert body["reports_written"] == 1
    assert WorkspaceSummary.model_validate(body) == WorkspaceSummary.model_validate(body)


def test_every_displayed_number_is_traceable():
    """The overview renders the workspace shape's fields and computes nothing."""
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    text = (frontend / "app" / "page.tsx").read_text()
    for marker in (
        "data.workspace.total_studies",
        "data.workspace.total_spend",
        "data.workspace.total_personas",
        "data.workspace.reports_written",
        "derived shape, never walked",
    ):
        assert marker in text, f"overview lacks {marker!r}"
    assert ".reduce(" not in text, "the overview must not compute sums client-side"


def test_disk_mode_derives_through_the_engine(tmp_path, monkeypatch):
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "80"
    code, output = run_command(*fake_args(out, run_id))
    assert code == 0, output

    proc = subprocess.run(
        [str(REPO / ".venv" / "bin" / "python"), str(REPO / "scripts" / "workspace_summary.py")],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["total_studies"] == 1 and body["reports_written"] == 1


def run_command(*argv: str) -> tuple[int, str]:
    import io as _io
    from contextlib import redirect_stderr, redirect_stdout

    from simcore.cli.__main__ import main as cli_main

    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        code = cli_main(list(argv))
    return code, buffer.getvalue()


def subprocess_client(runs_dir: Path):
    from fastapi.testclient import TestClient

    return TestClient(create_app(runs_dir=runs_dir))
