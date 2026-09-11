import copy
import json
from pathlib import Path

import pytest
import yaml

from simcore.brief import load_brief
from simcore.schemas import BriefPack, GateFailure
from tests.study_builders import load_ontology

MODULE = Path(__file__).resolve().parents[3] / "simcore" / "brief"


def brief_payload(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_the_shipped_example_loads_into_the_pack_it_describes(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assert isinstance(pack, BriefPack)
    assert pack.brief.product.name == "Protein water"
    assert [claim.text for claim in pack.brief.claims][0] == "20g protein with zero sugar"
    assert [audience.name for audience in pack.brief.audiences] == ["gym_regulars", "protein_dieters"]
    assert pack.ontology.category == pack.brief.product.category
    assert pack.ontology.version == pack.brief.ontology_version


def test_claims_are_identified_in_the_order_they_were_authored(example_brief, ontologies):
    assert [claim.id for claim in load_brief(example_brief, ontologies).brief.claims] == ["C1", "C2", "C3"]


def test_a_brief_naming_an_ontology_version_that_does_not_exist_is_refused(example_brief, ontologies, tmp_path):
    with pytest.raises(GateFailure, match="no ontology for category 'beverage_protein' at version '1.0.0'"):
        load_brief(example_brief, tmp_path / "empty")


def test_a_brief_that_is_not_on_disk_is_refused(ontologies, tmp_path):
    with pytest.raises(GateFailure, match="cannot be read"):
        load_brief(tmp_path / "absent.yaml", ontologies)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda b: b.update(unexpected_key=True), "unexpected_key"),
        (lambda b: b.pop("target_market"), "target_market"),
        (lambda b: b["price"].update(amount=-1.0), "price"),
        (lambda b: b["claims"][0].update(source="guess"), "source"),
        (lambda b: b["audiences"][0]["attribute_filters"].update(favourite_colour="blue"), "does not declare"),
    ],
    ids=["unknown-key", "missing-field", "impossible-price", "invented-source", "undeclared-filter"],
)
def test_a_brief_the_contract_refuses_is_a_gate_failure(example_brief, authored, change, match):
    payload = brief_payload(example_brief)
    change(payload)
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match=match):
        load_brief(path, ontology_dir)


def test_an_ontology_that_is_not_valid_json_is_refused(example_brief, authored, tmp_path):
    path, ontology_dir = authored(brief_payload(example_brief), load_ontology())
    (ontology_dir / "beverage_protein" / "1.0.0.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GateFailure, match="is not valid JSON"):
        load_brief(path, ontology_dir)


def test_an_ontology_the_contract_refuses_is_a_gate_failure(example_brief, authored):
    broken = copy.deepcopy(load_ontology())
    broken["conditioning_set"] = []
    path, ontology_dir = authored(brief_payload(example_brief), broken)
    with pytest.raises(GateFailure, match="conditioning_set"):
        load_brief(path, ontology_dir)


# --- what intake may not do -------------------------------------------------------------------


def test_intake_reaches_no_network_and_reads_no_clock():
    source = "\n".join(p.read_text() for p in MODULE.glob("*.py"))
    for forbidden in ("import socket", "urllib", "requests", "httpx", "datetime", "time.time", "os.environ", "getenv"):
        assert forbidden not in source, f"loading a brief must not use {forbidden}"


def test_the_modules_public_surface_is_loading_a_brief():
    import simcore.brief as module

    assert module.__all__ == ["load_brief"]
    assert not [name for name in vars(module) if name.startswith(("fetch", "write", "Brief_"))]
