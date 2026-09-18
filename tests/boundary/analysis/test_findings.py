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


class _VerbatimView:
    """A view over caller-supplied verbatims alone: no turns, no edges, resolve by id."""

    def __init__(self, said: list[tuple[str, str]]):
        from simcore.schemas import VerbatimGroup, VerbatimGrouping, VerbatimRecord

        self._records = [
            VerbatimRecord.model_validate({
                "event_id": f"ev-{'0' * 21}{index:05d}", "persona_id": persona, "tick": index,
                "subject_stimulus_id": f"st-{'0' * 21}{index:05d}", "action": "comment", "text": text,
            })
            for index, (persona, text) in enumerate(said)
        ]
        by_persona: dict[str, list] = {}
        for record in self._records:
            by_persona.setdefault(record.persona_id, []).append(record)
        self._groups = tuple(
            VerbatimGroup(grouping=VerbatimGrouping.PERSONA, key=persona, records=tuple(items))
            for persona, items in sorted(by_persona.items())
        )

    def verbatims(self, grouping):
        return self._groups

    def events(self, _filter):
        return ()

    def edges(self):
        return ()

    def resolve(self, trace_ids):
        known = {record.event_id for record in self._records}
        missing = sorted(set(trace_ids) - known)
        if missing:
            raise KeyError(f"no events for trace ids: {missing}")
        return tuple(record for record in self._records if record.event_id in set(trace_ids))


def test_an_objection_finding_counts_the_personas_not_the_verbatims(tmp_path):
    """One persona saying the same thing three times is one persona, not three."""
    from tests.boundary.analysis.test_clusters import _TopicalEmbed

    view = _VerbatimView([("p-000001", "too pricey"), ("p-000001", "the price is too much"),
                          ("p-000001", "far too expensive for what it is")])
    authored = [f for f in findings(view, embed=_TopicalEmbed(), threshold=0.75, seed=1)
                if f.kind.value == "objection"]
    assert len(authored) == 1
    assert len(authored[0].evidence_trace_ids) == 3
    assert authored[0].statement.startswith("1 persona ")
    assert "3 verbatims" in authored[0].statement


def test_an_objection_finding_states_what_was_measured_not_a_sentiment(tmp_path):
    """Clustering groups what personas said; it cannot tell praise from an objection, so the
    statement quotes and counts rather than characterising."""
    from tests.boundary.analysis.test_clusters import _TopicalEmbed

    view = _VerbatimView([("p-000001", "I would buy this tomorrow"), ("p-000002", "I would buy this tomorrow")])
    authored = [f for f in findings(view, embed=_TopicalEmbed(), threshold=0.75, seed=1)
                if f.kind.value == "objection"]
    assert len(authored) == 1
    assert "objection" not in authored[0].statement.lower()
    assert "I would buy this tomorrow" in authored[0].statement
