"""Perf and volume: the quickstart is fast, the graph scales, and gates hold across seeds."""

import time
from pathlib import Path

import pytest

from simcore.population import _graph, build
from simcore.population._assess import REFERENCE_CAP
from simcore.population._project import project
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack
from tests.study_builders import pack_payload

REPO = Path(__file__).resolve().parents[3]


def shape() -> SyntheticShape:
    return SyntheticShape(
        {
            "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
            "sex": AttributeShape(("female", "male")),
            "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
            "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            "spend_band": AttributeShape(("5_10", "10_20")),
        },
        rows=20000,
    )


def pack() -> BriefPack:
    return BriefPack.model_validate(pack_payload())


def test_building_two_thousand_personas_against_the_synthetic_source_and_fake_is_under_five_seconds():
    source = SyntheticCoresetSource(shape(), seed=11)
    started = time.perf_counter()
    result = build(pack(), 2000, 4021, coreset=source, inference=FakeChat())
    assert time.perf_counter() - started < 5.0
    assert len(result.population.personas) == 2000


def test_rewiring_candidate_sampling_keeps_graph_generation_from_growing_with_the_square(monkeypatch):
    pack_ = pack()
    source = SyntheticCoresetSource(shape(), seed=11)
    conditioning = tuple(sorted(pack_.ontology.conditioning_set))
    rows = list(source.rows(source.matching({}, present=conditioning)[:800]))
    personas = project(pack_, rows[:800], source, inference=FakeChat()).personas

    calls: list[int] = []
    original = _graph._similarity

    def counting(a, b, ontology):
        calls.append(1)
        return original(a, b, ontology)

    monkeypatch.setattr(_graph, "_similarity", counting)
    measured = {}
    for count in (200, 400):
        calls.clear()
        _graph.build_graph(pack_, personas[:count], population_seed=4021)
        measured[count] = len(calls)
    assert measured[400] < 4 * measured[200]  # linear in the population, not quadratic


def test_graph_gates_hold_across_twenty_seeds():
    pack_ = pack()
    source = SyntheticCoresetSource(shape(), seed=11)
    conditioning = tuple(sorted(pack_.ontology.conditioning_set))
    rows = list(source.rows(source.matching({}, present=conditioning)[:300]))
    personas = project(pack_, rows, source, inference=FakeChat()).personas
    for population_seed in range(1, 21):
        graph_build = _graph.build_graph(pack_, personas, population_seed=population_seed)
        assert all(result.passed for result in graph_build.results), population_seed


class RecordingSource:
    def __init__(self, inner: SyntheticCoresetSource) -> None:
        self.inner = inner
        self.row_calls: list[int] = []

    def matching(self, predicates, present):
        return self.inner.matching(predicates, present)

    def rows(self, ids):
        ids = tuple(ids)
        self.row_calls.append(len(ids))
        return self.inner.rows(ids)

    def values(self, attribute):
        return self.inner.values(attribute)


def test_a_larger_population_builds_without_loading_every_row_it_considered():
    recorder = RecordingSource(SyntheticCoresetSource(shape(), seed=11))
    build(pack(), 200, 4021, coreset=recorder, inference=FakeChat())
    assert recorder.row_calls
    assert max(recorder.row_calls) <= max(200, REFERENCE_CAP)


def test_the_population_module_reaches_no_network_of_its_own():
    for path in sorted((REPO / "simcore" / "population").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("import socket", "urllib", "requests", "httpx"):
            assert forbidden not in source, f"{path.name} reaches the network with {forbidden}"
