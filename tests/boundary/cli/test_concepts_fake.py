"""Phase 1: `concepts run --fake` — from a clean checkout to a report, with nothing required."""

import json
from collections import Counter

from simcore.schemas import EventFilter, VerbatimGrouping
from simcore.trace import TraceStore
from tests.boundary.cli.support import fake_args, run_command, run_id_from

RUN_ID = "run-" + "0" * 25 + "1"


def _run(tmp_path, monkeypatch, run_id=RUN_ID, out="runs", **overrides):
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / out
    code, output = run_command(*fake_args(out_dir, run_id, **overrides))
    assert code == 0, output
    printed = run_id_from(output)
    assert printed == run_id
    return out_dir / run_id, output


def test_fake_writes_both_report_formats_into_a_run_named_directory(tmp_path, monkeypatch):
    run_dir, _ = _run(tmp_path, monkeypatch)
    assert (run_dir / "report.md").read_text().strip()
    assert json.loads((run_dir / "report.json").read_text())["contract_version"] == "1.1.0"
    assert run_dir.parent.name == "runs" and run_dir.name == RUN_ID


def test_fake_needs_no_key_no_corpus_and_no_network(tmp_path, monkeypatch):
    """The suite refuses every network connection (see tests/conftest.py), so completing
    this run proves the fake path reaches none; pointing HOME at scratch proves it reads
    no cached corpus and no credentials."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    run_dir, _ = _run(tmp_path, monkeypatch)
    assert not (tmp_path / "home").exists()
    data = json.loads((run_dir / "report.json").read_text())
    pins = {entry["role"]: entry["model_id"] for entry in data["method"]["pins"]}
    assert pins["tier_a"].startswith("fake/") and pins["embed"].startswith("fake/")


def test_the_printed_run_id_matches_the_artefacts_and_the_registry(tmp_path, monkeypatch):
    run_dir, output = _run(tmp_path, monkeypatch)
    data = json.loads((run_dir / "report.json").read_text())
    assert data["run_id"] == RUN_ID
    store = TraceStore(run_dir / "trace")
    entry = store.registry.entry(RUN_ID)
    assert entry is not None and entry.status.value == "completed"
    assert f"artefacts: {run_dir}" in output


def test_the_whole_pipeline_runs_with_no_module_stubbed(tmp_path, monkeypatch):
    """Population, world, agent, runner, trace, analysis and report all run for real —
    only the inference and corpus ports are the declared `--fake` doubles."""
    run_dir, _ = _run(tmp_path, monkeypatch)
    assert json.loads((run_dir / "gate-report.json").read_text())["overall"] is True
    assert json.loads((run_dir / "manifest.json").read_text())["population_seed"] == 4021
    store = TraceStore(run_dir / "trace")
    world_ids = store.world_ids(RUN_ID)
    assert len(world_ids) == 1
    kinds = Counter(
        event.payload.kind
        for world_id in world_ids
        for event in store.view(RUN_ID, world_id).events(EventFilter())
    )
    assert kinds["turn"] > 0
    verbatims = [
        record.text
        for world_id in world_ids
        for group in store.view(RUN_ID, world_id).verbatims(VerbatimGrouping.PERSONA)
        for record in group.records
    ]
    assert verbatims and all(text == "I would try it after training" for text in verbatims)
    full = json.loads((run_dir / "digest.json").read_text())
    assert sum(entry["turn_count"] for entry in full["digests"]) == kinds["turn"]
    data = json.loads((run_dir / "report.json").read_text())
    # Every fake verbatim is favourable, so since ADR 0053 none is an objection: the report is whole without one.
    assert isinstance(data["findings"], list) and len(data["digests"]) == len(world_ids)
    assert not [f for f in data["findings"] if f["kind"] == "objection"]


def test_two_fake_runs_under_one_seed_produce_identical_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first, _ = _run(tmp_path, monkeypatch, run_id="run-" + "0" * 25 + "1", out="first")
    second, _ = _run(tmp_path, monkeypatch, run_id="run-" + "0" * 25 + "1", out="second")
    assert (first / "report.md").read_bytes() == (second / "report.md").read_bytes()
    assert (first / "report.json").read_bytes() == (second / "report.json").read_bytes()


def test_a_fake_study_long_enough_to_reflect_still_completes(tmp_path, monkeypatch):
    """Reflection fires on a jittered cadence, so a short study never reaches it. The stub
    persona knew two prompt shapes — a reaction and a probe — and a reflection is a third:
    the first study long enough to consolidate died with `KeyError: 'shown'`."""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "16"
    code, output = run_command(*fake_args(out, run_id, horizon=6))
    assert code == 0, output
    assert (out / run_id / "report.md").is_file()


def test_checking_the_budget_does_not_cost_the_record(tmp_path, monkeypatch):
    """The ladder tests the budget once per tick per world. Deriving the figure from the trace
    each time read every event of every world, so a longer horizon or a second seed multiplied
    the reading: 731 events for one world over three ticks, 17,584 for two worlds over six."""
    import simcore.cli._study as study

    monkeypatch.chdir(tmp_path)
    reads = {"calls": 0}
    original = study.StoreTrace.all_events

    def counted(self):
        reads["calls"] += 1
        return original(self)

    monkeypatch.setattr(study.StoreTrace, "all_events", counted)
    code, output = run_command(*fake_args(tmp_path / "runs", "run-" + "0" * 24 + "17",
                                          horizon=6, seeds="4021,917731"))
    assert code == 0, output
    # Once to prime the run's meter, once to record what it spent — not once per tick per world.
    assert reads["calls"] <= 4, reads
