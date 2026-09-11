"""What a person sees when their file is wrong: the file, the field, and what to fix."""

import re

import pytest
import yaml

from simcore.brief import load_brief
from simcore.brief._intake import MAX_REPORTED_PROBLEMS
from simcore.schemas import GateFailure
from tests.study_builders import load_ontology


def written(tmp_path, text: str):
    path = tmp_path / "brief.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def failure(example_brief, authored, change) -> str:
    payload = yaml.safe_load(example_brief.read_text())
    change(payload)
    path, ontology_dir = authored(payload, load_ontology())
    with pytest.raises(GateFailure) as raised:
        load_brief(path, ontology_dir)
    return str(raised.value)


def test_a_refusal_names_the_file_and_the_field(example_brief, authored):
    message = failure(example_brief, authored, lambda b: b["price"].update(currency="dollars"))
    assert "brief.yaml" in message and "price.currency" in message and "dollars" in message


def test_list_indices_follow_the_order_the_file_was_written_in(example_brief, authored):
    message = failure(example_brief, authored, lambda b: b["claims"][1].update(source="guess"))
    assert "claims[1].source" in message and "claims[0]" not in message


def test_several_problems_are_reported_together(example_brief, authored):
    def break_three(brief):
        brief["claims"][0]["source"] = "guess"
        brief["claims"][2]["source"] = "rumour"
        brief["price"]["amount"] = -1

    message = failure(example_brief, authored, break_three)
    assert message.count("\n") == 2
    assert "claims[0].source" in message and "claims[2].source" in message and "price.amount" in message


def test_a_flood_of_problems_is_capped_and_says_how_many_were_omitted(example_brief, authored):
    def break_many(brief):
        brief["claims"] = [{"text": f"claim {n}", "source": "guess"} for n in range(MAX_REPORTED_PROBLEMS + 3)]

    message = failure(example_brief, authored, break_many)
    reported, summary = message.splitlines()[:-1], message.splitlines()[-1]
    assert len(reported) == MAX_REPORTED_PROBLEMS
    omitted = int(re.search(r"and (\d+) more problems", summary).group(1))
    assert omitted >= 1


def test_a_model_wide_refusal_is_reported_without_a_field_path(example_brief, authored):
    message = failure(example_brief, authored, lambda b: b["audiences"][0]["attribute_filters"].update(spend_band="5_10"))
    assert "does not declare" in message and "::" not in message
