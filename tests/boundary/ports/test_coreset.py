"""The coreset seam: resolution by predicate and conditioning, decoded rows, and the value vocabulary."""

import subprocess
import sys
from pathlib import Path

import pytest

from simcore.ports import CoresetSource
from simcore.ports.fixture import FixtureCoresetSource
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BandRange, Exactly, OneOf

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def synthetic(seed: int = 3) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
            },
            rows=200,
        ),
        seed=seed,
    )


def test_the_adapters_satisfy_the_port():
    assert isinstance(synthetic(), CoresetSource)
    assert isinstance(FixtureCoresetSource.from_json(FIXTURES / "mini_coreset.json"), CoresetSource)


def test_resolution_requires_the_populated_attributes_in_the_same_call():
    source = SyntheticCoresetSource(
        SyntheticShape(
            {"age": AttributeShape(("25_34", "35_44")), "sex": AttributeShape(("female", "male"), populated=0.0)},
            rows=50,
        ),
        seed=1,
    )
    assert source.matching({}, present=("age",))
    assert source.matching({}, present=("age", "sex")) == ()


def test_a_predicate_resolves_exact_one_of_and_range_against_the_vocabulary():
    source = synthetic()
    exact = list(source.rows(source.matching({"exercise_frequency": Exactly(value="weekly")}, present=())))
    assert exact and all(row.values["exercise_frequency"] == "weekly" for row in exact)

    one_of = list(source.rows(source.matching({"exercise_frequency": OneOf(values=("weekly", "rarely"))}, present=())))
    assert one_of and {row.values["exercise_frequency"] for row in one_of} == {"weekly", "rarely"}

    ranged = list(
        source.rows(source.matching({"exercise_frequency": BandRange(first="weekly", last="3_plus_weekly")}, present=()))
    )
    assert ranged and {row.values["exercise_frequency"] for row in ranged} == {"weekly", "3_plus_weekly"}


def test_the_source_reports_the_value_set_and_refuses_an_unknown_attribute():
    source = synthetic()
    assert source.values("age") == ("18_24", "25_34", "35_44", "45_54")
    with pytest.raises(KeyError) as raised:
        source.values("hair_color")
    assert "hair_color" in str(raised.value)


def test_resolution_refuses_a_predicate_on_an_unknown_attribute():
    with pytest.raises(KeyError, match="does not know"):
        synthetic().matching({"hair_color": Exactly(value="brown")}, present=())


def test_a_shape_controls_the_distribution_and_how_often_an_attribute_is_populated():
    always = SyntheticCoresetSource(SyntheticShape({"age": AttributeShape(("a", "b"), populated=1.0)}, rows=40), seed=2)
    assert len(always.matching({}, present=("age",))) == 40

    never = SyntheticCoresetSource(SyntheticShape({"age": AttributeShape(("a", "b"), populated=0.0)}, rows=40), seed=2)
    assert never.matching({}, present=("age",)) == ()

    skewed = SyntheticCoresetSource(
        SyntheticShape({"age": AttributeShape(("a", "b"), weights=(1.0, 0.0), populated=1.0)}, rows=40), seed=2
    )
    assert {row.values["age"] for row in skewed.rows(skewed.matching({}, present=()))} == {"a"}


def test_the_synthetic_source_generates_the_same_rows_for_the_same_shape_and_seed_in_two_processes():
    script = (
        "import hashlib\n"
        "from simcore.ports.synthetic import AttributeShape, SyntheticShape, SyntheticCoresetSource\n"
        "shape = SyntheticShape({'a': AttributeShape(('x', 'y', 'z'), weights=(0.2, 0.3, 0.5), populated=0.7)}, rows=50)\n"
        "source = SyntheticCoresetSource(shape, seed=7)\n"
        "ids = source.matching({}, present=())\n"
        "material = '|'.join(f'{row.row_id}:{dict(row.values)}' for row in source.rows(ids))\n"
        "print(hashlib.sha256(material.encode()).hexdigest())\n"
    )

    def run() -> str:
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, check=True
        )
        return completed.stdout.strip()

    first, second = run(), run()
    assert first == second and len(first) == 64


def test_a_different_seed_generates_different_rows():
    def material(source):
        return "|".join(f"{row.row_id}:{dict(row.values)}" for row in source.rows(source.matching({}, present=())))

    assert material(synthetic(seed=3)) == material(synthetic(seed=3))
    assert material(synthetic(seed=3)) != material(synthetic(seed=4))


def test_the_fixture_source_serves_committed_rows_readable_beside_this_test():
    source = FixtureCoresetSource.from_json(FIXTURES / "mini_coreset.json")
    assert source.values("exercise_frequency") == ("rarely", "weekly", "3_plus_weekly")
    eligible = source.matching({}, present=("age", "sex", "exercise_frequency"))
    assert set(eligible) == {"000001", "000002", "000003", "000004", "000005", "000006", "000008"}
    assert next(source.rows(["000001"])).source == "gss"
    ranged = source.matching({"exercise_frequency": BandRange(first="weekly", last="3_plus_weekly")}, present=())
    assert set(ranged) == {"000001", "000002", "000004", "000005", "000006"}


def test_no_core_module_imports_a_concrete_source():
    offenders = [
        str(path.relative_to(REPO))
        for path in (REPO / "simcore").rglob("*.py")
        if "ports" not in path.parts
        and any(
            name in path.read_text(encoding="utf-8")
            for name in ("SyntheticCoresetSource", "FixtureCoresetSource", "ports.synthetic", "ports.fixture")
        )
    ]
    assert offenders == []
