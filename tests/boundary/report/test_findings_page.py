"""Phase 3: findings on the page — evidence, ledger, unmeasured adoption, confidence, quotes."""

from simcore.report import render
from simcore.schemas import BriefPack
from tests.boundary.report.support import BASELINE, EVIDENCE, digests, finding_payload, pack
from tests.study_builders import digest_payload, pack_payload


def cluster_payload(**overrides):
    payload = {
        "label": "tastes chalky after the gym",
        "verbatim_trace_ids": EVIDENCE,
        "size": 14,
        "threshold": 0.75,
        "embed_model_id": "openai/text-embedding-3-small",
    }
    payload.update(overrides)
    return payload


def test_every_finding_shows_its_evidence_ids_and_its_disconfirming_test():
    second = finding_payload(
        finding_id="f-belief-01",
        kind="belief_shift",
        statement="credence in value rose by 0.10 on average over 12 moves",
        evidence_trace_ids=EVIDENCE[:1],
        disconfirming_test="rerun the same scenario with 12 fresh personas",
        confidence="high",
    )
    report = render([finding_payload(), second], digests(), pack())
    for finding in (finding_payload(), second):
        for trace_id in finding["evidence_trace_ids"]:
            assert trace_id in report.markdown
        assert finding["disconfirming_test"] in report.markdown
    # Findings read by kind then id, so the belief-shift finding leads in both formats.
    assert [entry["finding_id"] for entry in report.data["findings"]] == ["f-belief-01", "f-objection-01"]
    assert [entry["evidence_trace_ids"] for entry in report.data["findings"]] == [EVIDENCE[:1], EVIDENCE]


def test_the_assumption_ledger_appears_with_sources():
    report = render([finding_payload()], digests(), pack())
    assert "Respondents distinguish clear from milky protein formats" in report.markdown
    assert "Hydrates like water, not milk" in report.markdown
    sources = {item["source"] for item in report.data["assumptions"]}
    assert {"user_asserted", "assumed"} <= sources


def test_what_the_brief_left_unstated_appears_in_the_ledger():
    brief_pack = BriefPack.model_validate(pack_payload(audiences=()))
    report = render([finding_payload()], digests(), pack(brief_pack=brief_pack))
    assert "assumed to be the whole population" in report.markdown


def test_unmeasured_adoption_is_stated_where_it_would_have_appeared():
    reason = "no anchor version is pinned, so no turn was scored"
    worlds = [
        digest_payload(
            BASELINE,
            audience_pmfs={},
            audience_shares={},
            community_pmfs={},
            community_sizes={},
            unmeasured_reason=reason,
        )
    ]
    report = render([finding_payload()], worlds, pack())
    assert "Adoption: unmeasured — " + reason in report.markdown
    assert report.data["digests"][0]["adoption"] is None
    assert report.data["digests"][0]["unmeasured_reason"] == reason


def test_measured_adoption_renders_as_a_number_in_the_same_place():
    report = render([finding_payload()], digests(), pack())
    adoptions = [entry["adoption"] for entry in report.data["digests"]]
    assert all(adoption is not None for adoption in adoptions)
    for adoption in adoptions:
        assert "Adoption: " + repr(adoption) in report.markdown


def test_confidence_beside_each_finding_and_calibration_never_beside_any():
    report = render([finding_payload()], digests(), pack())
    findings_section = report.markdown.split("## Findings")[1].split("## Trust")[0]
    assert "confidence medium" in findings_section
    assert "uncalibrated" not in findings_section
    assert "calibrat" not in findings_section


def test_objection_clusters_render_their_quoted_label_never_a_paraphrase():
    report = render([finding_payload()], digests(), pack(clusters=[cluster_payload()]))
    assert '"tastes chalky after the gym"' in report.markdown
    assert report.data["objection_clusters"][0]["label"] == "tastes chalky after the gym"


def test_what_a_run_without_ratings_measured_reaches_the_page():
    """ADR 0038: a digest carries the action mix, belief movement and word-of-mouth reach so a
    run that scored no intent still reports what happened. A report that prints only the
    unmeasured adoption line says the study measured nothing, which is the opposite."""
    worlds = [digest_payload(
        BASELINE, audience_pmfs={}, audience_shares={}, community_pmfs={}, community_sizes={},
        unmeasured_reason="no anchor version is pinned", turn_count=12, turns_without_intent=12,
        action_mix={"answer": 9, "ignore": 3}, belief_movement_mean={"value": 0.04},
        belief_movement_abs={"value": 0.06}, belief_move_mean=0.02, wom_deliveries=7, wom_reach=5)]
    report = render([finding_payload()], worlds, pack())
    markdown = report.markdown
    assert "12" in markdown and "answer 9" in markdown and "ignore 3" in markdown
    assert "0.04" in markdown and "0.06" in markdown
    assert "7" in markdown and "5" in markdown
    entry = report.data["digests"][0]
    assert entry["turn_count"] == 12 and entry["turns_without_intent"] == 12
    assert entry["action_mix"] == {"answer": 9, "ignore": 3}
    assert entry["belief_movement_mean"] == {"value": 0.04}
    assert entry["wom_deliveries"] == 7 and entry["wom_reach"] == 5


def test_polarization_and_divergence_are_stated_where_they_would_have_appeared():
    worlds = [digest_payload(
        BASELINE, audience_pmfs={}, audience_shares={}, community_pmfs={}, community_sizes={},
        unmeasured_reason="no anchor version is pinned", turn_count=1, action_mix={"answer": 1},
        turns_without_intent=1)]
    report = render([finding_payload()], worlds, pack())
    assert "Polarization: unmeasured" in report.markdown
    assert "Audience divergence: unmeasured" in report.markdown
    entry = report.data["digests"][0]
    assert entry["polarization"] is None and entry["audience_divergence"] is None


def test_a_quoted_verbatim_cannot_restructure_the_document():
    """A cluster's label is a sentence a persona wrote (ADR 0041) and a finding's statement
    quotes it. Printed as-is, a verbatim holding a line break and a `##` becomes a heading of
    the report itself."""
    label = "it is fine\n## Real heading injected"
    report = render(
        [finding_payload(statement="2 personas said something this cluster groups, quoted as " + repr(label))],
        digests(),
        pack(clusters=[cluster_payload(label=label, size=2)]),
    )
    headings = [line for line in report.markdown.splitlines() if line.startswith("#")]
    assert not any("Real heading injected" in heading for heading in headings)
    assert "Real heading injected" in report.markdown
    # The record keeps what the persona wrote; only the page renders it on one line.
    assert report.data["objection_clusters"][0]["label"] == label


def test_a_finding_citing_hundreds_of_records_stays_readable():
    """Every turn of every persona can be evidence: a belief-shift finding over 24 personas and
    six ticks cites 120 trace ids, and a real study cites thousands. Printed inline they bury
    the finding they support. The page shows the first of them; the JSON keeps them all, which
    is what a reader checks a citation against."""
    ids = [f"ev-{'0' * 21}{index:05d}" for index in range(120)]
    report = render([finding_payload(evidence_trace_ids=ids)], digests(), pack())
    evidence_line = next(line for line in report.markdown.splitlines() if line.startswith("Evidence: "))
    assert len(evidence_line) < 300
    assert ids[0] in evidence_line and ids[-1] not in evidence_line
    assert evidence_line.rstrip().endswith("…")
    assert report.data["findings"][0]["evidence_trace_ids"] == ids


def test_a_finding_citing_a_few_records_shows_them_all():
    report = render([finding_payload()], digests(), pack())
    evidence_line = next(line for line in report.markdown.splitlines() if line.startswith("Evidence: "))
    assert all(trace_id in evidence_line for trace_id in EVIDENCE)
    assert "…" not in evidence_line


def test_clusters_of_two_worlds_are_told_apart_on_the_page():
    """A two-seed study reports each world's clusters, and the stub personas say the same thing
    in both, so the list read as the same line printed twice with nothing to tell them apart —
    the defect the finding ids had, in the section beside them."""
    first = cluster_payload(world_id="a00631e91974")
    second = cluster_payload(world_id="4ecd96cdea45")
    report = render([finding_payload()], digests(), pack(clusters=[first, second]))
    lines = [line for line in report.markdown.splitlines() if line.startswith('- "')]
    assert len(lines) == 2 and lines[0] != lines[1]
    assert "a00631e91974" in report.markdown and "4ecd96cdea45" in report.markdown
    assert [entry["world_id"] for entry in report.data["objection_clusters"]] == ["4ecd96cdea45", "a00631e91974"]


def test_reasons_to_buy_render_beside_objections_and_long_tails_fold_rather_than_drop():
    """The report answers why in both directions: what held people back and what persuaded (ADR 0053). Past the
    first ten groups the rest stay in the document, folded — nothing is dropped and nothing is counted."""
    objections = [cluster_payload(label=f"objection {k}") for k in range(12)]
    reasons = [cluster_payload(label="I would buy it for the gym")]
    report = render([finding_payload()], digests(), pack(clusters=objections, reasons=reasons))
    why = report.markdown.split("## Why")[1].split("## Findings")[0]
    held, persuaded = why.split("### What persuaded")
    assert "<details><summary>Smaller groups of objections</summary>" in held
    assert all(f'"objection {k}"' in held for k in range(12))
    assert '"I would buy it for the gym"' in persuaded
    assert report.data["reason_clusters"][0]["label"] == "I would buy it for the gym"


def test_low_confidence_findings_are_folded_after_the_rest():
    low = finding_payload(finding_id="f-objection-09", confidence="low")
    report = render([finding_payload(), low], digests(), pack())
    findings = report.markdown.split("## Findings")[1].split("## Trust")[0]
    assert findings.index("confidence medium") < findings.index("<details><summary>Low-confidence findings</summary>") < findings.index("f-objection-09")
