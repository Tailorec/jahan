"""Phase 5: `sweep run` — a grid of scenarios and seeds under one budget."""

import json
import shutil

from simcore.schemas import Completion
from tests.boundary.cli.support import ANCHOR_VERSION, ANCHORS, BRIEF, ONTOLOGIES, REPO_ROOT, run_command, run_id_from

RUN_ID = "run-" + "0" * 25 + "5"

SCENARIO = """\
  - variant: {{variant_id: v1baseline, name: Baseline, description: Baseline concept at the brief price, emphasized_claims: [C1]}}
    price: {{amount: {price}, currency: USD}}
    audience_weights: {{gym_regulars: 0.6, protein_dieters: 0.4}}
    tick_unit: day
    horizon_ticks: {horizon}
    interventions: []
"""


def write_grid(tmp_path, horizon=2, prices=(2.49, 2.99), name="grid.yaml"):
    shutil.copy(BRIEF, tmp_path / "protein_water.yaml")
    shutil.copy(
        REPO_ROOT / "examples" / "protein_water.yaml.evidence.json",
        tmp_path / "protein_water.yaml.evidence.json",
    )
    scenarios = "".join(SCENARIO.format(price=price, horizon=horizon) for price in prices)
    grid = tmp_path / name
    grid.write_text(f"brief: protein_water.yaml\nscenarios:\n{scenarios}seeds: [4021]\n")
    return grid


def sweep_args(grid, out, run_id, *extra, budget="42"):
    return [
        "sweep", "run", "--grid", str(grid), "--budget", budget, "--fake",
        "--ontologies", str(ONTOLOGIES), "--anchors", str(ANCHORS), "--anchor-version", ANCHOR_VERSION,
        "--out", str(out), "--run-id", run_id, "--n", "24", *extra,
    ]


def test_sweep_runs_the_grid_as_one_run_under_one_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path)
    out = tmp_path / "runs"
    code, output = run_command(*sweep_args(grid, out, RUN_ID))
    assert code == 0, output
    run_dir = out / run_id_from(output)
    assert (run_dir / "report.md").read_text().strip()
    assert (run_dir / "report.json").is_file()
    digest = json.loads((run_dir / "digest.json").read_text())
    assert len(digest["digests"]) == 2
    result = json.loads((run_dir / "result.json").read_text())
    assert result["registry"]["config"]["budget"] == {"max_cost": 42.0, "currency": "USD"}
    assert len(result["outcomes"]) == 2
    assert {outcome["status"] for outcome in result["outcomes"]} == {"completed"}


def test_per_cell_summaries_carry_each_cells_seeds_and_their_spread(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path)
    out = tmp_path / "runs"
    code, output = run_command(*sweep_args(grid, out, RUN_ID))
    assert code == 0, output
    run_dir = out / RUN_ID
    for position in ("00", "01"):
        summary = json.loads((run_dir / f"summary-{position}.json").read_text())
        assert [entry["seed"] for entry in summary["summary"]["entries"]] == [4021]
        assert "adoption_spread" in summary["summary"] and "belief_move_spread" in summary["summary"]
    assert json.loads((run_dir / "summary-00.json").read_text())["scenario"]["price"]["amount"] == 2.49
    assert json.loads((run_dir / "summary-01.json").read_text())["scenario"]["price"]["amount"] == 2.99


def pricey(monkeypatch):
    from simcore.cli import _fake

    original = _fake.RoleFakeChat._one

    def _pricey(self, request):
        outcome = original(self, request)
        if isinstance(outcome, Completion):
            outcome = outcome.model_copy(update={"cost": outcome.cost.model_copy(update={"cost": 50.0})})
        return outcome

    monkeypatch.setattr(_fake.RoleFakeChat, "_one", _pricey)


def test_a_cell_that_ran_degraded_is_marked_in_the_output(tmp_path, monkeypatch):
    pricey(monkeypatch)
    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path, horizon=3, prices=(2.49,), name="single.yaml")
    out = tmp_path / "runs"
    # The wave the budget cannot cover pauses the cell before it: the output marks where
    # (the tick never closed) and why (the rung), with no partial wave in the trace.
    code, output = run_command(*sweep_args(grid, out, RUN_ID, budget="3000"))
    assert code == 3, output
    run_dir = out / RUN_ID
    result = json.loads((run_dir / "result.json").read_text())
    assert result["outcomes"][0]["rungs"] == ["wave_unaffordable"]


def test_a_budget_exhausted_mid_sweep_exits_3_and_keeps_completed_cells(tmp_path, monkeypatch):
    pricey(monkeypatch)
    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path, horizon=3)
    out = tmp_path / "runs"
    # As in the concepts budget test: the first cell completes inside $4000 and the second
    # pauses before the wave it cannot cover, so the completed cell keeps its summary.
    code, output = run_command(*sweep_args(grid, out, RUN_ID, budget="4000"))
    assert code == 3, output
    assert "paused" in output
    run_dir = out / RUN_ID
    assert (run_dir / "report.md").read_text().strip()
    assert (run_dir / "summary-00.json").is_file()
    assert not (run_dir / "summary-01.json").exists()
    result = json.loads((run_dir / "result.json").read_text())
    assert {outcome["status"] for outcome in result["outcomes"]} == {"completed", "partial"}


def test_rerunning_an_interrupted_sweep_completes_only_unfinished_cells(tmp_path, monkeypatch):
    from simcore.cli import _study as study

    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path, horizon=3)
    out = tmp_path / "runs"

    calls = []
    armed = {"stop": True}
    real_turns = study.agent_turns

    def flaky_turns(*args, **kwargs):
        # Tick zero invokes the agent with nothing to react to, so one cell of
        # horizon three takes three calls; the crash lands in the second cell.
        calls.append(1)
        if armed["stop"] and len(calls) > 4:
            raise RuntimeError("interrupted mid-sweep")
        return real_turns(*args, **kwargs)

    monkeypatch.setattr(study, "agent_turns", flaky_turns)
    code, _ = run_command(*sweep_args(grid, out, RUN_ID))
    assert code == 1
    from simcore.trace import TraceStore

    store = TraceStore(out / RUN_ID / "trace")
    assert len(store.world_ids(RUN_ID)) == 2

    armed["stop"] = False
    stepped: list = []
    real_world = study.World

    class CountingWorld(real_world):
        def step(self, tick, turns):
            stepped.append((self.world_id, tick))
            return super().step(tick, turns)

    monkeypatch.setattr(study, "World", CountingWorld)
    code, output = run_command(*sweep_args(grid, out, RUN_ID))
    assert code == 0, output
    result = json.loads((out / RUN_ID / "result.json").read_text())
    assert {outcome["status"] for outcome in result["outcomes"]} == {"completed"}
    # Only the interrupted cell stepped, and only from after its last closed tick.
    assert stepped
    stepped_worlds = {world_id for world_id, _ in stepped}
    assert len(stepped_worlds) == 1
    assert sorted(tick for _, tick in stepped) == [1, 2]


def test_each_version_shows_its_personas_its_own_price(tmp_path, monkeypatch):
    """ADR 0051: two versions differing only in price showed one identical concept, so no sweep could separate
    them. A persona is shown the version's description and its price."""
    from simcore.schemas import EventFilter
    from simcore.trace import TraceStore

    monkeypatch.chdir(tmp_path)
    grid = write_grid(tmp_path, prices=(2.49, 2.99))
    out = tmp_path / "runs"
    code, output = run_command(*sweep_args(grid, out, RUN_ID))
    assert code == 0, output
    view = TraceStore(out / RUN_ID / "trace").view(RUN_ID)
    concepts = {e.world_id: e.payload.stimulus.text for e in view.events(EventFilter(kinds=("stimulus_published",)))
                if e.payload.stimulus.kind.value == "concept"}
    assert len(concepts) == 2 and len(set(concepts.values())) == 2
    assert sorted(text.rsplit("Price: ", 1)[1] for text in concepts.values()) == ["2.49 USD", "2.99 USD"]
    assert all(text.startswith("Baseline concept at the brief price") for text in concepts.values())


def test_a_versions_name_changes_no_identity():
    """A label is how a person tells versions apart: naming or renaming one never makes a different world."""
    from simcore.schemas import Scenario, canonical_hash, derive_world_id
    from tests.study_builders import scenario_payload

    plain = Scenario.model_validate(scenario_payload())
    named = Scenario.model_validate({**scenario_payload(), "label": "Budget $9"})
    renamed = Scenario.model_validate({**scenario_payload(), "label": "Cheapest tier"})
    assert named.label == "Budget $9"
    assert canonical_hash(plain) == canonical_hash(named) == canonical_hash(renamed)
    assert derive_world_id(plain, 4021, "ab12" * 16) == derive_world_id(renamed, 4021, "ab12" * 16)
