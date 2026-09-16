"""`admissible_sources`: which sources a study may draw from, recorded, never silent."""

import random
from pathlib import Path

import pytest

from tests.study_builders import pack_payload

from simcore.population import PreviewRequest, assess, build, preview
from simcore.ports.coreset import DecodedRow, _DecodedRowSource
from simcore.ports.fake import FakeChat
from simcore.schemas import BriefPack, DistributionThresholds, FieldOrigin, FrozenDict, PopulationParameters

VOCABULARY = {
    "age": ["18_24", "25_34", "35_44", "45_54"],
    "sex": ["female", "male"],
    "exercise_frequency": ["rarely", "weekly", "3_plus_weekly"],
    "diet_protein_focus": ["low", "medium", "high"],
    "spend_band": ["0_5", "5_10", "10_20", "20_50"],
}
_TIERS = {"gss": FieldOrigin.MEASURED, "stackoverflow": FieldOrigin.MEASURED, "amazon": FieldOrigin.EXTRACTED}
_SOURCES = ["gss", "stackoverflow", "amazon"]


def multi_source(rows: int = 1200) -> _DecodedRowSource:
    """An in-memory corpus whose sources differ in the tier they carry: survey rows measured, Amazon rows
    extracted. Demographics are never synthesized, so the stand-in synthetic source is kept out; the
    synthesis path is exercised by other tests."""
    generated = []
    for index in range(rows):
        rng = random.Random(f"multi:{index}")
        source = _SOURCES[index % len(_SOURCES)]
        values = {
            "age": rng.choice(VOCABULARY["age"]),
            "sex": rng.choice(VOCABULARY["sex"]),
            "exercise_frequency": rng.choice(VOCABULARY["exercise_frequency"]),
            "diet_protein_focus": rng.choice(VOCABULARY["diet_protein_focus"]),
        }
        tiers = {attribute: _TIERS[source] for attribute in values}
        generated.append(DecodedRow(row_id=f"{index:04d}", source=source, values=FrozenDict(values), tiers=FrozenDict(tiers)))
    return _DecodedRowSource(generated, {key: tuple(value) for key, value in VOCABULARY.items()})


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def parameters(**overrides) -> PopulationParameters:
    # These tests are about which sources a study draws from and how the mix is graded, not about whether
    # a random subset happens to match its pool, so the distribution gates are held open throughout.
    overrides.setdefault("distribution_gates", DistributionThresholds(significance_level=1e-9, similarity_threshold=1e-9))
    return PopulationParameters(**overrides)


def test_admissible_sources_defaults_to_none_and_is_carried_on_the_manifest():
    built = build(pack(), 120, 4021, coreset=multi_source(), inference=FakeChat(), parameters=parameters())
    assert built.population.manifest.parameters.admissible_sources is None
    restricted = build(
        pack(), 120, 4021, coreset=multi_source(), inference=FakeChat(), parameters=parameters(admissible_sources=frozenset({"gss", "stackoverflow"}))
    )
    assert set(restricted.population.manifest.parameters.admissible_sources) == {"gss", "stackoverflow"}
    assert set(restricted.population.gate_report.source_mix) <= {"gss", "stackoverflow"}


def test_a_study_restricted_to_one_source_draws_from_it_alone():
    report = assess(
        pack(audiences=[]), 80, 4021, coreset=multi_source(), parameters=parameters(admissible_sources=frozenset({"gss"}))
    )
    assert set(report.source_mix) == {"gss"}


def test_a_study_naming_several_sources_may_draw_from_all_of_them():
    report = assess(
        pack(audiences=[]), 120, 4021, coreset=multi_source(), parameters=parameters(admissible_sources=frozenset({"gss", "amazon", "stackoverflow"}))
    )
    assert {"gss", "amazon", "stackoverflow"} <= set(report.source_mix)
    assert "synthetic" not in report.source_mix


def test_a_population_mixing_sources_grades_to_the_weakest_tier_present():
    measured_only = assess(pack(audiences=[]), 80, 4021, coreset=multi_source(), parameters=parameters(admissible_sources=frozenset({"gss", "stackoverflow"})))
    assert measured_only.evidence is FieldOrigin.MEASURED
    mixed = assess(pack(audiences=[]), 120, 4021, coreset=multi_source(), parameters=parameters(admissible_sources=frozenset({"gss", "amazon"})))
    assert mixed.evidence is FieldOrigin.EXTRACTED


def test_an_audience_filtering_on_an_extracted_attribute_is_permitted_and_labelled():
    built = build(pack(), 120, 4021, coreset=multi_source(), inference=FakeChat(), parameters=parameters(admissible_sources=frozenset({"gss", "amazon"})))
    report = built.population.gate_report
    assert {"gss", "amazon"} <= set(report.source_mix)
    assert report.evidence is FieldOrigin.EXTRACTED
    request = PreviewRequest(pack(), 120, sources=("gss", "amazon"))
    forecast = preview(request, catalog=multi_source())
    assert any(source.attributes["diet_protein_focus"] is FieldOrigin.EXTRACTED for source in forecast.sources)
    assert forecast.evidence is FieldOrigin.EXTRACTED


def test_reaching_a_quota_by_admitting_a_weaker_source_is_visible_in_preview_and_report():
    # The gym-regular audience is too small to fill its quota from the measured sources alone; admitting
    # Amazon reaches it, and both the preview and the report say the evidence fell to extracted.
    filters = {"exercise_frequency": "3_plus_weekly"}
    tight = PreviewRequest(pack(audiences=[]), 200, filters=filters, sources=("gss", "stackoverflow"))
    wide = PreviewRequest(pack(audiences=[]), 200, filters=filters, sources=("gss", "stackoverflow", "amazon"))
    measured_forecast = preview(tight, catalog=multi_source())
    mixed_forecast = preview(wide, catalog=multi_source())
    assert measured_forecast.evidence is FieldOrigin.MEASURED
    assert mixed_forecast.evidence is FieldOrigin.EXTRACTED
    assert sum(s.matched for s in mixed_forecast.sources) > sum(s.matched for s in measured_forecast.sources)
    built = build(
        pack(), 200, 4021, coreset=multi_source(), inference=FakeChat(),
        parameters=parameters(admissible_sources=frozenset({"gss", "stackoverflow", "amazon"})),
    )
    assert "amazon" in built.population.gate_report.source_mix
    assert built.population.gate_report.evidence is FieldOrigin.EXTRACTED


class ReadRecorder:
    """Delegates to a source and records every row id read, so a test can prove what a study touched."""

    def __init__(self, source) -> None:
        self._source = source
        self.read: list[str] = []

    def matching(self, predicates, present, *, sources=None):
        return self._source.matching(predicates, present, sources=sources)

    def rows(self, ids):
        for row in self._source.rows(ids):
            self.read.append(row.source)
            yield row

    def __getattr__(self, name):
        return getattr(self._source, name)


def test_restricting_sources_still_fills_the_study_when_the_admitted_sources_hold_enough_rows():
    """Admissible sources were once applied after the draw: a 300-persona study admitting two of three
    sources built 193 personas, recorded no relaxation and raised nothing."""
    built = build(
        pack(), 300, 4021, coreset=multi_source(), inference=FakeChat(),
        parameters=parameters(admissible_sources=frozenset({"gss", "stackoverflow"})),
    )
    assert len(built.population.personas) == 300
    assert set(built.population.gate_report.source_mix) == {"gss", "stackoverflow"}


def test_a_restriction_that_thins_an_audience_climbs_the_recorded_ladder_rather_than_shrinking_silently():
    """Admitting only one source once built 99 of 300 personas with no relaxation, though 400 rows of
    that source existed. The restriction now reaches eligibility, so a thin audience is a recorded rung."""
    built = build(
        pack(), 300, 4021, coreset=multi_source(), inference=FakeChat(),
        parameters=parameters(admissible_sources=frozenset({"gss"})),
    )
    report = built.population.gate_report
    assert len(built.population.personas) > 99
    assert report.relaxations, "a study that could not fill its quota from its admitted sources must say so"


def test_no_row_from_a_source_the_study_does_not_admit_is_ever_read():
    recorder = ReadRecorder(multi_source())
    build(pack(), 200, 4021, coreset=recorder, inference=FakeChat(), parameters=parameters(admissible_sources=frozenset({"gss"})))
    assert recorder.read and set(recorder.read) == {"gss"}
