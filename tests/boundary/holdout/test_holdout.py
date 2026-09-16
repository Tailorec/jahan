"""Phase 11: the holdout evaluation. Hide measured attitudes, project them through the production
path, and score the result against the truth and a demographic-conditional baseline — with metrics
proven to discriminate."""

import json
from collections import Counter
from pathlib import Path

import pytest

from simcore.holdout import evaluate, select_measured_rows
from simcore.holdout._evaluate import _baseline_draws
from simcore.ports.coreset import DecodedRow, _DecodedRowSource
from simcore.ports.fake import FakeChat
from simcore.schemas import BriefPack, FieldOrigin, FrozenDict

CELLS = {  # the truth the fixture is built to: attitude depends strongly on the demographic cell
    ("young", "female"): {"favor": 0.85, "neutral": 0.10, "against": 0.05},
    ("young", "male"): {"favor": 0.85, "neutral": 0.10, "against": 0.05},
    ("old", "female"): {"favor": 0.05, "neutral": 0.10, "against": 0.85},
    ("old", "male"): {"favor": 0.05, "neutral": 0.10, "against": 0.85},
}
VOCABULARY = ("favor", "neutral", "against")


def ontology() -> dict:
    return {
        "category": "beverage_protein",
        "version": "1.0.0",
        "attribute_domains": {"age": "demographic", "sex": "demographic", "att": "psychographic"},
        "conditioning_set": ["age", "sex"],
        "relevance_order": ["age", "sex", "att"],
        "anchor_sets": {"purchase_intent": "pi-beverage-v1"},
        "completion_policy": {"completable_domains": ["media"]},
        "ordinal_scales": [],
    }


def pack() -> BriefPack:
    brief = {
        "product": {"name": "Holdout", "category": "beverage_protein", "description": "A study of attitudes"},
        "price": {"amount": 1.0, "currency": "USD"},
        "claims": [{"text": "It works", "source": "user_asserted"}],
        "target_market": "everyone",
        "ontology_version": "1.0.0",
    }
    return BriefPack.model_validate({"brief": brief, "ontology": ontology()})


def fixture_rows(per_cell: int = 40, attitude: str = "att") -> list[DecodedRow]:
    rows: list[DecodedRow] = []
    index = 0
    for (age, sex), marginals in CELLS.items():
        counts = Counter()
        remaining = per_cell
        for value in VOCABULARY[:-1]:
            counts[value] = round(marginals[value] * per_cell)
            remaining -= counts[value]
        counts[VOCABULARY[-1]] = remaining
        for value, number in counts.items():
            for _ in range(number):
                index += 1
                rows.append(
                    DecodedRow(
                        row_id=f"{index:06d}",
                        source="stackoverflow",
                        values=FrozenDict({"age": age, "sex": sex, attitude: value}),
                    )
                )
    return rows


def source() -> _DecodedRowSource:
    return _DecodedRowSource(fixture_rows(), {"age": ("young", "old"), "sex": ("female", "male"), "att": VOCABULARY})


def oracle_responder(messages, template_id) -> str:
    """The perfect model: it returns the true demographic-conditional marginal as the distribution."""
    request = json.loads(messages[-1]["content"])
    answers = {}
    for persona in request["personas"]:
        key = (persona["known"]["age"], persona["known"]["sex"])
        marginals = CELLS[key]
        answers[persona["persona_id"]] = [marginals[value] for value in request["values"]]
    return json.dumps(answers, sort_keys=True)


def uniform_responder(messages, template_id) -> str:
    request = json.loads(messages[-1]["content"])
    share = 1.0 / len(request["values"])
    return json.dumps({persona["persona_id"]: [share] * len(request["values"]) for persona in request["personas"]}, sort_keys=True)


def run(responder, **overrides) -> "object":
    kwargs = {
        "hidden": ("att",),
        "inference": FakeChat(responder),
        "holdout_seed": 4021,
        "population_seed": 917731,
        "completion_temperature": 1.0,
        "pins": {"tier_a": "fake/chat"},
        "served_models": {"fake/chat": ["fake/chat-v1"]},
        "inference_label": "FakeChat",
    }
    kwargs.update(overrides)
    return evaluate(pack(), source(), fixture_rows(), **kwargs)


def test_a_fake_that_returns_the_true_conditionals_scores_at_the_baseline_and_a_uniform_one_worse():
    conditional = run(oracle_responder).attributes["att"]
    uniform = run(uniform_responder).attributes["att"]
    baseline = conditional.baseline_marginal_distance
    assert abs(conditional.marginal_distance - baseline) <= 0.06  # at the baseline
    assert uniform.marginal_distance > baseline + 0.05  # worse, decisively
    assert conditional.marginal_distance < uniform.marginal_distance
    # demographic dependence: the true conditionals recover it, uniform erases it, the baseline keeps it
    assert conditional.recovered_dependence is not None and conditional.recovered_dependence > 0.5
    assert uniform.recovered_dependence is not None and uniform.recovered_dependence < 0.25
    assert conditional.baseline_recovered_dependence is not None and conditional.baseline_recovered_dependence > 0.5


def marginal_only_responder(messages, template_id) -> str:
    """A model that ignores demographics: every persona gets the population's overall marginal."""
    request = json.loads(messages[-1]["content"])
    overall = {value: sum(cell[value] for cell in CELLS.values()) / len(CELLS) for value in request["values"]}
    return json.dumps({persona["persona_id"]: [overall[value] for value in request["values"]] for persona in request["personas"]}, sort_keys=True)


def test_the_proper_scores_rank_the_true_conditionals_above_ignoring_demographics_above_uniform():
    """Marginal distance scored a model ignoring demographics as well as the true one, and calibration scored
    uniform guessing as perfectly calibrated. Log loss and Brier reward being right and sharp at once."""
    conditional = run(oracle_responder).attributes["att"]
    ignoring = run(marginal_only_responder).attributes["att"]
    uniform = run(uniform_responder).attributes["att"]
    assert conditional.log_loss < ignoring.log_loss < uniform.log_loss
    assert conditional.brier < ignoring.brier < uniform.brier
    assert conditional.log_loss <= conditional.baseline_log_loss + 0.1  # the truth scores at the baseline
    assert ignoring.recovered_dependence is not None and ignoring.recovered_dependence < 0.25


def test_recovered_dependence_is_not_manufactured_by_sparse_cells():
    """At Stack Overflow's scale — tens of thousands of rows over hundreds of demographic cells, with the weak
    dependence real attitudes have — count-based mutual information credited uniform guessing with 64% of
    the dependence recovered and a model ignoring demographics with 69%. Both were estimation bias."""
    import numpy as np

    from simcore.holdout._evaluate import _recovered_dependence

    generator = np.random.default_rng(20260916)
    cells, rows = 880, 28000
    conditionals = generator.dirichlet(np.array([0.5, 0.3, 0.2]) * 60, size=cells)
    keys = generator.integers(0, cells, size=rows)
    truth = [VOCABULARY[generator.choice(3, p=conditionals[key])] for key in keys]
    known = [{"cell": str(key)} for key in keys]
    overall = np.array([truth.count(value) for value in VOCABULARY]) / rows

    def recovered(stated_for):
        predicted = [VOCABULARY[generator.choice(3, p=stated_for(key))] for key in keys]
        return _recovered_dependence(known, predicted, known, truth, VOCABULARY, seed="weak")

    assert recovered(lambda key: conditionals[key]) > 0.8
    assert recovered(lambda key: overall) < 0.1
    assert recovered(lambda key: np.ones(3) / 3) < 0.1


def test_the_report_records_the_pins_served_models_seeds_temperature_and_row_counts():
    report = run(oracle_responder)
    assert report.hidden == ("att",)
    assert report.holdout_seed == 4021 and report.population_seed == 917731
    assert report.completion_temperature == 1.0
    assert report.pool_rows == 160 - report.held_out_rows and report.held_out_rows > 30
    assert report.pins == {"tier_a": "fake/chat"}
    assert {k: list(v) for k, v in report.served_models.items()} == {"fake/chat": ["fake/chat-v1"]}
    assert report.inference == "FakeChat"
    restored = json.loads(report.to_json())
    assert restored["attributes"]["att"]["vocabulary"] == list(VOCABULARY)
    assert restored["attributes"]["att"]["projected_rows"] == report.held_out_rows


def test_held_out_rows_are_never_used_to_build_the_baseline():
    pool = fixture_rows()[:80]
    honest = [dict(row.values) for row in fixture_rows(per_cell=5)[80:100]]
    held_out = [
        DecodedRow(row_id=row["age"] + str(index), source="stackoverflow", values=FrozenDict(row))
        for index, row in enumerate(honest)
    ]
    # Two copies of the same held-out rows whose true attitudes disagree: the baseline must not care.
    flipped = [
        DecodedRow(row_id=row.row_id, source="stackoverflow", values=FrozenDict({**dict(row.values), "att": "against" if row.values["att"] == "favor" else "favor"}))
        for row in held_out
    ]
    _, assigned_a, _ = _baseline_draws(pool, held_out, "att", VOCABULARY, 4021, ("age", "sex"))
    _, assigned_b, _ = _baseline_draws(pool, flipped, "att", VOCABULARY, 4021, ("age", "sex"))
    assert assigned_a == assigned_b  # cell marginals come from the pool alone


def test_only_measured_attitudes_can_be_hidden():
    rows = fixture_rows(per_cell=1)
    inferred = DecodedRow(
        row_id="inferred", source="stackoverflow",
        values=FrozenDict({"age": "young", "sex": "female", "att": "favor"}),
        tiers=FrozenDict({"att": FieldOrigin.EXTRACTED}),
    )
    chosen = select_measured_rows([*rows, inferred], ["att"])
    assert inferred not in chosen
    assert len(chosen) == len(rows)


def test_the_holdout_refuses_a_sample_it_cannot_score():
    tiny = fixture_rows(per_cell=1)[:4]
    with pytest.raises(ValueError, match="rows carrying"):
        evaluate(pack(), source(), tiny, hidden=("att",), inference=FakeChat(oracle_responder), holdout_seed=1)


# --- the command ------------------------------------------------------------------------------------------


def _write_camp(tmp_path: Path) -> tuple[Path, Path, Path]:
    ontologies = tmp_path / "ontologies" / "beverage_protein"
    ontologies.mkdir(parents=True)
    (ontologies / "1.0.0.json").write_text(json.dumps(ontology()))
    brief_path = tmp_path / "holdout.yaml"
    brief_path.write_text(
        "product:\n  name: Holdout\n  category: beverage_protein\n  description: A study of attitudes\n"
        "price:\n  amount: 1.0\n  currency: USD\n"
        "claims:\n  - text: It works\n    source: user_asserted\n"
        "target_market: everyone\nontology_version: 1.0.0\n"
    )
    rows = [{"row_id": row.row_id, "source": "stackoverflow", "values": dict(row.values)} for row in fixture_rows()]
    coreset = tmp_path / "holdout_coreset.json"
    coreset.write_text(json.dumps({"vocabulary": {"age": ["young", "old"], "sex": ["female", "male"], "att": list(VOCABULARY)}, "rows": rows}))
    return brief_path, tmp_path / "ontologies", coreset


def test_the_command_runs_the_evaluation_from_one_invocation(tmp_path, capsys):
    from simcore.holdout.__main__ import main

    brief, ontologies, coreset = _write_camp(tmp_path)
    out = tmp_path / "report.json"
    assert main(["--pack", str(brief), "--ontologies", str(ontologies), "--coreset-fixture", str(coreset), "--hidden", "att", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["hidden"] == ["att"]
    assert report["attributes"]["att"]["projected_rows"] > 30
    assert report["pins"]["tier_a"] == "fake/chat"


def test_the_real_shards_are_the_endpoint_of_the_same_command(tmp_path):
    from tests.real_corpus import REAL_CACHE, real_corpus

    if REAL_CACHE is None:
        pytest.skip("no cached corpus shards")
    from simcore.holdout.__main__ import main

    out = tmp_path / "report.json"
    assert main(["--hidden", "att_ai", "--pool", "240", "--seed", "4021", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["held_out_rows"] >= 4 and report["attributes"]["att_ai"]["projected_rows"] > 0
