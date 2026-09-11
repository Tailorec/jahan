import pytest
from pydantic import ValidationError

from simcore.schemas import Completion, CostRecorded
from tests.study_builders import events_of_representative_cost


def completion(**overrides) -> dict:
    payload = {
        "text": "I would probably try it after training.",
        "template_id": "persona_turn",
        "prompt_hash": "12" * 32,
        "latency_ms": 840,
        "cost": events_of_representative_cost(),
    }
    payload.update(overrides)
    return payload


def test_completion_carries_text_template_prompt_hash_latency_and_its_cost_record():
    parsed = Completion.model_validate(completion())
    assert (parsed.text, parsed.template_id, parsed.prompt_hash, parsed.latency_ms) == (
        "I would probably try it after training.", "persona_turn", "12" * 32, 840)
    assert isinstance(parsed.cost, CostRecorded) and parsed.cost.kind == "cost"
    assert Completion.model_validate_json(parsed.model_dump_json()) == parsed


def test_the_cost_record_is_the_one_the_trace_receives():
    parsed = Completion.model_validate(completion())
    assert CostRecorded.model_validate(parsed.cost.model_dump(mode="json")) == parsed.cost


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"latency_ms": -1}, "latency_ms"),
        ({"prompt_hash": "not-a-hash"}, "prompt_hash"),
        ({"cost": {**events_of_representative_cost(), "role": "embed", "model_id": "openai/text-embedding-3-small"}}, "vectors, not completions"),
    ],
    ids=["negative-latency", "malformed-prompt-hash", "embedding-role"],
)
def test_completion_refuses_what_a_chat_call_cannot_return(overrides, match):
    with pytest.raises(ValidationError, match=match):
        Completion.model_validate(completion(**overrides))


def test_an_empty_response_is_still_a_completion():
    assert Completion.model_validate(completion(text="")).text == ""
