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


def test_belief_shift_and_wom_findings_authored_from_one_trace_and_no_objection_from_praise(tmp_path):
    """The built trace's verbatims are all favourable, so it authors belief shifts and word-of-mouth paths and,
    since ADR 0053, no objection: praise is not one."""
    view = _seeded_view(TraceStore(tmp_path))
    authored = findings(view, embed=FakeEmbed(), threshold=0.99, seed=4021)
    kinds = {finding.kind.value for finding in authored}
    assert {"belief_shift", "wom_path"} <= kinds and "objection" not in kinds


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
    """A view over caller-supplied verbatims and the turns that said them: each an objection unless `objects` is
    false; no edges, resolve by id."""

    def __init__(self, said: list[tuple[str, str]], objects: bool = True):
        self._objects = objects
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
        from tests.boundary.analysis.test_clusters import objecting_turns

        return objecting_turns(self._records, objects=self._objects)

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


def test_praise_is_not_an_objection(tmp_path):
    """ADR 0053: objection findings come from verbatims whose turns objected. Praise, however often it is said,
    is not an objection, and an objection is quoted and counted rather than characterised."""
    from tests.boundary.analysis.test_clusters import _TopicalEmbed

    praise = _VerbatimView([("p-000001", "I would buy this tomorrow"), ("p-000002", "I would buy this tomorrow")], objects=False)
    assert [f for f in findings(praise, embed=_TopicalEmbed(), threshold=0.75, seed=1) if f.kind.value == "objection"] == []
    doubt = _VerbatimView([("p-000001", "too pricey for me"), ("p-000002", "too pricey for me")])
    authored = [f for f in findings(doubt, embed=_TopicalEmbed(), threshold=0.75, seed=1) if f.kind.value == "objection"]
    assert len(authored) == 1 and "too pricey for me" in authored[0].statement


class _MovesOnlyView:
    """A view over caller-supplied belief moves alone: turns with a change and nothing else."""

    def __init__(self, moves: list[tuple[str, float]]):
        from types import SimpleNamespace

        self._events = tuple(
            SimpleNamespace(
                payload=SimpleNamespace(kind="turn", turn=SimpleNamespace(
                    reaction=SimpleNamespace(verbatim=None, belief_change=SimpleNamespace(
                        dimensions={dim: delta}, claim_credence={})))),
                tick=index, seq=index, event_id=f"ev-{'0' * 21}{index:05d}", persona_id=f"p-00000{index}")
            for index, (dim, delta) in enumerate(moves)
        )

    def events(self, _filter):
        return self._events

    def verbatims(self, _grouping):
        return ()

    def edges(self):
        return ()

    def resolve(self, trace_ids):
        known = {event.event_id for event in self._events}
        missing = sorted(set(trace_ids) - known)
        if missing:
            raise KeyError(f"no events for trace ids: {missing}")
        return trace_ids


def test_a_shift_too_small_to_state_is_not_a_finding():
    """Two moves of a thousandth clear no bar; stating them prints "rose by 0.00", which is a
    claim about nothing."""
    view = _MovesOnlyView([("value", 0.001), ("value", 0.001)])
    assert [f for f in findings(view, embed=None) if f.kind.value == "belief_shift"] == []


def test_moves_that_cancel_are_not_reported_as_a_direction():
    """Ten moves up and ten down average exactly zero: a report that says they "fell" is wrong."""
    view = _MovesOnlyView([("value", 0.2)] * 10 + [("value", -0.2)] * 10)
    assert [f for f in findings(view, embed=None) if f.kind.value == "belief_shift"] == []


def test_a_small_shift_held_across_many_moves_is_still_a_finding():
    view = _MovesOnlyView([("value", 0.03)] * 12)
    authored = [f for f in findings(view, embed=None) if f.kind.value == "belief_shift"]
    assert len(authored) == 1
    assert "rose by 0.03" in authored[0].statement


def test_findings_of_two_worlds_do_not_collide_by_id(tmp_path):
    """A study runs the same scenario under several seeds. Numbering findings within a world
    alone gives every world an `f-objection-01`, so a report over two worlds holds two findings
    with one id and no way to tell them apart — which `Report` refuses outright."""
    from tests.boundary.analysis.test_clusters import _TopicalEmbed

    said = [("p-000001", "too pricey"), ("p-000002", "the price is too much")]
    first = findings(_VerbatimView(said), embed=_TopicalEmbed(), seed=1, world_id="a00631e91974")
    second = findings(_VerbatimView(said), embed=_TopicalEmbed(), seed=1, world_id="4ecd96cdea45")
    assert first and second
    assert not ({f.finding_id for f in first} & {f.finding_id for f in second})
    assert all("a00631e91974" in f.finding_id for f in first)


def test_a_finding_without_a_world_is_numbered_as_before():
    from tests.boundary.analysis.test_clusters import _TopicalEmbed

    authored = findings(_VerbatimView([("p-000001", "too pricey")]), embed=_TopicalEmbed(), seed=1)
    assert [f.finding_id for f in authored] == ["f-objection-01"]


def test_risk_findings_authored_from_recorded_anomalies():
    from simcore.analysis import risk_findings
    from simcore.schemas import Anomaly, AnomalyKind

    sc_hash = "0" * 64
    anomalies = [
        Anomaly.model_validate({
            "kind": AnomalyKind.HERDING,
            "scenario_hash": sc_hash,
            "tick": 3,
            "evidence_trace_ids": [f"ev-{'0' * 25}1"],
            "threshold": 0.15,
            "observed": 0.35,
        })
    ]
    risks = risk_findings(anomalies, world_id="w-01")
    assert len(risks) == 1
    r = risks[0]
    assert r.kind.value == "risk"
    assert "herding" in r.statement and "0.35" in r.statement
    assert r.evidence_trace_ids == (f"ev-{'0' * 25}1",)
    assert "neutral seed" in r.disconfirming_test
    assert r.confidence.value == "high"


def test_ranking_findings_authored_with_spread_and_survives():
    from simcore.analysis import ranking_findings
    from simcore.schemas import OutcomeDigest
    from tests.study_builders import digest_payload, scenario_payload

    s1 = scenario_payload()
    s2 = scenario_payload()
    s2["variant"]["variant_id"] = "v-other"
    d1 = OutcomeDigest.model_validate(digest_payload(s1, seed=4021))
    d2 = OutcomeDigest.model_validate(digest_payload(s2, seed=4021))

    rankings = ranking_findings([d1, d2], world_id="w-rank")
    assert len(rankings) == 1
    rk = rankings[0]
    assert rk.kind.value == "ranking"
    assert len(rk.ranked_scenarios) == 2
    assert "replicate spread" in rk.statement
    assert "ordering survives" in rk.statement or "does not survive" in rk.statement
    assert rk.confidence.value in ("high", "low")

