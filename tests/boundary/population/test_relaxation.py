"""The relaxation ladder: a starved quota widens, then drops, then accepts short — and records every rung."""

from pathlib import Path

import pytest

from simcore.population import assess
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BandRange, BriefPack, Exactly, GateFailure, RelaxationRung
from tests.study_builders import pack_payload


class RecordingSource:
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


def source(rows: int = 600, seed: int = 11) -> SyntheticCoresetSource:
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


def pack(audiences) -> BriefPack:
    return BriefPack.model_validate(pack_payload(audiences=audiences))


CONDITIONING = {"age", "sex", "exercise_frequency"}


def test_a_starved_quota_widens_its_ordinal_predicate_by_one_band():
    report = assess(
        pack([{"name": "gym", "share": 1.0, "attribute_filters": {"exercise_frequency": "3_plus_weekly"}}]),
        300,
        4021,
        coreset=source(),
    )
    (relaxation,) = report.relaxations
    assert relaxation.rung.value == "widen_ordinal" and relaxation.attribute == "exercise_frequency"
    assert relaxation.authored == Exactly(value="3_plus_weekly")
    assert relaxation.applied == BandRange(first="weekly", last="3_plus_weekly")
    assert relaxation.rows_after > relaxation.rows_before
    assert relaxation.share_achieved == 1.0


def test_a_widened_predicate_that_still_cannot_fill_drops_the_least_relevant_filter():
    report = assess(
        pack(
            [
                {
                    "name": "both",
                    "share": 1.0,
                    "attribute_filters": {"exercise_frequency": "3_plus_weekly", "diet_protein_focus": "high"},
                }
            ]
        ),
        400,
        4021,
        coreset=source(),
    )
    drops = [relaxation for relaxation in report.relaxations if relaxation.rung.value == "drop_filter"]
    assert len(drops) == 1
    assert drops[0].attribute == "diet_protein_focus"  # least relevant non-conditioning attribute
    assert drops[0].applied is None
    assert any(relaxation.rung.value == "widen_ordinal" for relaxation in report.relaxations)


def test_a_quota_that_still_cannot_fill_is_accepted_short_and_the_mix_shows_it():
    report = assess(
        pack(
            [
                {"name": "older", "share": 0.5, "attribute_filters": {"age": "45_54"}},
                {"name": "rest", "share": 0.5, "attribute_filters": {}},
            ]
        ),
        400,
        4021,
        coreset=source(),
    )
    (shortfall,) = [relaxation for relaxation in report.relaxations if relaxation.rung.value == "accept_shortfall"]
    assert shortfall.attribute is None and shortfall.share_achieved < 1.0
    assert report.achieved_mix["older"] < 0.5
    assert sum(report.achieved_mix.values()) == pytest.approx(1.0)


def test_no_rung_ever_loosens_the_conditioning_set():
    recorder = RecordingSource(source())
    report = assess(
        pack(
            [
                {"name": "older", "share": 0.5, "attribute_filters": {"age": "45_54"}},
                {"name": "rest", "share": 0.5, "attribute_filters": {}},
            ]
        ),
        400,
        4021,
        coreset=recorder,
    )
    assert all(relaxation.attribute not in CONDITIONING for relaxation in report.relaxations)
    sampled = list(recorder.inner.rows(recorder.rows_calls[0]))
    assert sampled and all(CONDITIONING <= set(row.values) for row in sampled)


def test_an_audience_matching_no_rows_is_refused_naming_its_filters_and_the_rung_counts():
    with pytest.raises(GateFailure) as raised:
        assess(
            pack([{"name": "vegans", "share": 1.0, "attribute_filters": {"diet_protein_focus": "vegan"}}]),
            100,
            4021,
            coreset=source(),
        )
    message = str(raised.value)
    assert "vegans" in message and "vegan" in message and "counts at each rung" in message


def test_relaxations_do_not_change_the_gate_report_verdict():
    report = assess(
        pack(
            [
                {
                    "name": "both",
                    "share": 1.0,
                    "attribute_filters": {"exercise_frequency": "3_plus_weekly", "diet_protein_focus": "high"},
                }
            ]
        ),
        400,
        4021,
        coreset=source(),
    )
    assert report.relaxations
    assert report.overall == all(result.passed for result in report.results)


def test_a_study_whose_audiences_all_fill_records_no_relaxations():
    report = assess(BriefPack.model_validate(pack_payload()), 200, 4021, coreset=source(rows=4000))
    assert report.relaxations == ()


def test_widening_never_swallows_the_whole_scale():
    """A filter widened across every band is a dropped filter wearing a gentler name."""
    source = SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly"), weights=(0.97, 0.02, 0.01)),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            },
            rows=4000,
        ),
        seed=11,
    )
    report = assess(BriefPack.model_validate(pack_payload()), 1000, 4021, coreset=source)
    gym = [relaxation for relaxation in report.relaxations if relaxation.audience == "gym_regulars"]
    widened = [relaxation for relaxation in gym if relaxation.rung is RelaxationRung.WIDEN_ORDINAL]
    assert widened, "the starved audience should have widened at least once"
    assert all(relaxation.applied.first != "rarely" for relaxation in widened)
    assert gym[-1].rung is RelaxationRung.ACCEPT_SHORTFALL
    assert report.achieved_mix["gym_regulars"] < 0.3
