"""Phase 3: the two pre-flight commands — gate the cohort, judge the scale."""

import json
import shutil
import types

import numpy as np
import pytest

from simcore.elicitation import assert_pinnable
from simcore.schemas import GateFailure
from simcore.ports.embed import EmbedResult
from simcore.ports.fake import FakeEmbed
from tests.boundary.cli.support import ANCHORS, BRIEF, ONTOLOGIES, REPO_ROOT, run_command, run_id_from

RUN_ID = "run-" + "0" * 25 + "3"
STARVED = REPO_ROOT / "tests" / "fixtures" / "cli-starved-coreset.json"


def gate_args(out, run_id, *extra, fake=True):
    args = ["coreset-gate", "--brief", str(BRIEF), "--n", "24", "--seed", "4021"]
    if fake:
        args.append("--fake")
    args.extend([
        "--ontologies", str(ONTOLOGIES), "--out", str(out), "--run-id", run_id, *extra,
    ])
    return args


def test_coreset_gate_writes_gates_and_manifest_and_starts_no_world(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, output = run_command(*gate_args(out, RUN_ID))
    assert code == 0, output
    run_dir = out / run_id_from(output)
    assert json.loads((run_dir / "gate-report.json").read_text())["overall"] is True
    assert json.loads((run_dir / "manifest.json").read_text())["population_seed"] == 4021
    assert not (run_dir / "trace").exists()
    assert f"artefacts: {run_dir}" in output


def test_coreset_gate_distinguishes_a_failed_gate_from_a_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, _ = run_command(*gate_args(out, RUN_ID, "--coreset-fixture", str(STARVED), "--n", "200", fake=False))
    assert code == 2
    assert json.loads((out / RUN_ID / "gate-report.json").read_text())["overall"] is False
    code, _ = run_command(*gate_args(out, RUN_ID, "--coreset-fixture", str(tmp_path / "missing.json")))
    assert code == 1


def _manifest(tmp_path):
    from tests.study_builders import population_manifest_payload

    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(population_manifest_payload()))
    return path


def replica_args(out, run_id, manifest, anchors_dir, *extra):
    return [
        "ssr-replica", "--anchors", "purchase-intent-v1", "--construct", "purchase_intent",
        "--population", str(manifest), "--fake",
        "--anchors-dir", str(anchors_dir), "--out", str(out), "--run-id", run_id, *extra,
    ]


def test_ssr_replica_reports_ladder_rank_stability_and_non_collapse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    anchors_copy = tmp_path / "anchors"
    shutil.copytree(ANCHORS, anchors_copy)
    out = tmp_path / "runs"
    code, output = run_command(*replica_args(out, RUN_ID, _manifest(tmp_path), anchors_copy))
    assert code == 2, output
    assert "verdict: FAILED" in output
    run_dir = out / run_id_from(output)
    diagnostics = json.loads((run_dir / "anchors-check.json").read_text())
    assert len(diagnostics["expected_ratings"]) == 7
    assert diagnostics["spearman_min"] < 0.8
    assert diagnostics["passed"] is False
    assert f"artefacts: {run_dir}" in output


def test_a_version_that_fails_its_check_is_reported_as_failing_and_is_not_pinned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    anchors_copy = tmp_path / "anchors"
    shutil.copytree(ANCHORS, anchors_copy)
    out = tmp_path / "runs"
    code, output = run_command(*replica_args(out, RUN_ID, _manifest(tmp_path), anchors_copy))
    assert code == 2
    assert "it is not pinned" in output
    diagnostics = json.loads((out / RUN_ID / "anchors-check.json").read_text())
    assert diagnostics["pinnable"] is False
    with pytest.raises(ValueError, match="cannot be pinned"):
        assert_pinnable("purchase-intent-v1", "purchase_intent", "v1", anchors_copy)


class _DesignedEmbed(FakeEmbed):
    """A perfect embedding model, positioned by call: anchors on a basis, the ladder
    interpolating across it, varied responses spread wide — so the real gate passes."""

    def __init__(self, **kwargs):
        super().__init__(model_id="test/designed-1")
        self._calls = 0

    def embed(self, texts):
        self._calls += 1
        basis = np.eye(16)[:5]
        if self._calls == 1:
            vectors = [basis[index % 5] for index in range(len(texts))]
        elif self._calls == 2:
            vectors = []
            for position in range(len(texts)):
                mix = np.zeros(16)
                share = position / (len(texts) - 1)
                mix[0], mix[4] = 1 - share, share
                vectors.append(mix / np.linalg.norm(mix))
        else:
            vectors = [basis[index % 5] for index in range(len(texts))]
        return EmbedResult(
            vectors=np.asarray(vectors, dtype=np.float32),
            model_id=self.model_id,
            served_model_id=self.model_id,
            normalization="l2",
            dim=16,
            costs=(),
        )


def test_ssr_replica_passes_a_version_that_clears_its_check(tmp_path, monkeypatch):
    import simcore.cli._ssr_replica as replica

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(replica, "FakeEmbed", _DesignedEmbed)
    anchors_dir = tmp_path / "anchors" / "purchase_intent"
    anchors_dir.mkdir(parents=True)
    sets = [[f"set {s} anchor {i}" for i in range(5)] for s in range(6)]
    (anchors_dir / "v9.json").write_text(json.dumps({"construct": "purchase_intent", "version": "v9", "sets": sets}))
    out = tmp_path / "runs"
    code, output = run_command(
        "ssr-replica", "--anchors", "test-set-v9", "--construct", "purchase_intent", "--anchor-version", "v9",
        "--population", str(_manifest(tmp_path)), "--fake",
        "--anchors-dir", str(tmp_path / "anchors"), "--out", str(out), "--run-id", RUN_ID,
    )
    assert code == 0, output
    assert "verdict: passed" in output
    diagnostics = json.loads((out / RUN_ID / "anchors-check.json").read_text())
    assert diagnostics["passed"] is True and diagnostics["pinnable"] is True
    assert_pinnable("test-set-v9", "purchase_intent", "v9", tmp_path / "anchors", embed_model_id="test/designed-1")


def test_a_study_says_which_anchor_version_it_runs_on(tmp_path, monkeypatch):
    """A construct holding several frozen versions refuses with "the study must say which one",
    and until now there was no way to say it: the moment a second version exists — which is what
    happens when a failing scale is superseded — no study could run at all."""
    import shutil

    monkeypatch.chdir(tmp_path)
    anchors = tmp_path / "anchors"
    shutil.copytree(ANCHORS, anchors)
    shutil.copy(anchors / "purchase_intent" / "v1.json", anchors / "purchase_intent" / "v9.json")
    (anchors / "purchase_intent" / "v9.json").write_text(
        (anchors / "purchase_intent" / "v1.json").read_text().replace('"v1"', '"v9"'))

    out = tmp_path / "runs"
    base = ["concepts", "run", str(BRIEF), "--fake", "--ontologies", str(ONTOLOGIES),
            "--anchors", str(anchors), "--out", str(out), "--n", "24", "--horizon", "2"]
    code, output = run_command(*base, "--run-id", "run-" + "0" * 24 + "20")
    assert code == 2
    assert "v1" in output and "v9" in output

    code, output = run_command(*base, "--run-id", "run-" + "0" * 24 + "21",
                               "--anchor-version", "purchase_intent=v9")
    assert code == 0, output


def test_a_study_says_which_shards_it_draws_from(tmp_path, monkeypatch):
    """The release is ten shards and a draw needs a fraction of one. Demanding every shard the
    manifest lists makes a study wait on gigabytes it will never read, and there was no way to
    say which ones it draws from."""
    from simcore.cli._study import shards_from

    assert shards_from(types.SimpleNamespace(shards=None)) is None
    assert shards_from(types.SimpleNamespace(shards="0000,0004")) == [
        "data/persona-1m-0000.parquet", "data/persona-1m-0004.parquet"]
    assert shards_from(types.SimpleNamespace(shards="data/persona-1m-0009.parquet")) == [
        "data/persona-1m-0009.parquet"]
    with pytest.raises(GateFailure, match="shard"):
        shards_from(types.SimpleNamespace(shards="  "))


def test_a_study_says_which_persona_sources_it_admits(tmp_path):
    """The release carries synthetic rows beside the measured ones, and a persona may not have
    synthesized demographics: a draw that reaches them is refused by the `Population` contract,
    after the whole draw is built. A study admits sources deliberately, and could not say so."""
    from simcore.cli._study import sources_from

    assert sources_from(types.SimpleNamespace(sources=None)) is None
    assert sources_from(types.SimpleNamespace(sources="wiki,gss")) == frozenset({"wiki", "gss"})
    with pytest.raises(GateFailure, match="source"):
        sources_from(types.SimpleNamespace(sources="wiki,nosuchsource"))
    with pytest.raises(GateFailure, match="source"):
        sources_from(types.SimpleNamespace(sources=" "))


def test_a_study_says_which_channels_spread_and_when_it_surveys(tmp_path, monkeypatch):
    """Channels, survey waves and launch reach are scenario content (ADR 0048): a study says
    which channels spread information and when purchase intent is measured, and the engine
    refuses a launch reach on anything but word of mouth alone."""
    from simcore.cli._study import assemble_scenario, parse_channels
    from simcore.brief import load_brief

    pack = load_brief(BRIEF, ONTOLOGIES)
    default = assemble_scenario(pack, variant_id="v1", name="n", description="d")
    assert set(default.channels) == set() and default.survey_every == 1 and default.launch_reach == 0.10
    spread = assemble_scenario(
        pack, variant_id="v1", name="n", description="d",
        channels=["social_feed", "forum"], survey_every=2,
    )
    assert {channel.value for channel in spread.channels} == {"social_feed", "forum"}
    assert spread.survey_every == 2
    assert parse_channels("") == [] and parse_channels("social_feed,wom") == ["social_feed", "wom"]
    with pytest.raises((GateFailure, ValueError)):
        parse_channels("carrier_pigeon")
    with pytest.raises((GateFailure, ValueError)):
        assemble_scenario(
            pack, variant_id="v1", name="n", description="d",
            channels=["social_feed"], launch_reach=0.2,
        )


def test_a_pinned_scale_can_actually_be_scored_with():
    """`anchor_pins` hands the agent the hashes it scores against, and both `_pinned` and
    `resolve_anchors` look them up by anchor set id — `resolve_anchors` says so outright.
    Keyed by construct instead, a passing scale pinned cleanly into the run configuration and
    then every turn recorded `unpinned_anchors`: 252 real answers kept, not one scored."""
    from pathlib import Path

    from simcore.agent import AgentConfig
    from simcore.agent._intent import PURCHASE_CONSTRUCT, _pinned
    from simcore.brief import load_brief
    from simcore.cli._study import anchor_pins

    pack = load_brief(REPO_ROOT / "examples" / "protein_water_persona1m.yaml", ONTOLOGIES)
    set_hashes, set_ids, versions, hashes = anchor_pins(
        pack, REPO_ROOT / "anchors", embed_pin="amazon.titan-embed-text-v2:0",
        chosen={"purchase_intent": "v2"})
    assert set_ids[PURCHASE_CONSTRUCT] == "purchase-intent-v1"
    assert versions[PURCHASE_CONSTRUCT] == "v2"
    # The hashes the scorer resolves against are keyed the way the scorer looks them up.
    assert set(hashes) <= set(set_hashes), "anchor hashes are keyed by anchor set id"
    assert set_ids[PURCHASE_CONSTRUCT] in hashes

    cfg = AgentConfig(
        run_seed=4021, anchor_set_ids=set_ids, anchor_versions=versions, anchor_hashes=hashes,
        anchors_dir=str(REPO_ROOT / "anchors"), category=pack.brief.product.category)
    assert _pinned(cfg), "a scale that passed its check must be usable for scoring"
