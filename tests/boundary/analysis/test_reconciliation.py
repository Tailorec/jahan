"""Phase 8: reconciliation — the regenerated study digests end to end from its durable record.

Reads only the committed partitions, and only through the five trace shapes. The
evaluation's figures are produced by `digest`, not gathered beside it: every number is
asserted against a recomputation from raw events. Validating one report over both
worlds' digests fails on the old shapes, which refused two digests of one scenario.
"""

import json
from collections import Counter
from pathlib import Path

from simcore.analysis import detect_anomalies, digest, findings, spread, trust_statement
from simcore.ports.fake import FakeEmbed
from simcore.schemas import (
    EventFilter,
    Population,
    Report,
    TracePartition,
    derive_world_id,
)
from simcore.trace import derive_beliefs, derive_edges, derive_verbatims, filter_events, resolve_events

EVAL = Path(__file__).resolve().parents[3] / "docs" / "evaluations" / "m10-analysis"


class PartitionView:
    """The five questions, over a committed partition's events and nothing else."""

    def __init__(self, events):
        self._events = events

    def events(self, asked):
        return filter_events(self._events, asked)

    def beliefs(self, persona_id):
        return derive_beliefs(self._events, persona_id)

    def edges(self):
        return derive_edges(self._events)

    def verbatims(self, grouping):
        return derive_verbatims(self._events, grouping)

    def resolve(self, trace_ids):
        return resolve_events(self._events, trace_ids)


def _load():
    partitions = {}
    for path in sorted((EVAL / "partitions").glob("world-*.json")):
        partition = TracePartition.model_validate(json.loads(path.read_text()))
        assert partition.header.world_id == path.stem.removeprefix("world-")
        partitions[partition.header.world_id] = partition
    assert len(partitions) == 2
    population = Population.model_validate(json.loads((EVAL / "population.json").read_text()))
    return partitions, population


def test_regenerated_partitions_validate_and_pin_their_worlds():
    partitions, population = _load()
    first = next(iter(partitions.values()))
    assert first.header.population.population_hash == population.population_hash
    for wid, partition in partitions.items():
        header = partition.header
        assert header.world_id == derive_world_id(
            header.scenario, header.replicate_seed, header.population.population_hash)


def test_digest_numbers_match_the_record_where_both_measure_the_same_thing():
    partitions, population = _load()
    for wid, partition in sorted(partitions.items()):
        header = partition.header
        view = PartitionView(partition.events)
        result = digest(view, scenario=header.scenario, population=population,
                        seed=header.replicate_seed, pinned_embed_model=header.config.pins.embed.model_id)
        assert result.world_id == wid

        turns = [e for e in view.events(EventFilter()) if e.payload.kind == "turn"]
        assert result.turn_count == len(turns)
        assert dict(result.action_mix) == dict(Counter(e.payload.turn.reaction.action.value for e in turns))
        scored = sum(1 for e in turns if e.payload.turn.reaction.intent is not None)
        assert result.turn_count - result.turns_without_intent == scored
        assert result.wom_deliveries == sum(e.count for e in view.edges())
        assert result.adoption is not None and abs(result.adoption - 0.65) < 1e-9


def test_two_worlds_spread_report_findings_and_trust():
    partitions, population = _load()
    first = next(iter(partitions.values()))
    header, config = first.header, first.header.config
    pin = config.pins.embed.model_id
    digests = []
    for wid, partition in sorted(partitions.items()):
        view = PartitionView(partition.events)
        result = digest(view, scenario=partition.header.scenario, population=population,
                        seed=partition.header.replicate_seed, pinned_embed_model=pin)
        digests.append((partition.header.replicate_seed, wid, result))
        for finding in findings(view, embed=FakeEmbed(model_id=pin), pinned_embed_model=pin,
                                seed=partition.header.replicate_seed):
            view.resolve(tuple(finding.evidence_trace_ids))

    summary = spread(digests)
    assert summary.adoption_spread == 0.0 and summary.adoption_spread is not None
    assert summary.rung_mixed is False

    report = Report.model_validate({
        "config": config.model_dump(mode="json"),
        "trust": trust_statement().model_dump(mode="json"),
        "findings": [],
        "anomalies": [],
        "objection_clusters": [],
        "digests": [d.model_dump(mode="json") for _, _, d in digests],
    })
    assert len(report.digests) == 2
    assert report.trust.level.value == "uncalibrated"

    committed = json.loads((EVAL / "digest-report.json").read_text())
    assert [w["digest"]["adoption"] for w in committed["worlds"]] == [d.adoption for _, _, d in digests]
    assert committed["spread"]["adoption_spread"] == summary.adoption_spread
