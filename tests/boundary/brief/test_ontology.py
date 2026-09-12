"""Resolving the category ontology: one exact version, one path, and a file that agrees with it."""

import copy

import pytest
import yaml

from simcore.brief import load_brief
from simcore.schemas import GateFailure
from tests.study_builders import load_ontology


def payload_of(example_brief) -> dict:
    return yaml.safe_load(example_brief.read_text())


@pytest.mark.parametrize("version", ["latest", "1.x", "1.0.0.latest", "x"])
def test_a_floating_ontology_version_is_refused(example_brief, authored, version):
    payload = payload_of(example_brief)
    payload["ontology_version"] = version
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match="exact version"):
        load_brief(path, ontology_dir)


@pytest.mark.parametrize("version", ["*", ">=1.0.0", "~1.0.0", "^1.0.0", "1.*"])
def test_a_wildcard_or_range_ontology_version_is_refused(example_brief, authored, version):
    payload = payload_of(example_brief)
    payload["ontology_version"] = version
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match="ontology_version"):
        load_brief(path, ontology_dir)


def test_a_missing_version_names_the_path_and_lists_the_versions_present(example_brief, authored):
    payload = payload_of(example_brief)
    payload["ontology_version"] = "9.9.9"
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure) as raised:
        load_brief(path, ontology_dir)
    message = str(raised.value)
    assert "9.9.9.json" in message
    assert "versions present: '1.0.0'" in message


def test_a_category_with_no_directory_is_refused_distinctly_from_a_missing_version(example_brief, authored, tmp_path):
    payload = payload_of(example_brief)
    path, _ = authored(payload, load_ontology())
    with pytest.raises(GateFailure) as no_directory:
        load_brief(path, tmp_path / "nowhere")
    assert "does not exist" in str(no_directory.value)
    assert "versions present" not in str(no_directory.value)

    payload["ontology_version"] = "9.9.9"
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure) as missing_version:
        load_brief(path, ontology_dir)
    assert "versions present" in str(missing_version.value)
    assert "does not exist" not in str(missing_version.value)


def test_an_ontology_declaring_another_category_than_its_path_is_refused(example_brief, authored):
    ontology = copy.deepcopy(load_ontology())
    ontology["category"] = "snack_bar"
    path, ontology_dir = authored(payload_of(example_brief), ontology)
    with pytest.raises(GateFailure, match=r"declares category 'snack_bar'.*path says 'beverage_protein'"):
        load_brief(path, ontology_dir)


def test_an_ontology_declaring_another_version_than_its_path_is_refused(example_brief, authored):
    ontology = copy.deepcopy(load_ontology())
    ontology["version"] = "2.0.0"
    path, ontology_dir = authored(payload_of(example_brief), ontology)
    with pytest.raises(GateFailure, match=r"at version '2.0.0'.*path says 'beverage_protein' at version '1.0.0'"):
        load_brief(path, ontology_dir)


@pytest.mark.parametrize("field", ["category", "version"])
def test_a_component_that_escapes_the_ontology_directory_is_refused_by_the_contract(example_brief, authored, field):
    payload = payload_of(example_brief)
    if field == "category":
        payload["product"]["category"] = "../../etc"
    else:
        payload["ontology_version"] = "../../secret"
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure, match=field):
        load_brief(path, ontology_dir)


def test_a_key_repeated_in_an_ontology_file_is_refused(example_brief, authored, tmp_path):
    path, ontology_dir = authored(payload_of(example_brief), load_ontology())
    ontology = ontology_dir / "beverage_protein" / "1.0.0.json"
    ontology.write_text('{"category": "beverage_protein", "category": "snack_bar"}', encoding="utf-8")
    with pytest.raises(GateFailure, match=r"the key 'category' is given more than once"):
        load_brief(path, ontology_dir)
