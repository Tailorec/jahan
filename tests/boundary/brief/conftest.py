"""Paths the boundary tests exercise: the repository's own shipped artifacts, not copies."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def example_brief() -> Path:
    return REPO / "examples" / "protein_water.yaml"


@pytest.fixture
def ontologies() -> Path:
    return REPO / "ontologies"


@pytest.fixture
def authored(tmp_path):
    """Write a brief, and any ontologies it needs, into a temporary tree and return both paths.

    `sidecar` controls the machine-written evidence beside the brief: "auto" derives a valid
    entry per cited URL, a mapping is written as given, a string is written verbatim (to make
    it malformed), and None writes no sidecar at all."""
    import json

    import yaml

    def write(
        brief: dict,
        ontology: dict | None = None,
        *,
        category="beverage_protein",
        version="1.0.0",
        sidecar: dict | str | None = "auto",
    ) -> tuple[Path, Path]:
        path = tmp_path / "brief.yaml"
        path.write_text(yaml.safe_dump(brief, sort_keys=False), encoding="utf-8")
        directory = tmp_path / "ontologies"
        if ontology is not None:
            (directory / category).mkdir(parents=True, exist_ok=True)
            (directory / category / f"{version}.json").write_text(json.dumps(ontology), encoding="utf-8")
        if sidecar == "auto":
            sidecar = {
                claim["evidence_url"]: {"content_hash": "ab" * 32, "fetched_at": "2026-09-01T00:00:00Z"}
                for claim in brief.get("claims", [])
                if isinstance(claim, dict) and claim.get("evidence_url")
            }
        if sidecar is not None:
            text = sidecar if isinstance(sidecar, str) else json.dumps(sidecar)
            path.with_name(path.name + ".evidence.json").write_text(text, encoding="utf-8")
        return path, directory

    return write
