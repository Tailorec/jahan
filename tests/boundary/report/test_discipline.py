"""Phase 5: nothing computed here — the renderer cannot smuggle a claim."""

import ast
import json
import re
from pathlib import Path

from simcore.report import render
from simcore.schemas import Finding, OutcomeDigest, canonical_hash
from tests.boundary.report.support import digests, finding_payload, pack
from tests.boundary.report.test_findings_page import cluster_payload

REPORT_DIR = Path(__file__).resolve().parents[3] / "simcore" / "report"


def _trees():
    return [(path, ast.parse(path.read_text())) for path in sorted(REPORT_DIR.glob("*.py"))]


def test_the_package_imports_nothing_from_analysis():
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "simcore":
                if "analysis" in (node.module or "").split("."):
                    offenders.append(f"{path.name}: imports {node.module}")
            if isinstance(node, ast.Import) and any(
                alias.name.split(".")[:2] == ["simcore", "analysis"] for alias in node.names
            ):
                offenders.append(f"{path.name}: imports analysis")
    assert offenders == []


def test_no_arithmetic_on_findings_or_digests_beyond_formatting():
    # String concatenation is formatting; every other binary operator derives.
    forbidden_ops = (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult)
    forbidden_calls = {"sum", "min", "max", "abs", "round", "pow"}
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, forbidden_ops):
                offenders.append(f"{path.name}:{node.lineno}: arithmetic {type(node.op).__name__}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                offenders.append(f"{path.name}:{node.lineno}: computes with {node.func.id}()")
    assert offenders == []


def test_a_number_in_the_report_always_appears_in_what_it_came_from():
    findings = [Finding.model_validate(finding_payload())]
    worlds = [OutcomeDigest.model_validate(digest) for digest in digests()]
    pack_ = pack(clusters=[cluster_payload()])
    allowed = json.dumps({
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "digests": [digest.model_dump(mode="json") for digest in worlds],
        "config": pack_.config.model_dump(mode="json"),
        "trust": pack_.trust.model_dump(mode="json"),
        "brief": pack_.brief_pack.model_dump(mode="json"),
        "clusters": [cluster.model_dump(mode="json") for cluster in pack_.clusters],
        "anomalies": [anomaly.model_dump(mode="json") for anomaly in pack_.anomalies],
        "validation": pack_.validation,
        "engine_commit": pack_.engine_commit,
        "forced_from": list(pack_.forced_from),
        "contract_version": pack_.contract_version,
        "config_hash": canonical_hash(pack_.config),
    })
    report = render(findings, worlds, pack_)
    numbers = set(re.findall(r"\d+(?:\.\d+)?", report.markdown))
    assert numbers, "the report carries numbers to check"
    for number in sorted(numbers):
        assert number in allowed, f"{number} is printed but appears in no digest, finding or pack field"
