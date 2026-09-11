import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    EventId,
    TraceEvent,
    TracePayload,
)

VALID_ULID = "01j7x9k2m3n4p5q6r7s8t9v0wx"
EVENT_ID = f"ev-{VALID_ULID}"


def exposure_payload():
    return {
        "kind": "exposure",
        "persona_id": "p-000042",
        "exposure": {
            "stimulus_id": f"st-{VALID_ULID}",
            "reason": "recsys_rank_2",
            "attention": 0.8,
            "seen": True,
        },
    }


def event_payload(**overrides):
    payload = {
        "event_id": EVENT_ID,
        "world_id": "a1b2c3d4e5f6",
        "tick": 7,
        "agent_id": "p-000042",
        "seq": 3,
        "payload": exposure_payload(),
    }
    payload.update(overrides)
    return payload


def payload_of(kind: str, **fields):
    fields.pop("kind", None)
    return event_with_payload(kind, fields)


def event_with_payload(kind: str, fields: dict) -> dict:
    body = {key: value for key, value in fields.items() if key != "kind"}
    return event_payload(payload={"kind": kind, **body})


def test_event_with_mismatched_payload_kind_refused():
    with pytest.raises(ValidationError):
        TraceEvent.model_validate(payload_of("cost", stimulus_id=f"st-{VALID_ULID}"))


def test_each_payload_kind_is_a_distinct_type_and_dispatches_on_kind_alone():
    cases = {
        "stimulus_published": {
            "stimulus": {
                "stimulus_id": f"st-{VALID_ULID}",
                "tick": 1,
                "kind": "claim_post",
                "text": "20g protein, zero sugar",
                "claim_id": "C1",
            }
        },
        "exposure": exposure_payload(),
        "exposure_dropped": {"persona_id": "p-000042", "stimulus_id": f"st-{VALID_ULID}", "reason": "budget_exhausted"},
        "turn": {
            "persona_id": "p-000042",
            "impression_id": f"im-{VALID_ULID}",
            "reaction_id": f"rc-{VALID_ULID}",
            "prompt_hash": "ab12" * 16,
            "persona_block_hash": "cd34" * 16,
        },
        "reaction": {
            "reaction": {
                "reaction_id": f"rc-{VALID_ULID}",
                "persona_id": "p-000042",
                "impression_id": f"im-{VALID_ULID}",
                "subject_stimulus_id": f"st-{VALID_ULID}",
                "tick": 7,
                "action": "comment",
                "verbatim": "the protein claim lands",
                "belief_change": {"claim_ids": ["C1"], "dimensions": {}, "claim_credence": {"C1": 0.2}},
            }
        },
        "belief_delta": {
            "persona_id": "p-000042",
            "change": {"claim_ids": ["C1"], "dimensions": {}, "claim_credence": {"C1": 0.2}},
            "trigger": "belief_shift",
        },
        "reflection": {"persona_id": "p-000042", "trigger": "tick_cadence"},
        "ssr": {
            "result": {
                "response_text": "I would try it.",
                "pmf": (0.05, 0.1, 0.2, 0.3, 0.35),
                "per_set_pmfs": [(0.05, 0.1, 0.2, 0.3, 0.35)],
                "construct_id": "purchase_intent",
                "category": "beverage_protein",
                "anchor_set_id": "pi-beverage-v1",
                "anchor_version": "1.0.0",
                "embed_model_id": "openai/text-embedding-3-small",
                "tau": 0.42,
            }
        },
        "cost": {
            "role": "tier_a",
            "model_id": "openrouter/camel-ai/persona-8b",
            "input_tokens": 812,
            "output_tokens": 96,
            "cache_hit": False,
            "cost": 0.0004,
        },
        "intervention": {"variant_id": "v1baseline", "intervention_kind": "launch"},
        "lifecycle": {"phase": "started"},
    }
    assert len(cases) == 11
    for kind, fields in cases.items():
        event = TraceEvent.model_validate(event_with_payload(kind, fields))
        assert event.payload.kind == kind


def test_events_carry_no_seed_and_no_contract_version_field():
    assert "seed" not in TraceEvent.model_fields
    assert "world_seed" not in TraceEvent.model_fields
    assert "contract_version" not in TraceEvent.model_fields
    with pytest.raises(ValidationError):
        TraceEvent.model_validate(event_payload(seed=4021))


def test_turn_payload_stores_only_parts_and_a_hash():
    turn = payload_of(
        "turn",
        persona_id="p-000042",
        impression_id=f"im-{VALID_ULID}",
        reaction_id=f"rc-{VALID_ULID}",
        prompt_hash="ab12" * 16,
        persona_block_hash="cd34" * 16,
    )
    parsed = TraceEvent.model_validate(turn).payload
    assert parsed.prompt_hash == "ab12" * 16
    assert "prompt" not in type(parsed).model_fields
    assert "context" not in type(parsed).model_fields
    assert "prompt_text" not in type(parsed).model_fields


def test_event_id_format():
    assert TypeAdapter(EventId).validate_python(EVENT_ID)
    for bad in (VALID_ULID, f"st-{VALID_ULID}", f"ev-{VALID_ULID.upper()}"):
        with pytest.raises(ValidationError):
            TypeAdapter(EventId).validate_python(bad)


def test_events_round_trip_through_json():
    events = [TraceEvent.model_validate(event_payload(event_id=f"ev-{VALID_ULID[:-1]}{c}", seq=n)) for n, c in enumerate("0123456789a")]
    dumped = [event.model_dump(mode="json") for event in events]
    reparsed = [TraceEvent.model_validate(d) for d in dumped]
    assert reparsed == events
    assert [(e.agent_id, e.tick, e.seq) for e in reparsed] == [(e.agent_id, e.tick, e.seq) for e in events]
