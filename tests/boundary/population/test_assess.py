"""`assess`: eligibility before sampling, a seeded draw, and the gates that judge it."""

from pathlib import Path

import pytest

from simcore.population import assess
from simcore.ports.fixture import FixtureCoresetSource
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, GateFailure, canonical_hash
from tests.study_builders import pack_payload

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class RecordingSource:
    """An in-memory source that records every `rows()` request, so a test can see what was sampled."""

    def __init__(self, inner: SyntheticCoresetSource) -> None:
        self.inner = inner
        self.rows_calls: list[tuple[str, ...]] = []

    def matching(self, predicates, present):
        return self.inner.matching(predicates, present)

    def rows(self, ids):
        ids = tuple(ids)
        self.rows_calls.append(ids)
        return self.inner.rows(ids)

    def values(self, attribute):
        return self.inner.values(attribute)


def default_source(rows: int = 4000, seed: int = 11) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            },
            rows=rows,
        ),
        seed=seed,
    )


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def test_a_row_missing_a_conditioning_attribute_never_reaches_the_candidate_pool():
    inner = SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("25_34", "35_44"), populated=0.4),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
            },
            rows=400,
        ),
        seed=5,
    )
    recorder = RecordingSource(inner)
    assess(pack(audiences=[]), 100, 4021, coreset=recorder)
    sampled = recorder.rows_calls[0]
    assert sampled
    assert all("age" in row.values for row in inner.rows(sampled))


def test_sampling_fills_each_audiences_quota_from_its_own_eligible_pool():
    recorder = RecordingSource(default_source())
    report = assess(pack(), 100, 4021, coreset=recorder)
    assert dict(report.achieved_mix) == {"gym_regulars": 0.6, "protein_dieters": 0.4}
    sampled = list(recorder.inner.rows(recorder.rows_calls[0]))
    assert all(
        row.values.get("exercise_frequency") == "3_plus_weekly" or row.values.get("diet_protein_focus") == "high"
        for row in sampled
    )


def test_the_source_mix_of_the_sample_is_reported():
    source = FixtureCoresetSource.from_json(FIXTURES / "mini_coreset.json")
    report = assess(pack(audiences=[]), 6, 4021, coreset=source)
    assert set(report.source_mix) <= {"gss", "amazon", "synthetic"}
    assert sum(report.source_mix.values()) == pytest.approx(1.0)


def test_a_faithful_sample_passes_and_a_skewed_categorical_marginal_fails():
    source = default_source()
    faithful = assess(pack(audiences=[]), 1000, 4021, coreset=source)
    assert faithful.overall is True

    skewed = assess(
        pack(audiences=[{"name": "young", "share": 1.0, "attribute_filters": {"age": "25_34"}}]),
        1000,
        4021,
        coreset=source,
    )
    age = next(result for result in skewed.results if result.attribute == "age")
    assert age.kind == "categorical" and age.passed is False
    assert skewed.overall is False


def test_an_ordinal_attribute_is_judged_on_its_declared_bands_and_a_shifted_distribution_fails():
    source = default_source()
    faithful = assess(pack(audiences=[]), 1000, 4021, coreset=source)
    ordinal = next(result for result in faithful.results if result.attribute == "exercise_frequency")
    assert ordinal.kind == "ordinal" and ordinal.passed is True

    shifted = assess(
        pack(audiences=[{"name": "gym", "share": 1.0, "attribute_filters": {"exercise_frequency": "3_plus_weekly"}}]),
        1000,
        4021,
        coreset=source,
    )
    moved = next(result for result in shifted.results if result.attribute == "exercise_frequency")
    assert moved.kind == "ordinal" and moved.passed is False


def test_gates_run_only_on_attributes_the_sample_carries():
    source = SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("25_34", "35_44")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "high"), populated=0.0),
            },
            rows=400,
        ),
        seed=5,
    )
    report = assess(pack(audiences=[]), 100, 4021, coreset=source)
    gated = {result.attribute for result in report.results}
    assert "diet_protein_focus" not in gated
    assert {"age", "sex", "exercise_frequency"} <= gated


def test_assessing_calls_no_model_and_the_same_seed_assesses_identically():
    source = default_source()
    first = assess(pack(audiences=[]), 500, 4021, coreset=source)
    second = assess(pack(audiences=[]), 500, 4021, coreset=source)
    assert canonical_hash(first) == canonical_hash(second)


def test_a_study_that_can_sample_nothing_is_refused():
    source = SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("25_34",), populated=0.0),
                "sex": AttributeShape(("female",), populated=0.0),
                "exercise_frequency": AttributeShape(("weekly",), populated=0.0),
            },
            rows=10,
        ),
        seed=1,
    )
    with pytest.raises(GateFailure, match="conditioning"):
        assess(pack(audiences=[]), 10, 4021, coreset=source)
