"""Phase 3: trust, stated once.

The run's calibration appears once per study view and never on a finding; the
trust page shows the ladder and what the next rung requires without an unearned
accuracy number; unmeasured quantities render their reason where the number
would have been; forced runs say so; nothing writes or overrides a trust level;
a finding's confidence is never presented as calibration.
"""

import json
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_a_report_states_trust_once_and_no_finding_carries_one(tmp_path, monkeypatch):
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "73"
    code, output = run_command(*fake_args(out, run_id))
    assert code == 0, output
    report = json.loads((out / run_id / "report.json").read_text())
    assert report["trust"]["level"] == "uncalibrated"
    assert report["trust"]["caveats"]
    for finding in report["findings"]:
        assert "trust" not in finding and "calibration" not in finding
        assert finding["confidence"] in ("low", "medium", "high")
        assert finding["disconfirming_test"].strip()


def test_levels_above_uncalibrated_require_evidence_meeting_the_floors():
    from simcore.analysis import trust_statement

    assert trust_statement().level.value == "uncalibrated"
    try:
        trust_statement(level="category_benchmarked")
    except ValueError:
        pass
    else:
        raise AssertionError("a level above UNCALIBRATED without evidence must raise")


def test_nothing_in_the_interface_writes_or_overrides_a_trust_level():
    pages = list((FRONTEND / "app").rglob("*.tsx")) + [(FRONTEND / "components" / "ui.tsx")]
    forbidden = ("setTrust", "set_trust", "trust_level=", "trustLevel=", "method=\"POST\"")
    for page in pages:
        text = page.read_text()
        for marker in forbidden:
            assert marker not in text, f"{page.name} writes trust: {marker!r}"
        for line in text.splitlines():
            lowered = line.lower()
            if "forced_inputs" in lowered:
                continue
            assert not any(control in lowered for control in ("<input", "<select", "<textarea")) or "trust" not in lowered, (
                f"{page.name} takes a trust input: {line.strip()[:100]}"
            )


def test_every_study_view_states_the_calibration_exactly_once():
    """`TrustLine` is the one statement per view; the report states it in its header."""
    for page in ("run", "atlas", "cohort", "trace"):
        text = (FRONTEND / "app" / page / "page.tsx").read_text()
        assert text.count("<TrustLine") == 1, f"{page} states calibration {text.count('<TrustLine')} times"
    report = (FRONTEND / "app" / "report" / "page.tsx").read_text()
    assert "<TrustLine" not in report
    assert "r.trust.level" in report and "r.trust.caveats" in report


def test_an_unmeasured_quantity_renders_its_reason_where_the_number_would_be():
    for page, markers in (
        ("run", ("unmeasured_reason", "polarization_reason")),
        ("atlas", ("unmeasured_reason", "polarization_reason")),
        ("report", ("unmeasured_reason",)),
        ("calibration", ("What earns it", "CalibrationRef")),
    ):
        text = (FRONTEND / "app" / page / "page.tsx").read_text()
        for marker in markers:
            assert marker in text, f"{page} never renders {marker!r}"


def test_a_forced_run_says_so():
    text = (FRONTEND / "app" / "report" / "page.tsx").read_text()
    assert "forced_from" in text and "forced_inputs" in text
