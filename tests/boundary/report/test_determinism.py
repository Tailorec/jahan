"""Phase 4: determinism — a report is a function of its findings."""

import json
import random

from simcore.report import render
from simcore.schemas import Scenario, canonical_hash
from tests.boundary.report.support import BASELINE, PREMIUM, digests, finding_payload, pack
from tests.boundary.report.test_findings_page import cluster_payload
from tests.study_builders import digest_payload, ulid


def test_rendering_one_finding_set_twice_is_byte_identical():
    first = render([finding_payload()], digests(), pack(clusters=[cluster_payload()]))
    second = render([finding_payload()], digests(), pack(clusters=[cluster_payload()]))
    assert first.markdown == second.markdown
    assert json.dumps(first.data, sort_keys=True) == json.dumps(second.data, sort_keys=True)


def test_shuffling_the_inputs_changes_nothing():
    findings = [
        finding_payload(),
        finding_payload(finding_id="f-belief-01", kind="belief_shift", statement="credence rose"),
        finding_payload(finding_id="f-ranking-01", kind="ranking", statement="baseline leads",
                        ranked_scenarios=[canonical_hash(Scenario.model_validate(BASELINE)),
                                          canonical_hash(Scenario.model_validate(PREMIUM))]),
    ]
    clusters = [cluster_payload(), cluster_payload(label="a cheaper refill pack", size=3)]
    worlds = digests()
    expected = render(findings, worlds, pack(clusters=clusters))
    shuffled_findings = list(findings)
    random.Random(0).shuffle(shuffled_findings)
    shuffled_worlds = list(reversed(worlds))
    shuffled_clusters = list(reversed(clusters))
    actual = render(shuffled_findings, shuffled_worlds, pack(clusters=shuffled_clusters))
    assert actual.markdown == expected.markdown
    assert actual.data == expected.data


def test_findings_read_by_kind_then_id_clusters_by_size_then_label():
    findings = [
        finding_payload(finding_id="f-objection-02"),
        finding_payload(finding_id="f-belief-01", kind="belief_shift", statement="credence rose"),
        finding_payload(),
    ]
    clusters = [
        cluster_payload(size=3, label="a cheaper refill pack"),
        cluster_payload(label="zero sugar aftertaste", size=14),
        cluster_payload(size=14),
    ]
    report = render(findings, digests(), pack(clusters=clusters))
    assert [entry["finding_id"] for entry in report.data["findings"]] == [
        "f-belief-01", "f-objection-01", "f-objection-02",
    ]
    assert [(entry["size"], entry["label"]) for entry in report.data["objection_clusters"]] == [
        (14, "tastes chalky after the gym"), (14, "zero sugar aftertaste"), (3, "a cheaper refill pack"),
    ]


def test_digests_read_by_scenario_then_seed():
    worlds = [digest_payload(PREMIUM, seed=917731), digest_payload(BASELINE, seed=917731),
              digest_payload(PREMIUM), digest_payload(BASELINE)]
    report = render([finding_payload()], worlds, pack())
    expected = sorted(
        ((canonical_hash(Scenario.model_validate(BASELINE)), 4021),
         (canonical_hash(Scenario.model_validate(BASELINE)), 917731),
         (canonical_hash(Scenario.model_validate(PREMIUM)), 4021),
         (canonical_hash(Scenario.model_validate(PREMIUM)), 917731)),
    )
    assert [(entry["scenario_hash"], entry["seed"]) for entry in report.data["digests"]] == expected


def _distinct_finding(fid, n, **overrides):
    payload = {
        "finding_id": fid,
        "statement": f"statement unique to {fid}",
        "evidence_trace_ids": [f"ev-{ulid(n)}"],
        "disconfirming_test": f"test unique to {fid}",
    }
    payload.update(overrides)
    return finding_payload(**payload)


def test_reports_differing_in_one_finding_differ_only_where_it_appears():
    base = [_distinct_finding("f-aaa-01", 11), _distinct_finding("f-bbb-01", 12), _distinct_finding("f-ccc-01", 13)]
    changed = [_distinct_finding("f-aaa-01", 11),
               _distinct_finding("f-bbb-01", 12, statement="a changed statement"),
               _distinct_finding("f-ccc-01", 13)]
    first = render(base, digests(), pack())
    second = render(changed, digests(), pack())
    assert first.markdown != second.markdown
    for fid in ("f-aaa-01", "f-ccc-01"):
        assert [line for line in first.markdown.splitlines() if fid in line] == [
            line for line in second.markdown.splitlines() if fid in line
        ]
    assert [entry for entry in first.data["findings"] if entry["finding_id"] != "f-bbb-01"] == [
        entry for entry in second.data["findings"] if entry["finding_id"] != "f-bbb-01"
    ]
