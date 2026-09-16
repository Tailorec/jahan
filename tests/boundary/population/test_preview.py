"""`preview`: what the corpus holds, answered from a catalog and no rows."""

from pathlib import Path

import pytest

from simcore.population import PreviewRequest, preview
from simcore.ports.fixture import FixtureCoresetSource
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, FieldOrigin, RelaxationRung
from tests.study_builders import load_fixture, load_ontology, pack_payload

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def pack(**overrides) -> BriefPack:
    return BriefPack.model_validate(pack_payload(**overrides))


def bare_pack() -> BriefPack:
    """The shipped ontology with no completable economic attribute, so nothing would be synthesized."""
    return BriefPack.model_validate({"brief": load_fixture("example_brief.json"), "ontology": load_ontology()})


def fixture() -> FixtureCoresetSource:
    return FixtureCoresetSource.from_json(FIXTURES / "mini_coreset.json")


def synthetic(origin: FieldOrigin = FieldOrigin.MEASURED, populated: float = 1.0) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly"), populated=populated, origin=origin),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            },
            rows=4000,
        ),
        seed=11,
    )


class CatalogOnly:
    """A catalog with no way to read a row: the shape `preview` is typed to, proven by construction."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.row_reads = 0

    def sources(self):
        return self.inner.sources()

    def attributes(self):
        return self.inner.attributes()

    def values(self, attribute):
        return self.inner.values(attribute)

    def coverage(self, attributes, sources):
        return self.inner.coverage(attributes, sources)

    def count(self, predicates, present, *, by_source=True):
        return self.inner.count(predicates, present, by_source=by_source)

    def rows(self, ids):
        self.row_reads += 1
        raise AssertionError("preview must not read a row")


def test_preview_takes_a_catalog_and_never_reads_a_row():
    catalog = CatalogOnly(fixture())
    report = preview(PreviewRequest(pack(audiences=[]), 5), catalog=catalog)
    assert report.sources
    assert catalog.row_reads == 0


def test_preview_reports_matched_carrying_and_total_per_source():
    request = PreviewRequest(
        pack(audiences=[]), 5, filters={"exercise_frequency": "3_plus_weekly"}
    )
    report = preview(request, catalog=fixture())
    by_source = {source.source: source for source in report.sources}
    assert (by_source["gss"].matched, by_source["gss"].carrying, by_source["gss"].total) == (1, 4, 4)
    assert (by_source["amazon"].matched, by_source["amazon"].carrying, by_source["amazon"].total) == (1, 2, 2)
    # Nobody matches the synthetic rows, but somebody carries the attribute: that is a finding, not a gap.
    assert (by_source["synthetic"].matched, by_source["synthetic"].carrying, by_source["synthetic"].total) == (0, 1, 2)


def test_preview_names_each_attributes_tier_per_source_including_absent():
    report = preview(PreviewRequest(pack(audiences=[]), 5), catalog=synthetic(populated=0.0))
    (source,) = report.sources
    assert source.attributes["exercise_frequency"] is None
    assert source.attributes["age"] is FieldOrigin.MEASURED
    assert source.carrying == 0


def test_preview_grades_by_the_weakest_attribute_and_reports_extracted():
    report = preview(PreviewRequest(bare_pack(), 5), catalog=synthetic(origin=FieldOrigin.EXTRACTED))
    assert report.evidence is FieldOrigin.EXTRACTED


def test_a_field_that_would_be_synthesized_is_counted_without_weakening_the_gate_grade():
    # spend_band is absent everywhere and completable, so a draw would invent it — but an invented field is
    # never gated, so it lowers the reported count, not the grade the gated comparisons support.
    report = preview(PreviewRequest(pack(audiences=[]), 5), catalog=synthetic(origin=FieldOrigin.EXTRACTED))
    assert report.synthesized_fields > 0
    assert report.evidence is FieldOrigin.EXTRACTED


def test_preview_reports_the_fields_a_draw_would_synthesize_and_their_share():
    report = preview(PreviewRequest(pack(audiences=[]), 5), catalog=synthetic())
    # The ontology declares spend_band as economic and completable; the source does not carry it.
    assert report.synthesized_fields > 0
    assert report.synthesized_share > 0.0


def test_the_synthesized_count_is_for_the_requested_draw_not_the_whole_pool():
    """The count once summed over every matched row, so a five-persona study read as thousands of invented
    fields. spend_band is absent everywhere, so a draw of five invents exactly five, whatever the pool."""
    small = preview(PreviewRequest(pack(audiences=[]), 5), catalog=synthetic())
    large = preview(PreviewRequest(pack(audiences=[]), 50), catalog=synthetic())
    assert small.synthesized_fields == 5
    assert large.synthesized_fields == 50
    assert small.synthesized_share == large.synthesized_share


def test_preview_forecasts_the_rungs_the_ladder_would_climb():
    request = PreviewRequest(pack(audiences=[]), 50, filters={"exercise_frequency": "3_plus_weekly"})
    report = preview(request, catalog=fixture())
    assert report.relaxations
    assert {relaxation.rung for relaxation in report.relaxations} <= set(RelaxationRung)


def test_preview_without_filters_forecasts_no_rungs():
    assert preview(PreviewRequest(pack(audiences=[]), 5), catalog=fixture()).relaxations == ()


def test_preview_refuses_a_filter_on_an_attribute_the_ontology_does_not_declare():
    with pytest.raises(ValueError, match="does not declare"):
        preview(PreviewRequest(pack(audiences=[]), 5, filters={"eye_colour": "brown"}), catalog=fixture())


def test_a_source_implements_both_the_source_and_catalog_protocols():
    from simcore.ports import CoresetCatalog, CoresetSource

    source = synthetic()
    assert isinstance(source, CoresetSource)
    assert isinstance(source, CoresetCatalog)