"""Phase 1: one pass, two formats — findings and digests in, markdown and JSON out."""

import json
from unittest import mock

from simcore.report import REPORT_CONTRACT_VERSION, render
from simcore.schemas.base import SCHEMA_VERSION
from tests.boundary.report.support import BASELINE, PREMIUM, digests, finding_payload, pack


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
    assert "1.0.0" in report.markdown
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
