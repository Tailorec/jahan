"""Launching any study from the interface, not only a fake one.

The first real study run against a partly cached corpus could not be launched from the interface:
the launch route passed `--model` and `--embed-model` and nothing else, so a real launch demanded all ten
shards and died on the first one that was not cached; the gate route carried no model pins, so a real
draw could not be previewed at all; and the anchor version defaulted to the one version that fails its own
check, so a purchase-intent study launched with no version named scored nothing. Every input the command
line takes for a study now travels from a form, is refused before a process starts when it is wrong, and
the corpus and the anchors are offered from what is actually there — never as a filesystem path.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simcore.web import create_app

REPO = Path(__file__).resolve().parents[3]
BRIEF = (REPO / "examples" / "protein_water.yaml").read_text()
EVIDENCE = json.loads((REPO / "examples" / "protein_water.yaml.evidence.json").read_text())

REAL = {
    "brief_yaml": BRIEF, "evidence_json": EVIDENCE, "fake": False,
    "model": "amazon.nova-micro-v1:0", "embed_model": "amazon.titan-embed-text-v2:0",
}


def _client(tmp_path: Path, **kwargs):
    from fastapi.testclient import TestClient

    settings = dict(
        runs_dir=tmp_path / "runs", ontology_dir=REPO / "ontologies", briefs_dir=REPO / "examples",
        anchors_dir=REPO / "anchors", engine_root=REPO,
    )
    settings.update(kwargs)
    return TestClient(create_app(**settings))


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("SIMCORE_INFERENCE_BASE_URL", "http://gateway.invalid:4000/v1")


@pytest.fixture
def launched(monkeypatch):
    """Study starts, recorded rather than spawned: no process, no model, no network."""
    started: list[list[str]] = []
    monkeypatch.setattr("simcore.web.app.lifecycle.launch", lambda run_id, argv, *a, **k: started.append(list(argv)))
    return started


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


# --- the study's own inputs travel to the command ---------------------------------------------------


def test_a_real_study_carries_its_corpus_seed_and_prices_to_the_command(tmp_path, endpoint, launched):
    response = _client(tmp_path).post("/api/runs", json={
        **REAL, "n": 500, "horizon": 3, "elicits": "purchase", "anchor_versions": ["purchase_intent=v2"],
        "shards": ["0000", "0004", "0005"], "sources": ["wiki", "gss", "amazon", "stackoverflow"],
        "population_seed": 4022, "price_chat_in": 0.035, "price_chat_out": 0.14, "price_embed_in": 0.02,
        "validation": "Interview 20 parents before building anything.",
    })
    assert response.status_code == 202, response.text
    (argv,) = launched
    assert _flag(argv, "--shards") == "0000,0004,0005"
    assert _flag(argv, "--sources") == "wiki,gss,amazon,stackoverflow"
    assert _flag(argv, "--population-seed") == "4022"
    assert _flag(argv, "--price-chat-in") == "0.035"
    assert _flag(argv, "--price-chat-out") == "0.14"
    assert _flag(argv, "--price-embed-in") == "0.02"
    assert _flag(argv, "--validation") == "Interview 20 parents before building anything."
    assert "--fake" not in argv


def test_the_endpoint_and_the_key_still_never_travel_in_the_command(tmp_path, endpoint, launched):
    _client(tmp_path).post("/api/runs", json={**REAL, "shards": ["0000"], "sources": ["wiki"]})
    (argv,) = launched
    joined = " ".join(argv)
    assert "gateway.invalid" not in joined and "SIMCORE_INFERENCE" not in joined and "api-key" not in joined


def test_a_study_that_names_none_of_them_launches_exactly_as_before(tmp_path, launched):
    """A fake study, and any client written before these inputs existed, is unchanged."""
    _client(tmp_path).post("/api/runs", json={"brief_yaml": BRIEF, "evidence_json": EVIDENCE, "fake": True})
    (argv,) = launched
    for flag in ("--shards", "--sources", "--population-seed", "--price-chat-in", "--price-chat-out",
                 "--price-embed-in", "--validation"):
        assert flag not in argv, f"{flag} was passed although nothing named it"


# --- a wrong input is refused before anything is spawned ---------------------------------------------


@pytest.mark.parametrize(
    ("override", "mentions"),
    [
        ({"shards": ["../../etc/passwd"]}, "shard"),
        ({"shards": ["12"]}, "shard"),
        ({"shards": []}, "shard"),
        ({"sources": ["nosuchsource"]}, "source"),
        ({"sources": []}, "source"),
        ({"population_seed": -1}, "population_seed"),
        ({"price_chat_in": 0.035}, "price"),
        ({"price_chat_out": 0.14}, "price"),
        ({"price_chat_in": -1.0, "price_chat_out": 0.14}, "price"),
        ({"price_embed_in": -0.02}, "price"),
        ({"channel": "carrier_pigeon"}, "channel"),
    ],
)
def test_a_wrong_input_is_refused_before_a_process_starts(tmp_path, endpoint, launched, override, mentions):
    response = _client(tmp_path).post("/api/runs", json={**REAL, **override})
    assert response.status_code == 422, response.text
    assert mentions in response.text.lower()
    assert launched == [], "a process was started for an input that was refused"
    assert [c for c in (tmp_path / "runs").glob("run-*") if (c / "trace").exists()] == []


def test_every_channel_the_engine_has_can_be_named(tmp_path, endpoint, launched):
    from simcore.schemas import Channel

    client = _client(tmp_path)
    for channel in Channel:
        assert client.post("/api/runs", json={**REAL, "channel": channel.value}).status_code == 202
    assert len(launched) == len(list(Channel))


# --- the population gate can reach a real corpus ---------------------------------------------------


@pytest.fixture
def gate_calls(monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="error: recorded, not run")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_a_real_gate_carries_its_pins_and_its_corpus_choices(tmp_path, endpoint, gate_calls):
    response = _client(tmp_path).post("/api/gate", json={
        "brief_yaml": BRIEF, "evidence_json": EVIDENCE, "n": 300, "seed": 4022, "fake": False,
        "model": "amazon.nova-micro-v1:0", "embed_model": "amazon.titan-embed-text-v2:0",
        "shards": ["0000", "0004"], "sources": ["wiki", "gss"],
    })
    assert response.status_code == 200, response.text
    (argv,) = gate_calls
    assert "--fake" not in argv
    assert _flag(argv, "--model") == "amazon.nova-micro-v1:0"
    assert _flag(argv, "--embed-model") == "amazon.titan-embed-text-v2:0"
    assert _flag(argv, "--shards") == "0000,0004"
    assert _flag(argv, "--sources") == "wiki,gss"
    assert _flag(argv, "--seed") == "4022"


def test_a_real_gate_without_pins_is_refused_by_the_api_not_by_a_subprocess(tmp_path, endpoint, gate_calls):
    response = _client(tmp_path).post("/api/gate", json={"brief_yaml": BRIEF, "fake": False})
    assert response.status_code == 422
    assert "model" in response.text.lower()
    assert gate_calls == []


def test_a_real_gate_without_an_endpoint_says_so(tmp_path, monkeypatch, gate_calls):
    monkeypatch.delenv("SIMCORE_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    response = _client(tmp_path).post("/api/gate", json={
        "brief_yaml": BRIEF, "fake": False, "model": "m", "embed_model": "e"})
    assert response.status_code == 409
    assert "endpoint" in response.text.lower()
    assert gate_calls == []


def test_a_fake_gate_is_unchanged(tmp_path, gate_calls):
    _client(tmp_path).post("/api/gate", json={"brief_yaml": BRIEF, "evidence_json": EVIDENCE, "n": 24})
    (argv,) = gate_calls
    assert "--fake" in argv and "--model" not in argv and "--shards" not in argv


# --- the corpus is offered from what is actually cached, never as a path ------------------------------


def _corpus(root: Path, cached: tuple[str, ...]) -> Path:
    corpus = root / "corpus"
    (corpus / "data").mkdir(parents=True)
    files = [{"path": f"data/persona-1m-{n}.parquet", "rows": 100000, "bytes": 1000, "sha256": "0" * 64}
             for n in ("0000", "0004", "0009")]
    (corpus / "manifest.json").write_text(json.dumps({
        "files": files,
        "sources": {"wiki": 323438, "gss": 63532, "stackoverflow": 113120, "synthetic": 400000},
    }))
    for name in cached:
        (corpus / "data" / f"persona-1m-{name}.parquet").write_bytes(b"")
    return corpus


def test_the_corpus_endpoint_says_which_shards_are_cached_and_which_sources_exist(tmp_path):
    corpus = _corpus(tmp_path, cached=("0000", "0004"))
    body = _client(tmp_path, corpus_dir=corpus).get("/api/corpus").json()
    assert body["available"] is True
    by_id = {shard["id"]: shard for shard in body["shards"]}
    assert set(by_id) == {"0000", "0004", "0009"}
    assert [by_id[i]["cached"] for i in ("0000", "0004", "0009")] == [True, True, False]
    assert by_id["0000"]["rows"] == 100000
    assert set(body["sources"]) == {"wiki", "gss", "stackoverflow", "synthetic"}
    assert body["sources"]["gss"] == 63532
    assert "synthetic" not in body["measured_sources"]
    assert set(body["measured_sources"]) == {"wiki", "gss", "stackoverflow"}


def test_the_corpus_endpoint_returns_no_filesystem_path(tmp_path):
    corpus = _corpus(tmp_path, cached=("0000",))
    text = _client(tmp_path, corpus_dir=corpus).get("/api/corpus").text
    assert str(tmp_path) not in text and str(corpus) not in text
    assert ".parquet" not in text and "/" not in text.replace("\\/", "")


def test_no_corpus_is_stated_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "nothing-here"))
    body = _client(tmp_path, corpus_dir=tmp_path / "absent").get("/api/corpus").json()
    assert body["available"] is False
    assert body["shards"] == []


# --- the anchors are offered with their verdicts, and the default is one that passed ------------------


def _anchors(tmp_path: Path) -> Path:
    anchors = tmp_path / "anchors"
    shutil.copytree(REPO / "anchors", anchors)
    return anchors


def test_the_anchors_endpoint_lists_each_version_with_its_verdict(tmp_path):
    body = _client(tmp_path, anchors_dir=_anchors(tmp_path)).get("/api/anchors").json()
    versions = {(a["construct"], a["version"]): a for a in body["anchors"]}
    assert versions[("purchase_intent", "v1")]["passed"] is False
    assert versions[("purchase_intent", "v2")]["passed"] is True
    assert versions[("purchase_intent", "v2")]["embed_model_id"] == "amazon.titan-embed-text-v2:0"
    assert "/" not in json.dumps(body).replace("amazon.titan-embed-text-v2:0", "")


def test_the_default_scale_is_the_newest_version_that_passed_its_check(tmp_path):
    """It was hard-coded to v1, which fails: a study that named no version silently scored nothing."""
    anchors = _anchors(tmp_path)
    body = _client(tmp_path, anchors_dir=anchors).get("/api/anchors").json()
    assert body["defaults"] == ["purchase_intent=v2"]
    # A newer version that has not passed is not chosen over one that has.
    shutil.copy(anchors / "purchase_intent" / "v2.json", anchors / "purchase_intent" / "v3.json")
    body = _client(tmp_path, anchors_dir=anchors).get("/api/anchors").json()
    assert body["defaults"] == ["purchase_intent=v2"]


def test_a_version_edited_after_its_check_passed_is_not_offered_as_a_default(tmp_path):
    anchors = _anchors(tmp_path)
    path = anchors / "purchase_intent" / "v2.json"
    edited = json.loads(path.read_text())
    edited["sets"][0][0] = "I would not ever buy this."
    path.write_text(json.dumps(edited))
    body = _client(tmp_path, anchors_dir=anchors).get("/api/anchors").json()
    assert body["defaults"] == []
    v2 = next(a for a in body["anchors"] if a["version"] == "v2")
    assert v2["passed"] is True and v2["unchanged_since_check"] is False


def test_a_launch_that_names_no_scale_uses_the_default_that_passed(tmp_path, endpoint, launched):
    _client(tmp_path).post("/api/runs", json={**REAL, "elicits": "purchase"})
    (argv,) = launched
    assert "purchase_intent=v2" in argv and "purchase_intent=v1" not in argv
