"""Phase 1: one pass, two formats — findings and digests in, markdown and JSON out."""

import json
from unittest import mock

import pytest
from pydantic import ValidationError

from simcore.report import REPORT_CONTRACT_VERSION, render
from simcore.schemas.base import SCHEMA_VERSION
from tests.boundary.report.support import BASELINE, PREMIUM, digests, finding_payload, pack
from tests.study_builders import digest_payload


def test_render_returns_both_formats_from_one_intermediate():
    report = render([finding_payload()], digests(), pack())
    assert report.markdown.strip()
    assert report.data
    # The same finding set in both: same ids, same order, neither omits one.
    markdown_ids = [line.split(" · ")[0].removeprefix("### ") for line in report.markdown.splitlines() if line.startswith("### f-")]
    assert markdown_ids == [finding["finding_id"] for finding in report.data["findings"]]
    assert markdown_ids == ["f-objection-01"]


def test_json_records_the_contract_version_it_was_rendered_under():
    report = render([finding_payload()], digests(), pack())
    assert report.data["contract_version"] == REPORT_CONTRACT_VERSION == SCHEMA_VERSION
    assert SCHEMA_VERSION in report.markdown
    json.dumps(report.data)


def test_a_report_with_no_findings_renders_both_formats_and_says_so():
    report = render([], digests(), pack())
    assert "No findings were authored for this run." in report.markdown
    assert report.data["findings"] == []
    assert report.data["contract_version"] == REPORT_CONTRACT_VERSION


def test_rendering_reads_nothing_but_what_it_was_given():
    findings, worlds, pack_ = [finding_payload()], digests(), pack()
    with mock.patch("builtins.open", side_effect=AssertionError("render opens no files")):
        report = render(findings, worlds, pack_)
    assert report.data["findings"][0]["finding_id"] == "f-objection-01"
    assert findings == [finding_payload()] and worlds == digests()


def test_markdown_and_json_carry_the_same_digests():
    report = render([finding_payload()], digests(), pack())
    assert [entry["world_id"] for entry in report.data["digests"]] == [
        line.removeprefix("### World ").split(" · ")[0] for line in report.markdown.splitlines() if line.startswith("### World ")
    ]
    assert len(report.data["digests"]) == 2
    _ = (BASELINE, PREMIUM)


def test_a_digest_of_a_world_this_run_does_not_configure_is_refused():
    """`Report` is the contract a rendered report has to satisfy: one digest per world, each
    world one this run configures, no finding id twice. Formatting without building it lets a
    document describe a study its own configuration never ran."""
    from tests.study_builders import scenario_payload

    stranger = scenario_payload(
        variant={"variant_id": "v9stranger", "name": "Stranger", "description": "Another run entirely"})
    with pytest.raises((ValidationError, ValueError), match="does not configure"):
        render([finding_payload()], [digest_payload(stranger, seed=999)], pack())


def test_two_findings_under_one_id_are_refused():
    with pytest.raises((ValidationError, ValueError), match="repeated"):
        render([finding_payload(), finding_payload()], digests(), pack())


def test_the_rendering_carries_the_validated_report_it_was_built_from():
    report = render([finding_payload()], digests(), pack())
    assert report.report is not None
    assert [digest.world_id for digest in report.report.digests] == [
        entry["world_id"] for entry in report.data["digests"]
    ]


def test_waves_render_as_intent_over_time_with_the_reached_split_and_the_repeated_ssr_caveat():
    worlds = digests()
    worlds[0]["waves"] = [
        {"tick": 0, "respondents": 4, "audience_pmfs": {"gym_regulars": (0.1, 0.1, 0.2, 0.3, 0.3)},
         "audience_shares": {"gym_regulars": 1.0}, "reached": 0, "unreached_pmf": (0.1, 0.1, 0.2, 0.3, 0.3)},
        {"tick": 2, "respondents": 4, "audience_pmfs": {"gym_regulars": (0.0, 0.1, 0.1, 0.4, 0.4)},
         "audience_shares": {"gym_regulars": 1.0}, "reached": 3,
         "reached_pmf": (0.0, 0.0, 0.2, 0.4, 0.4), "unreached_pmf": (0.2, 0.2, 0.2, 0.2, 0.2)},
    ]
    report = render([], worlds, pack())
    assert "Intent over survey waves:" in report.markdown
    assert "- tick 0: 4 answered, adoption 0.6 (gym_regulars 0.6); unreached 4 at 0.6" in report.markdown
    assert "; reached 3 at 0.8; unreached 1 at 0.4" in report.markdown
    assert "one-shot survey" in report.markdown
    (first, _) = [d for d in report.data["digests"] if d["waves"]][0]["waves"]
    assert first["adoption"] == pytest.approx(0.6)
