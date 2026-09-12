"""Fetching cited evidence through the port and recording it in the sidecar."""

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from simcore.brief import fetch_evidence
from simcore.ports import EvidencePort
from simcore.ports.memory import InMemoryEvidence
from simcore.schemas import GateFailure

MODULE = Path(__file__).resolve().parents[3] / "simcore" / "brief"
A = "https://example.com/a"
B = "https://example.com/b"


def brief_with(*urls: str) -> dict:
    return {
        "product": {"name": "Protein water", "category": "beverage_protein", "description": "clear"},
        "price": {"amount": 2.49, "currency": "USD"},
        "claims": [
            {"text": f"claim {number}", "source": "user_asserted", "evidence_url": url}
            for number, url in enumerate(urls)
        ],
        "target_market": "US adults",
        "ontology_version": "1.0.0",
    }


def sidecar_of(path: Path) -> Path:
    return path.with_name(path.name + ".evidence.json")


def entries(path: Path) -> dict:
    return json.loads(sidecar_of(path).read_text())


def test_fetching_records_an_entry_per_cited_url_keyed_by_the_url(authored):
    path, _ = authored(brief_with(A, B), None, sidecar=None)
    port = InMemoryEvidence({A: b"alpha", B: b"beta"})
    fetch_evidence(path, port)
    assert set(entries(path)) == {A, B}
    assert port.calls == [A, B]
    assert entries(path)[A]["content_hash"] == hashlib.sha256(b"alpha").hexdigest()


def test_the_bytes_are_hashed_as_received_and_the_body_is_not_stored(authored):
    path, _ = authored(brief_with(A), None, sidecar=None)
    fetch_evidence(path, InMemoryEvidence({A: b"the body"}))
    assert "the body" not in sidecar_of(path).read_text()
    assert entries(path)[A]["content_hash"] == hashlib.sha256(b"the body").hexdigest()


def test_a_partial_failure_keeps_the_successes_and_a_rerun_completes(authored):
    path, _ = authored(brief_with(A, B), None, sidecar=None)
    report = fetch_evidence(path, InMemoryEvidence({A: b"alpha"}, errors={B: OSError("dead link")}))
    assert [entry.url for entry in report.fetched] == [A]
    assert [failure.url for failure in report.failed] == [B]
    assert set(entries(path)) == {A}

    completed = fetch_evidence(path, InMemoryEvidence({B: b"beta"}))
    assert [entry.url for entry in completed.fetched] == [B]
    assert list(completed.skipped) == [A]
    assert set(entries(path)) == {A, B}


def test_a_second_run_skips_recorded_urls_and_leaves_their_hashes(authored):
    path, _ = authored(brief_with(A), None, sidecar=None)
    fetch_evidence(path, InMemoryEvidence({A: b"alpha"}))
    before = entries(path)[A]["content_hash"]
    second = InMemoryEvidence({A: b"changed"})
    report = fetch_evidence(path, second)
    assert second.calls == []
    assert list(report.skipped) == [A]
    assert entries(path)[A]["content_hash"] == before


def test_an_explicit_refetch_replaces_an_entry_and_reports_the_change(authored):
    path, _ = authored(brief_with(A), None, sidecar=None)
    first = fetch_evidence(path, InMemoryEvidence({A: b"alpha"}))
    second = fetch_evidence(path, InMemoryEvidence({A: b"beta"}), refetch=True)
    assert second.fetched[0].content_hash == hashlib.sha256(b"beta").hexdigest()
    assert second.fetched[0].content_hash != first.fetched[0].content_hash
    assert entries(path)[A]["content_hash"] == second.fetched[0].content_hash


def test_a_brief_citing_nothing_fetches_nothing(authored):
    path, _ = authored(brief_with(), None, sidecar=None)
    port = InMemoryEvidence()
    report = fetch_evidence(path, port)
    assert report.fetched == () and report.skipped == () and report.failed == ()
    assert port.calls == []
    assert not sidecar_of(path).exists()


def test_an_entry_no_claim_cites_survives_a_fetch(authored):
    path, _ = authored(brief_with(A), None, sidecar=None)
    sidecar_of(path).write_text(
        json.dumps({"https://example.com/old": {"content_hash": "cd" * 32, "fetched_at": "2020-01-01T00:00:00Z"}})
    )
    fetch_evidence(path, InMemoryEvidence({A: b"alpha"}))
    assert "https://example.com/old" in entries(path)


@pytest.mark.parametrize("cited", [None, "", "   "], ids=["null", "empty", "whitespace"])
def test_a_citation_naming_no_url_is_refused_when_fetching_too(authored, cited):
    brief = brief_with(A)
    brief["claims"][0]["evidence_url"] = cited
    path, _ = authored(brief, sidecar=None)
    with pytest.raises(GateFailure, match=r"claims\[0\]\.evidence_url: cite a url or leave the field out"):
        fetch_evidence(path, InMemoryEvidence({A: b"a"}))


def test_a_sidecar_recording_a_url_twice_is_refused_before_it_is_rewritten(authored):
    """What loading refuses, fetching must not quietly accept — and then rewrite, keeping one."""
    entry = '{"content_hash": "%s", "fetched_at": "2026-09-01T00:00:00Z"}' % ("ab" * 32)
    path, _ = authored(brief_with(A, B), sidecar='{"%s": %s, "%s": %s}' % (A, entry, A, entry))
    before = sidecar_of(path).read_text()
    with pytest.raises(GateFailure, match="is given more than once"):
        fetch_evidence(path, InMemoryEvidence({A: b"a", B: b"b"}))
    assert sidecar_of(path).read_text() == before


def test_a_sidecar_that_is_not_a_mapping_is_refused_by_the_fetcher_too(authored):
    path, _ = authored(brief_with(A), sidecar="[1, 2]")
    with pytest.raises(GateFailure, match="must be a mapping of cited URLs"):
        fetch_evidence(path, InMemoryEvidence({A: b"a"}))


def test_an_interrupted_write_leaves_the_sidecar_untouched(authored, monkeypatch):
    path, _ = authored(brief_with(A), None, sidecar=None)
    fetch_evidence(path, InMemoryEvidence({A: b"alpha"}))
    before = sidecar_of(path).read_text()
    real_replace = os.replace

    def interrupted(source, destination):
        if Path(destination) == sidecar_of(path):
            raise OSError("simulated interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(GateFailure, match="could not be written"):
        fetch_evidence(path, InMemoryEvidence({A: b"beta"}), refetch=True)
    assert sidecar_of(path).read_text() == before
    assert list(sidecar_of(path).parent.glob("*.tmp")) == []


# --- what the module may reach -----------------------------------------------------------------


def test_the_in_memory_adapter_satisfies_the_port():
    assert isinstance(InMemoryEvidence(), EvidencePort)


def test_fetching_reaches_the_network_only_through_the_port():
    source = (MODULE / "_fetch.py").read_text()
    for forbidden in ("import socket", "urllib", "requests", "httpx", "http.client", "urlopen"):
        assert forbidden not in source, f"fetching must reach the network only through the port, not {forbidden}"


def core_port_imports():
    for path in sorted(MODULE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("simcore.ports"):
                yield path, node.module, [alias.name for alias in node.names]


def test_no_core_module_imports_a_concrete_adapter():
    for path, module, names in core_port_imports():
        assert (module, names) == ("simcore.ports", ["EvidencePort"]), (
            f"{path.name} imports {names} from {module}: core imports the protocol only"
        )
