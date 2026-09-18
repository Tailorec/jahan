"""Phase 5: findings authored by extraction — objection, belief-shift and word-of-mouth."""

import pytest
from pydantic import ValidationError

from simcore.analysis import findings
from simcore.ports.fake import FakeEmbed
from simcore.schemas import Finding, TraceEvent
from simcore.trace import TraceStore
from tests.boundary.trace.support import seed_header_and_entry, write_by_tick
from tests.study_builders import partition_payload


def _seeded_view(store: TraceStore):
    header, entry = seed_header_and_entry(store)
    events = [TraceEvent.model_validate(record) for record in partition_payload()["events"]]
    write_by_tick(store, events)
    return store.view(entry.config.run_id, header.world_id)


def test_objection_belief_shift_and_wom_findings_authored_from_one_trace(tmp_path):
    view = _seeded_view(TraceStore(tmp_path))
    authored = findings(view, embed=FakeEmbed(), threshold=0.99, seed=4021)
    kinds = {finding.kind.value for finding in authored}
    assert {"objection", "belief_shift", "wom_path"} <= kinds


def test_every_finding_resolves_against_the_view_at_authorship(tmp_path):
    view = _seeded_view(TraceStore(tmp_path))
    for finding in findings(view, embed=FakeEmbed(), threshold=0.99, seed=4021):
        assert view.resolve(tuple(finding.evidence_trace_ids))
    with pytest.raises(KeyError, match="no events for trace ids"):
        view.resolve(("ev-00000000000000000000000000",))
    with pytest.raises(ValidationError):
        Finding.model_validate({
            "finding_id": "f-empty-01", "kind": "risk", "statement": "no evidence",
            "evidence_trace_ids": [], "disconfirming_test": "x", "confidence": "low",
        })
    with pytest.raises(ValidationError):
        Finding.model_validate({
            "finding_id": "f-untestable-01", "kind": "risk", "statement": "no test",
            "evidence_trace_ids": [f"ev-{'0' * 21}00001"], "disconfirming_test": "  ", "confidence": "low",
        })


def test_two_runs_produce_the_same_findings_in_the_same_order(tmp_path):
    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    events = [TraceEvent.model_validate(record) for record in partition_payload()["events"]]
    write_by_tick(store, events)
    first = findings(store.view(entry.config.run_id, header.world_id), embed=FakeEmbed(), threshold=0.99, seed=4021)
    second = findings(store.view(entry.config.run_id, header.world_id), embed=FakeEmbed(), threshold=0.99, seed=4021)
    assert [f.model_dump() for f in first] == [f.model_dump() for f in second]
    assert len({f.finding_id for f in first}) == len(first)


def test_no_finding_states_calibration_and_confidence_ignores_it(tmp_path):
    view = _seeded_view(TraceStore(tmp_path))
    for finding in findings(view, embed=FakeEmbed(), threshold=0.99, seed=4021):
        assert "calibrat" not in finding.statement.lower()
        assert "calibrat" not in finding.disconfirming_test.lower()
        assert finding.confidence.value in {"low", "medium", "high"}
        assert "trust" not in set(type(finding).model_fields)
