"""The shape of the file itself: what a parser would accept but a study must not."""

import pytest

from simcore.brief import load_brief
from simcore.schemas import GateFailure


def written(tmp_path, text: str):
    path = tmp_path / "brief.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_repeated_key_is_refused_and_named(tmp_path, ontologies):
    path = written(tmp_path, "product:\n  name: Protein water\nclaims: []\nclaims: []\n")
    with pytest.raises(GateFailure, match=r"the key 'claims' is given more than once \(line 4\)"):
        load_brief(path, ontologies)


def test_a_repeated_key_nested_inside_the_file_is_refused(tmp_path, ontologies):
    path = written(tmp_path, "product:\n  name: Protein water\n  name: Something else\n")
    with pytest.raises(GateFailure, match="the key 'name' is given more than once"):
        load_brief(path, ontologies)


def test_an_empty_file_is_refused_as_empty(tmp_path, ontologies):
    with pytest.raises(GateFailure, match="is empty"):
        load_brief(written(tmp_path, "# nothing but a comment\n"), ontologies)


@pytest.mark.parametrize(
    ("text", "match"),
    [("- one\n- two\n", "not a list"), ("just some text\n", "not text"), ("42\n", "not a number")],
    ids=["a-list", "a-string", "a-number"],
)
def test_a_file_that_is_not_a_mapping_is_refused_as_such(tmp_path, ontologies, text, match):
    with pytest.raises(GateFailure, match=f"must be a mapping of fields at its top level, {match}"):
        load_brief(written(tmp_path, text), ontologies)


def test_malformed_yaml_is_refused_without_a_parser_traceback(tmp_path, ontologies):
    with pytest.raises(GateFailure, match="is not valid YAML"):
        load_brief(written(tmp_path, "product:\n  name: [unclosed\n"), ontologies)


# --- what survives for a debugger -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["product:\n  name: [unclosed\n", "claims: []\nclaims: []\n", "product:\n  name: x\n"],
    ids=["malformed", "duplicate-key", "contract-refusal"],
)
def test_every_refusal_chains_the_cause_it_came_from(tmp_path, ontologies, text):
    with pytest.raises(GateFailure) as raised:
        load_brief(written(tmp_path, text), ontologies)
    assert raised.value.__cause__ is not None
