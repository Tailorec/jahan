"""Phase 2: exit codes — a shell can branch on what happened."""

import ast
import json
from pathlib import Path

import pytest

import simcore.cli.__main__ as cli_main
from simcore.cli._errors import EXIT_CODES, exit_code_for, report_error
from simcore.runner import ResumeRefused
from simcore.schemas.errors import BudgetExhausted, GateFailure, SchemaVersionError, SimError
from tests.boundary.cli.support import REPO_ROOT, fake_args, run_command

RUN_ID = "run-" + "0" * 25 + "2"
STARVED = REPO_ROOT / "tests" / "fixtures" / "cli-starved-coreset.json"


def test_each_mapped_exception_class_produces_its_documented_exit_code(capsys):
    assert report_error(SimError("broke")) == 1
    assert report_error(GateFailure("no")) == 2
    assert report_error(BudgetExhausted("empty")) == 3
    assert report_error(SchemaVersionError("moved")) == 5
    assert capsys.readouterr().err.count("error: ") == 4


def test_an_unmapped_exception_exits_1_and_prints_what_happened(capsys):
    assert report_error(ValueError("boom")) == 1
    assert "boom" in capsys.readouterr().err


def test_a_new_exception_class_without_a_mapping_inherits_its_parents():
    class NewGateProblem(GateFailure):
        pass

    assert exit_code_for(NewGateProblem("new")) == 2
    assert exit_code_for(SimError("new")) == 1


def test_the_mapping_lives_in_one_place():
    assert set(EXIT_CODES) == {SimError, GateFailure, BudgetExhausted, SchemaVersionError}
    assert list(EXIT_CODES.values()) == [1, 2, 3, 5]


ENGINE_ERROR_BASES = {
    "SimError",
    "GateFailure",
    "BudgetExhausted",
    "SchemaVersionError",
    "ResumeRefused",
    "TraceError",
}


def _sim_error_subclasses() -> set[str]:
    found = set()
    for path in sorted((REPO_ROOT / "simcore").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                    if name in ENGINE_ERROR_BASES:
                        found.add(node.name)
    return found


def test_every_engine_exception_is_mapped_by_class():
    """A new exception class without a mapping breaks this test: map it in `_errors` first."""
    assert _sim_error_subclasses() == {
        "GateFailure",
        "BudgetExhausted",
        "SchemaVersionError",
        "ResumeRefused",
        "TraceError",
        "DuplicateSequenceError",
        "DuplicateEntryError",
        "FinalizedError",
        "UnknownRunError",
        "UnknownWorldError",
    }
    assert exit_code_for(ResumeRefused("inputs", "a", "b")) == 1
    from simcore.trace import TraceError

    assert exit_code_for(TraceError("refused")) == 1


@pytest.mark.parametrize(
    ("error", "code"),
    [(GateFailure("no"), 2), (BudgetExhausted("empty"), 3), (SchemaVersionError("moved"), 5), (ValueError("boom"), 1)],
    ids=["gate", "budget", "contract", "unmapped"],
)
def test_main_routes_exceptions_through_the_mapping(monkeypatch, error, code):
    def raiser(argv):
        raise error

    monkeypatch.setattr(cli_main, "cmd_concepts_run", raiser)
    assert cli_main.main(["concepts", "run", "brief.yaml"]) == code


def test_a_failed_gate_exits_2_and_writes_the_gate_report_that_explains_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, output = run_command(
        *fake_args(out, RUN_ID, fake=False, coreset_fixture=str(STARVED), n="200"),
    )
    assert code == 2
    assert "distribution gates" in output or "gates" in output
    report = json.loads((out / RUN_ID / "gate-report.json").read_text())
    assert report["overall"] is False
    failed = [result["attribute"] for result in report["results"] if not result["passed"]]
    assert failed


def test_an_exhausted_budget_exits_3_and_keeps_the_completed_worlds_artefacts(tmp_path, monkeypatch):
    from simcore.cli import _fake
    from simcore.schemas import Completion

    original = _fake.RoleFakeChat._one

    def pricey(self, request):
        outcome = original(self, request)
        if isinstance(outcome, Completion):
            outcome = outcome.model_copy(update={"cost": outcome.cost.model_copy(update={"cost": 50.0})})
        return outcome

    monkeypatch.setattr(_fake.RoleFakeChat, "_one", pricey)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    # A wave costs a turn per persona per tick, tick 0 included: 24 personas × 3 ticks × $50
    # is $3600 a world. Inside $4000 the first world completes and the second pauses before
    # the wave it cannot cover, leaving one completed world and one partial one.
    code, output = run_command(*fake_args(out, RUN_ID, horizon="3", budget="4000", seeds="4021,917731"))
    assert code == 3, output
    assert "paused" in output
    run_dir = out / RUN_ID
    assert (run_dir / "report.md").read_text().strip()
    assert (run_dir / "report.json").is_file()
    result = json.loads((run_dir / "result.json").read_text())
    assert {outcome["status"] for outcome in result["outcomes"]} == {"completed", "partial"}
    assert any("pause" in rung or "unaffordable" in rung for outcome in result["outcomes"] for rung in outcome["rungs"])


def test_a_usage_error_is_not_mistaken_for_a_failed_gate():
    """argparse exits 2 on a malformed command line, which is the code this CLI documents for a
    failed gate. A shell branching on 2 would read a mistyped flag as a population that failed
    its distribution gates."""
    for argv in (["concepts", "run"], ["concepts", "run", "brief.yaml", "--nope"], ["sweep", "run"]):
        code, output = run_command(*argv)
        assert code == 1, f"{argv} exited {code}"
        assert "usage" in output.lower()


def test_help_exits_zero():
    for argv in (["--help"], ["concepts", "run", "--help"]):
        code, _ = run_command(*argv)
        assert code == 0
