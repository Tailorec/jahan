"""Phase 7: intake, and a real study.

A brief is authored and validated against the engine's own contracts before a
run can start; the assumption ledger is assembled from what the brief states
and what it leaves unstated; a study states what its personas are asked and a
purchase-intent study names its anchor version; the interface reports whether
an endpoint is configured and never accepts or displays a key.
"""

import json
from pathlib import Path

from simcore.web import create_app

REPO = Path(__file__).resolve().parents[3]
BRIEF = (REPO / "examples" / "protein_water.yaml").read_text()
EVIDENCE = json.loads((REPO / "examples" / "protein_water.yaml.evidence.json").read_text())


def _client(tmp_path: Path, **kwargs):
    from fastapi.testclient import TestClient

    return TestClient(create_app(
        runs_dir=tmp_path / "runs",
        ontology_dir=REPO / "ontologies",
        anchors_dir=REPO / "anchors",
        engine_root=REPO,
        **kwargs,
    ))


def test_a_brief_validates_with_its_assumption_ledger(tmp_path):
    client = _client(tmp_path)
    response = client.post("/api/briefs/validate", json={"brief_yaml": BRIEF, "evidence_json": EVIDENCE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["claims"] == ["C1", "C2", "C3"]
    assert body["ontology_version"] == "1.0.0"
    sources = {item["source"] for item in body["assumption_ledger"]}
    assert "assumed" in sources and "user_asserted" in sources


def test_an_invalid_brief_is_refused_before_anything_runs(tmp_path):
    client = _client(tmp_path)
    bad = BRIEF.replace("ontology_version:", "ontology_version_bogus:")
    response = client.post("/api/briefs/validate", json={"brief_yaml": bad})
    assert response.status_code == 422
    response = client.post("/api/runs", json={"brief_yaml": bad, "fake": True})
    assert response.status_code == 422
    assert [child for child in (tmp_path / "runs").iterdir() if (child / "trace").exists()] == []


def test_a_study_states_which_channels_spread_and_when_it_surveys(tmp_path):
    client = _client(tmp_path)
    run_id = client.post("/api/runs", json={
        "brief_yaml": BRIEF, "evidence_json": EVIDENCE, "fake": True,
        "n": 8, "horizon": 1, "channels": ["social_feed", "wom"], "survey_every": 1,
        "launch_reach": 0.10, "anchor_versions": ["purchase_intent=v1"],
    }).json()["run_id"]
    launch = json.loads((tmp_path / "runs" / run_id / "launch.json").read_text())
    assert "--channels" in launch["argv"] and "social_feed,wom" in launch["argv"]
    assert "--survey-every" in launch["argv"]
    assert "--anchor-version" in launch["argv"] and "purchase_intent=v1" in launch["argv"]


def test_a_real_study_without_pins_is_refused(tmp_path):
    client = _client(tmp_path)
    response = client.post("/api/runs", json={"brief_yaml": BRIEF, "fake": False})
    assert response.status_code == 422


def test_status_reports_configuration_without_values(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMCORE_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = _client(tmp_path)
    body = client.get("/api/status").json()
    assert body["endpoint_configured"] is False and body["fake_available"] is True
    assert "key" not in json.dumps(body).lower()

    monkeypatch.setenv("OPENAI_BASE_URL", "http://gateway:4000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    body = client.get("/api/status").json()
    assert body["endpoint_configured"] is True
    assert "gateway" not in json.dumps(body) and "secret" not in json.dumps(body).lower()


def test_brief_check_exits_with_the_ledger(tmp_path, monkeypatch):
    from tests.boundary.cli.support import run_command

    monkeypatch.chdir(tmp_path)
    code, output = run_command(
        "brief", "check", "--brief", str(REPO / "examples" / "protein_water.yaml"),
        "--ontologies", str(REPO / "ontologies"), "--format", "json",
    )
    assert code == 0, output
    assert json.loads(output)["valid"] is True
    code, output = run_command(
        "brief", "check", "--brief", str(REPO / "examples" / "protein_water.yaml"),
        "--ontologies", str(tmp_path),
    )
    assert code == 2
