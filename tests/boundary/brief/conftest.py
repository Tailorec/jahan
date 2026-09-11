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
    """Write a brief, and any ontologies it needs, into a temporary tree and return both paths."""
    import yaml

    def write(brief: dict, ontology: dict | None = None, *, category="beverage_protein", version="1.0.0") -> tuple[Path, Path]:
        path = tmp_path / "brief.yaml"
        path.write_text(yaml.safe_dump(brief, sort_keys=False), encoding="utf-8")
        directory = tmp_path / "ontologies"
        if ontology is not None:
            (directory / category).mkdir(parents=True, exist_ok=True)
            (directory / category / f"{version}.json").write_text(__import__("json").dumps(ontology), encoding="utf-8")
        return path, directory

    return write
