"""What the server refuses, what it says while a study is going, and what it will not leak.

Each of these was true of the first cut of `web` and none was asserted: a run id
could climb out of the runs root, a study with nonsense numbers was accepted and
died silently, a run whose process was alive read as finished, and a refusal
carried the path of the file it refused.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from simcore.analysis import world_progress
from simcore.schemas import EventFilter, RunStatus
from simcore.trace import TraceStore
from simcore.web import _lifecycle as lifecycle
from simcore.web import create_app
from tests.boundary.trace.support import seed_header_and_entry
from tests.boundary.web.test_api import _seed_run

REPO = Path(__file__).resolve().parents[3]
BRIEF = (REPO / "examples" / "protein_water.yaml").read_text()
EVIDENCE = json.loads((REPO / "examples" / "protein_water.yaml.evidence.json").read_text())


@pytest.fixture(autouse=True)
def _fresh_process_table():
    lifecycle._processes.clear()
    yield
    for proc in list(lifecycle._processes.values()):
        try:
            proc.kill()
        except Exception:
            pass
    lifecycle._processes.clear()


def _client(runs_dir: Path):
    from fastapi.testclient import TestClient

    runs_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(
        runs_dir=runs_dir,
        ontology_dir=REPO / "ontologies",
        briefs_dir=REPO / "examples",
        anchors_dir=REPO / "anchors",
        engine_root=REPO,
    ))


def _body(**overrides):
    body = {"brief_yaml": BRIEF, "evidence_json": EVIDENCE, "fake": True, "horizon": 1}
    body.update(overrides)
    return body


# --- a run id is one directory name -------------------------------------------------


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "..", ".hidden", "_validate", "x" * 200, "run id"])
def test_a_run_id_that_is_not_one_directory_name_is_refused(tmp_path, run_id):
    runs = tmp_path / "runs"
    client = _client(runs)
    response = client.post("/api/runs", json=_body(run_id=run_id))
    assert response.status_code == 422, response.text
    assert sorted(path.name for path in tmp_path.iterdir()) == ["runs"], "nothing was written outside the runs root"
    assert not any(runs.iterdir()), "nothing was written inside it either"


def test_a_run_id_that_climbs_out_of_the_runs_root_reads_as_no_such_run(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "result.json").write_text(json.dumps({"status": "completed", "registry": {}, "outcomes": []}))
    client = _client(tmp_path / "runs")
    for path in ("/api/runs/..", "/api/runs/%2e%2e", "/api/runs/%2e%2e/report", "/api/runs/_validate"):
        assert client.get(path).status_code == 404, path


def test_a_run_id_the_trace_would_refuse_is_refused_up_front(tmp_path):
    """`run-mine` passes for a directory name and dies inside the study on the id pattern."""
    runs = tmp_path / "runs"
    response = _client(runs).post("/api/runs", json=_body(run_id="run-mine"))
    assert response.status_code == 422 and "not a run id" in response.json()["detail"]
    assert not any(runs.iterdir())


# --- reading a run never writes to it -----------------------------------------------


def _tree(root: Path) -> list[str]:
    """Every file under a root — bar SQLite's own `-shm`/`-wal`, which opening any database
    in WAL mode brings and closing it takes away again: housekeeping, not a record."""
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if not path.name.endswith(("-shm", "-wal"))
    )


def test_looking_at_a_run_that_never_ran_a_study_leaves_it_as_it_was(tmp_path):
    """A gate-only run has no trace. Reading it created one — and the run 500ed on `summary`."""
    runs = tmp_path / "runs"
    client = _client(runs)
    gated = client.post("/api/gate", json={"brief_yaml": BRIEF, "evidence_json": EVIDENCE, "n": 60}).json()
    run_id = gated["run_id"]
    before = _tree(runs)

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200 and detail.json()["has_gate_report"] is True
    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/workspace").status_code == 200
    for path in ("summary", "events", "digest", "report", "findings"):
        assert client.get(f"/api/runs/{run_id}/{path}").status_code == 404, path
    assert client.get(f"/api/runs/{run_id}/gate").status_code == 200
    assert client.get(f"/api/runs/{run_id}/manifest").status_code == 200
    assert _tree(runs) == before, "nothing was created by looking"


def test_looking_at_a_finished_run_writes_nothing_to_it(tmp_path):
    runs = tmp_path / "runs"
    store, entry, _ = _seed_run(runs)
    run_id = entry.config.run_id
    world_id = store.world_ids(run_id)[0]
    client = _client(runs)
    before = _tree(runs)
    for path in (
        f"/api/runs/{run_id}",
        f"/api/runs/{run_id}/summary",
        f"/api/runs/{run_id}/events",
        f"/api/runs/{run_id}/worlds/{world_id}/edges",
        "/api/runs",
        "/api/workspace",
    ):
        assert client.get(path).status_code == 200, path
    assert _tree(runs) == before


# --- a study's numbers are checked before a process is started ----------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"n": 0},
        {"horizon": 0},
        {"budget": -1},
        {"budget": 0},
        {"seeds": "abc"},
        {"seeds": ","},
        {"seeds": []},
        {"tick_unit": "fortnight"},
        {"elicits": "purchase_intent"},
        {"api_key": "sk-nope"},
        {"base_url": "http://elsewhere"},
        {"brief_yaml": "   "},
    ],
)
def test_a_study_with_nonsense_inputs_is_refused_before_it_starts(tmp_path, overrides):
    runs = tmp_path / "runs"
    client = _client(runs)
    response = client.post("/api/runs", json=_body(**overrides))
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], str), "one refusal shape: detail is a sentence"
    assert not any(runs.iterdir()), "a refused study leaves no run behind"
    assert not lifecycle._processes


def test_a_key_is_never_accepted_in_a_request(tmp_path):
    client = _client(tmp_path / "runs")
    response = client.post("/api/runs", json=_body(api_key="sk-secret"))
    assert response.status_code == 422
    assert "sk-secret" not in response.text


def test_a_real_study_names_its_pins_and_needs_a_configured_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMCORE_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    runs = tmp_path / "runs"
    client = _client(runs)

    unpinned = client.post("/api/runs", json=_body(fake=False))
    assert unpinned.status_code == 422 and "pins its models" in unpinned.json()["detail"]

    unconfigured = client.post("/api/runs", json=_body(fake=False, model="m", embed_model="e"))
    assert unconfigured.status_code == 409
    assert "SIMCORE_INFERENCE_BASE_URL" in unconfigured.json()["detail"]
    assert not any(runs.iterdir())


def test_paging_is_bounded(tmp_path):
    store, entry, _ = _seed_run(tmp_path / "runs")
    client = _client(tmp_path / "runs")
    run_id = entry.config.run_id
    for params in ({"offset": -1}, {"limit": 0}, {"limit": -3}):
        assert client.get(f"/api/runs/{run_id}/events", params=params).status_code == 422, params
    assert client.get("/api/codebook", params={"offset": -1}).status_code in (409, 422)


# --- a study says why it stopped ----------------------------------------------------


def test_a_study_that_dies_before_it_records_anything_says_why(tmp_path):
    """Its output was thrown away, so the run 404ed forever and nobody could tell why."""
    runs = tmp_path / "runs"
    client = _client(runs)
    response = client.post("/api/runs", json=_body(anchor_versions=["purchase_intent=v99"]))
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert lifecycle.wait_for_exit(run_id, timeout=120)

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200, "a started run exists, whether or not it got as far as a registry"
    body = detail.json()
    assert body["status"] == "partial" and body["live"] is False
    assert body["launch_error"], "the reason the study stopped is served"
    assert str(tmp_path) not in body["launch_error"] and str(REPO) not in body["launch_error"]


# --- a live process is not a finished run --------------------------------------------


def test_a_run_whose_process_is_alive_is_not_reported_finished(tmp_path):
    """The registry can say completed while the report is still being written."""
    runs = tmp_path / "runs"
    store, entry, _ = _seed_run(runs)
    run_id = entry.config.run_id
    store.registry.update(entry.model_copy(update={"status": RunStatus.COMPLETED}))
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "--run-id", run_id],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        lifecycle.write_launch_record(runs / run_id, {"argv": ["study"], "cwd": ".", "pid": proc.pid})
        lifecycle.sweep_orphans(runs)
        body = _client(runs).get(f"/api/runs/{run_id}").json()
        assert body["live"] is True
        assert body["status"] == "running", "no result.json yet: the study has not finished"
        assert body["has_report"] is False
    finally:
        proc.kill()
        proc.wait()


# --- the workspace counts reports, not completions ----------------------------------


def test_reports_written_counts_reports_not_completed_runs(tmp_path):
    runs = tmp_path / "runs"
    store, entry, _ = _seed_run(runs)
    run_id = entry.config.run_id
    store.registry.update(entry.model_copy(update={"status": RunStatus.COMPLETED}))
    client = _client(runs)

    body = client.get("/api/workspace").json()
    assert body["completed_studies"] == 1
    assert body["reports_written"] == 0, "completed, but analysis never wrote its report"

    (runs / run_id / "report.json").write_text("{}")
    assert client.get("/api/workspace").json()["reports_written"] == 1


# --- progress is derived in analysis, and matches the raw events --------------------


def test_world_progress_matches_the_events_it_summarises(tmp_path):
    store, entry, events = _seed_run(tmp_path / "runs")
    run_id = entry.config.run_id
    world_id = store.world_ids(run_id)[0]
    view = store.view(run_id, world_id)

    shape = world_progress(view, world_id)
    closed = [event.tick for event in events if event.payload.kind == "tick_closed"]
    turns = [event for event in events if event.payload.kind == "turn"]
    degraded = {str(event.payload.rung) for event in events if event.payload.kind == "degraded"}
    assert shape.world_id == world_id
    assert shape.last_closed_tick == max(closed)
    assert shape.turns == len(turns) and shape.turns > 0
    assert set(shape.rungs) == degraded

    empty = TraceStore(tmp_path / "empty" / "trace")
    _, fresh = seed_header_and_entry(empty)
    fresh_world = empty.world_ids(fresh.config.run_id)[0]
    nothing = world_progress(empty.view(fresh.config.run_id, fresh_world), fresh_world)
    assert nothing.last_closed_tick is None and nothing.turns == 0 and nothing.rungs == ()


def test_progress_reaches_the_browser_as_the_shape_analysis_derived(tmp_path):
    runs = tmp_path / "runs"
    store, entry, _ = _seed_run(runs)
    run_id = entry.config.run_id
    world_id = store.world_ids(run_id)[0]
    body = _client(runs).get(f"/api/runs/{run_id}").json()
    assert body["status"] == "running"
    expected = json.loads(world_progress(store.view(run_id, world_id), world_id).model_dump_json())
    assert body["progress"] == [expected]


# --- nothing served carries a path ---------------------------------------------------


def test_a_refused_brief_names_the_file_not_where_it_lives(tmp_path):
    client = _client(tmp_path / "runs")
    for path, body in (
        ("/api/briefs/validate", {"brief_yaml": "product: {}"}),
        ("/api/gate", {"brief_yaml": "product: {}"}),
        ("/api/runs", {"brief_yaml": "product: {}"}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 422, (path, response.text)
        assert str(tmp_path) not in response.text, path
        assert "consumersim-brief" not in response.text, path
        assert "brief.yaml" in response.text, path


# --- the gate, served ---------------------------------------------------------------


def test_the_gate_answers_with_its_report_and_manifest_and_no_path(tmp_path):
    runs = tmp_path / "runs"
    client = _client(runs)
    response = client.post("/api/gate", json={"brief_yaml": BRIEF, "evidence_json": EVIDENCE, "n": 60})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0 and body["run_id"]
    assert body["gate"]["overall"] is True and body["gate"]["results"]
    assert body["manifest"]["persona_ids"]
    assert str(tmp_path) not in response.text and str(REPO) not in response.text
    assert (runs / body["run_id"] / "gate-report.json").is_file(), "the gate is kept, like a study's"

    listed = client.get("/api/runs").json()["runs"]
    assert [run["run_id"] for run in listed] == [body["run_id"]]
    assert listed[0]["has_gate_report"] is True


# --- one refusal shape ---------------------------------------------------------------


def test_every_refusal_is_a_detail_sentence(tmp_path):
    client = _client(tmp_path / "runs")
    for response in (
        client.get("/api/runs/run-nope"),
        client.get("/api/ontologies/nope/0.0.0"),
        client.post("/api/runs", json={}),
        client.post("/api/gate", json={"brief_yaml": BRIEF, "n": 0}),
    ):
        assert response.status_code in (404, 422)
        assert isinstance(response.json()["detail"], str), response.text


# --- evidence is resolved across the run, not one world at a time --------------------


def test_evidence_from_sibling_worlds_resolves_in_one_request(tmp_path):
    """A finding cites events from every replicate; a world's `resolve` refuses a sibling's ids,
    so resolving them world by world lost the whole batch as soon as two worlds were in it."""
    from simcore.schemas import PartitionHeader
    from tests.boundary.trace.support import partition_events, write_by_tick
    from tests.study_builders import partition_header_payload

    runs = tmp_path / "runs"
    store, entry, events = _seed_run(runs)
    run_id = entry.config.run_id
    first_world = store.world_ids(run_id)[0]
    other_seed = next(seed for seed in entry.config.seeds if seed != 4021)
    second = PartitionHeader.model_validate({**partition_header_payload(), "replicate_seed": other_seed})
    store.create_world(run_id, second)
    siblings = [
        event.model_copy(update={"world_id": second.world_id, "event_id": f"ev-{'1' * 22}{index:04d}"})
        for index, event in enumerate(events)
    ]
    write_by_tick(store, siblings)

    asked = [events[0].event_id, siblings[0].event_id]
    client = _client(runs)

    within_one_world = client.get(f"/api/runs/{run_id}/worlds/{first_world}/resolve", params={"trace_id": asked})
    assert within_one_world.status_code == 404, "a world refuses its sibling's ids"

    across_the_run = client.get(f"/api/runs/{run_id}/resolve", params={"trace_id": asked})
    assert across_the_run.status_code == 200, across_the_run.text
    assert [event["event_id"] for event in across_the_run.json()["events"]] == asked

    absent = client.get(f"/api/runs/{run_id}/resolve", params={"trace_id": [asked[0], "ev-00000000000000000000000001"]})
    assert absent.status_code == 404, "absent ids still refuse: nothing is guessed"


# --- a study that died mid-session is not still running -------------------------------


def test_a_study_that_died_mid_session_reads_partial_not_running(tmp_path):
    """The sweep runs at server start; a study killed while the server was up stayed `running`
    forever, with a cancel button for a process that no longer existed."""
    runs = tmp_path / "runs"
    store, entry, _ = _seed_run(runs)
    run_id = entry.config.run_id
    assert entry.status.value == "running"
    lifecycle.write_launch_record(runs / run_id, {"argv": ["study"], "cwd": ".", "pid": 2**22 - 1})

    body = _client(runs).get(f"/api/runs/{run_id}").json()
    assert body["live"] is False
    assert body["status"] == "partial"


def test_a_run_started_elsewhere_keeps_the_status_its_registry_states(tmp_path):
    """No launch record: a study running in someone's terminal. Its process is not ours to judge."""
    runs = tmp_path / "runs"
    _, entry, _ = _seed_run(runs)
    body = _client(runs).get(f"/api/runs/{entry.config.run_id}").json()
    assert body["status"] == "running" and body["live"] is False
