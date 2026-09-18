"""Phase 4: `concepts run` against a real endpoint.

The suite reaches no network and holds no credentials, so a live endpoint run cannot
happen here by design. What can be proven offline is proven: the real backend pins the
named models and passes the environment's endpoint configuration through untouched,
a study with no measurable adoption still exits 0 with the reason stated, and a resume
the inputs moved refuses by name. The remaining step — the same code path with live
ports — is the documented manual command, not a CI target.
"""

import json
import shutil
import types

from simcore.brief import load_brief
from simcore.cli._study import assemble_backend
from simcore.runner import ENGINE_VERSION
from tests.boundary.cli.support import ANCHOR_VERSION, ANCHORS, BRIEF, ONTOLOGIES, REPO_ROOT, fake_args, run_command, run_id_from

RUN_ID = "run-" + "0" * 25 + "4"


def real_args(**overrides):
    args = {
        "fake": False,
        "coreset_fixture": None,
        "population_seed": 4021,
        "model": "ministral-3-8b",
        "embed_model": "titan-embed-v2",
        "price_chat_in": None,
        "price_chat_out": None,
        "price_embed_in": None,
        "cache": None,
    }
    args.update(overrides)
    return types.SimpleNamespace(**args)


def test_a_real_run_without_a_cached_corpus_refuses_with_the_fetch_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    argv = fake_args(out, RUN_ID, fake=False, model="ministral-3-8b", embed_model="titan-embed-v2",
                     cache=str(tmp_path / "empty-cache"))
    code, output = run_command(*argv)
    assert code == 1
    assert "fetch it with" in output


def test_a_study_with_no_measurable_adoption_exits_0_and_reports_why(tmp_path, monkeypatch):
    """No anchor version passes its check, so no turn scores intent — the study the
    engine can currently do. The command still exits 0 and the report says why."""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, _ = run_command(*fake_args(out, RUN_ID))
    assert code == 0
    markdown = (out / RUN_ID / "report.md").read_text()
    assert "Adoption: unmeasured" in markdown
    digest = json.loads((out / RUN_ID / "digest.json").read_text())
    assert digest["digests"][0]["adoption"] is None
    assert digest["digests"][0]["unmeasured_reason"]


def test_the_method_disclosure_names_pins_seeds_and_engine_commit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, _ = run_command(*fake_args(out, RUN_ID, seeds="4021,917731"))
    assert code == 0
    data = json.loads((out / RUN_ID / "report.json").read_text())
    pins = {entry["role"]: entry["model_id"] for entry in data["method"]["pins"]}
    assert pins == {"tier_a": "fake/tier-a-1", "tier_b": "fake/tier-b-1", "embed": "fake/embed-1"}
    assert data["method"]["seeds"] == [4021, 917731]
    assert data["engine_commit"] == ENGINE_VERSION
    markdown = (out / RUN_ID / "report.md").read_text()
    assert ENGINE_VERSION in markdown and "4021" in markdown


def test_a_resume_refused_by_changed_inputs_names_what_moved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brief = tmp_path / "brief.yaml"
    shutil.copy(BRIEF, brief)
    shutil.copy(REPO_ROOT / "examples" / "protein_water.yaml.evidence.json", tmp_path / "brief.yaml.evidence.json")
    out = tmp_path / "runs"
    base = ["concepts", "run", str(brief), "--fake", "--ontologies", str(ONTOLOGIES),
            "--anchors", str(ANCHORS), "--anchor-version", ANCHOR_VERSION, "--out", str(out), "--run-id", RUN_ID, "--n", "24", "--horizon", "2"]
    code, _ = run_command(*base)
    assert code == 0

    text = brief.read_text().replace(
        "Respondents distinguish clear from milky protein formats",
        "Respondents distinguish clear from milky protein formats, mostly",
    )
    brief.write_text(text)
    code, output = run_command(*base)
    assert code == 1
    assert "resume refused" in output and "brief" in output


def test_the_command_passes_endpoint_configuration_through_untouched(tmp_path, monkeypatch):
    """The environment configures how a run executes, never what it measured: the base
    URL, key and budgets reach the client exactly as stated."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMCORE_INFERENCE_BASE_URL", "http://127.0.0.1:4000/v1")
    monkeypatch.setenv("SIMCORE_INFERENCE_API_KEY", "key-123")
    monkeypatch.setenv("SIMCORE_INFERENCE_TIMEOUT_S", "12.5")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("simcore.ports.hf.HfCoresetSource", lambda **kwargs: ("coreset", kwargs))
    pack = load_brief(BRIEF, ONTOLOGIES)
    client, same, coreset, pins, embed_pin = assemble_backend(pack, real_args())
    try:
        assert same is client
        assert client.settings.base_url == "http://127.0.0.1:4000/v1"
        assert client.settings.api_key == "key-123"
        assert client.settings.timeout_s == 12.5
        assert pins["tier_a"]["model_id"] == "ministral-3-8b"
        assert pins["embed"]["model_id"] == "titan-embed-v2"
        assert embed_pin == "titan-embed-v2"
        assert coreset[0] == "coreset"
    finally:
        closers = [name for name in ("aclose", "close") if hasattr(client, name)]
        for name in closers:
            try:
                result = getattr(client, name)()
                if hasattr(result, "__await__"):
                    import asyncio

                    asyncio.run(result)
            except Exception:
                pass


def test_a_forced_resume_is_recorded_in_the_registry_and_marked_in_the_report(tmp_path, monkeypatch):
    """ADR 0036: a forced resume proceeds, is recorded in the registry, and marks the run's
    results. The runner recorded it by calling `mark_forced`, which only the in-memory registry
    of its own test suite has — against the real one a forced run left no trace of being forced."""
    monkeypatch.chdir(tmp_path)
    brief = tmp_path / "brief.yaml"
    shutil.copy(BRIEF, brief)
    shutil.copy(REPO_ROOT / "examples" / "protein_water.yaml.evidence.json", tmp_path / "brief.yaml.evidence.json")
    out = tmp_path / "runs"
    run_id = "run-" + "0" * 24 + "18"
    base = ["concepts", "run", str(brief), "--fake", "--ontologies", str(ONTOLOGIES),
            "--anchors", str(ANCHORS), "--anchor-version", ANCHOR_VERSION, "--out", str(out), "--run-id", run_id, "--n", "24", "--horizon", "2"]
    assert run_command(*base)[0] == 0

    brief.write_text(brief.read_text().replace(
        "Respondents distinguish clear from milky protein formats",
        "Respondents distinguish clear from milky protein formats, mostly",
    ))
    assert run_command(*base)[0] == 1
    code, output = run_command(*base, "--force")
    assert code == 0, output

    from simcore.trace import TraceStore

    entry = TraceStore(out / run_id / "trace").registry.entry(run_id)
    assert entry is not None
    assert "brief" in entry.forced_inputs
    assert "forced" in (out / run_id / "report.md").read_text().lower()
    assert json.loads((out / run_id / "report.json").read_text())["forced_inputs"] == ["brief"]
