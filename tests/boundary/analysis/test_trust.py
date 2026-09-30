"""Phase 7: the trust guard — uncalibrated by construction, and no chat model anywhere."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from simcore.analysis import cluster_objections, digest, findings, trust_statement
from simcore.ports.fake import FakeEmbed
from simcore.schemas import Finding, TraceEvent, TrustLevel
from simcore.trace import TraceStore
from tests.boundary.trace.support import seed_header_and_entry, write_by_tick
from tests.study_builders import as_survey_answers, partition_payload, population_payload, ssr_payload

from simcore.schemas import Population


def _seeded_view(store: TraceStore):
    header, entry = seed_header_and_entry(store)
    events = [TraceEvent.model_validate(record) for record in as_survey_answers(partition_payload())["events"]]
    write_by_tick(store, events)
    return header, store.view(entry.config.run_id, header.world_id)


def test_above_uncalibrated_without_a_reference_raises():
    assert trust_statement().level is TrustLevel.UNCALIBRATED
    for level in ("category_benchmarked", "prospectively_validated"):
        with pytest.raises(ValidationError, match="requires a calibration reference"):
            trust_statement(level=level)


def test_calibration_stated_once_and_no_finding_carries_one(tmp_path):
    header, view = _seeded_view(TraceStore(tmp_path))
    trust = trust_statement()
    assert trust.level is TrustLevel.UNCALIBRATED
    assert "trust" not in set(Finding.model_fields)
    for finding in findings(view, embed=FakeEmbed(), threshold=0.99, seed=4021):
        assert "trust" not in set(type(finding).model_fields)


def test_no_path_in_the_package_calls_a_chat_model():
    root = Path(__file__).resolve().parents[3] / "simcore" / "analysis"
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "chat" in node.module:
                offenders.append(f"{path.name}: imports {node.module}")
            if isinstance(node, ast.Import) and any("chat" in alias.name for alias in node.names):
                offenders.append(f"{path.name}: imports chat")
            if isinstance(node, ast.Attribute) and node.attr in ("chat", "complete"):
                offenders.append(f"{path.name}: calls .{node.attr}()")
            if isinstance(node, ast.Name) and node.id in ("ChatPort", "FakeChat", "chat"):
                offenders.append(f"{path.name}: names {node.id}")
    assert offenders == []


def test_embedding_is_the_only_model_call_through_the_pinned_model(tmp_path):
    header, view = _seeded_view(TraceStore(tmp_path))
    population = Population.model_validate(population_payload())
    pin = header.config.pins.embed.model_id
    result = digest(view, scenario=header.scenario, population=population, seed=header.replicate_seed,
                    pinned_embed_model=pin)
    assert result.adoption is not None
    clusters = cluster_objections(view, embed=FakeEmbed(model_id=pin), pinned_embed_model=pin)
    assert all(cluster.embed_model_id == pin for cluster in clusters)


def test_trace_in_another_embedding_space_refused(tmp_path):
    header, view = _seeded_view(TraceStore(tmp_path))
    population = Population.model_validate(population_payload())
    with pytest.raises(ValueError, match="pins .* for every embedding"):
        digest(view, scenario=header.scenario, population=population, seed=header.replicate_seed,
               pinned_embed_model="other/model-1")
    with pytest.raises(ValueError, match="pins .* for every embedding"):
        cluster_objections(view, embed=FakeEmbed(), pinned_embed_model="other/model-1")
    with pytest.raises(ValueError, match="pins .* for every embedding"):
        findings(view, embed=FakeEmbed(), pinned_embed_model="other/model-1")
