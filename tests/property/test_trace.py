import json

import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    EventId,
    PartitionHeader,
    RunRegistryEntry,
    SCHEMA_VERSION,
    TraceEvent,
    TracePayload,
    read_events_lenient,
)

VALID_ULID = "01j7x9k2m3n4p5q6r7s8t9v0wx"
EVENT_ID = f"ev-{VALID_ULID}"


def exposure_payload():
    return {
        "kind": "exposure",
        "persona_id": "p-000042",
        "exposure": {
            "stimulus_id": f"st-{VALID_ULID}",
            "reason": "interest",
            "attention": 0.8,
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
                "subject_stimulus_id": f"st-{VALID_ULID}",
                "action": "comment",
                "verbatim": "the protein claim lands",
                "belief_change": {"dimensions": {}, "claim_credence": {"C1": 0.2}},
            }
        },
        "belief_delta": {
            "persona_id": "p-000042",
            "change": {"dimensions": {}, "claim_credence": {"C1": 0.2}},
            "trigger": "belief_shift",
        },
        "reflection": {"persona_id": "p-000042", "trigger": "tick_cadence"},
        "ssr": {
            "result": {
                "response_text": "I would try it.",
                "per_set_pmfs": [(0.05, 0.1, 0.2, 0.3, 0.35), (0.05, 0.1, 0.2, 0.3, 0.35),
                                 (0.05, 0.1, 0.2, 0.3, 0.35), (0.05, 0.1, 0.2, 0.3, 0.35),
                                 (0.05, 0.1, 0.2, 0.3, 0.35), (0.05, 0.1, 0.2, 0.3, 0.35)],
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


# --- partitions, registry, lenient read path ---------------------------------------------------


def test_contract_version_recorded_once_per_partition_and_in_the_registry():
    header = PartitionHeader(contract_version=SCHEMA_VERSION, world_id="a1b2c3d4e5f6")
    entry = RunRegistryEntry.model_validate(registry_payload())
    assert header.contract_version == SCHEMA_VERSION
    assert entry.contract_version == SCHEMA_VERSION
    assert "contract_version" not in TraceEvent.model_fields


def registry_payload(**overrides):
    payload = {
        "run_id": "run-01j7x9k2m3n4p5q6r7s8t9v0wx",
        "contract_version": SCHEMA_VERSION,
        "config_hash": "aa11" * 16,
        "brief_hash": "bb22" * 16,
        "ontology_hash": "cc33" * 16,
        "population_hash": "dd44" * 16,
        "seeds": [4021, 917731],
        "pins": {
            "tier_a": "openrouter/camel-ai/persona-8b",
            "tier_b": "anthropic/claude-sonnet-4-5-20250929",
            "embed": "openai/text-embedding-3-small",
        },
        "world_ids": ["a1b2c3d4e5f6", "b2c3d4e5f6a1"],
        "status": "running",
    }
    payload.update(overrides)
    return payload


def test_registry_entry_pins_every_hash_and_model_identifier():
    entry = RunRegistryEntry.model_validate(registry_payload())
    assert entry.brief_hash and entry.ontology_hash and entry.population_hash and entry.config_hash
    assert entry.pins.embed == "openai/text-embedding-3-small"
    assert {world_id for world_id in entry.world_ids} == {"a1b2c3d4e5f6", "b2c3d4e5f6a1"}


def test_earlier_contract_partition_loads_under_a_later_one():
    legacy = event_payload(seed=4021)
    with pytest.raises(ValidationError):
        TraceEvent.model_validate(legacy)
    loaded = read_events_lenient([legacy], "0.9.0")
    assert loaded[0].event_id == EVENT_ID


def test_lenient_path_is_never_used_to_write():
    legacy = event_payload(seed=4021)
    loaded = read_events_lenient([legacy], "0.9.0")[0]
    with pytest.raises(ValidationError, match="seed"):
        TraceEvent.model_validate(loaded.model_dump(mode="json") | {"seed": 4021})


def test_current_contract_partition_loads_unchanged():
    current = event_payload()
    assert list(read_events_lenient([current], SCHEMA_VERSION)) == [TraceEvent.model_validate(current)]


def test_events_at_realistic_volume_round_trip_with_ordering_preserved():
    from simcore.schemas import Exposure, ExposureRecorded

    volume = 100_000
    payload = ExposureRecorded.model_construct(
        kind="exposure",
        persona_id="p-000042",
        exposure=Exposure.model_construct(
            stimulus_id=f"st-{VALID_ULID}", reason="interest", attention=0.8
        ),
    )
    constructed = [
        TraceEvent.model_construct(
            event_id=f"ev-{seq:026d}",
            world_id="a1b2c3d4e5f6",
            tick=(seq // 2000) % 30,
            agent_id=f"p-{seq % 2000:06d}",
            seq=seq,
            payload=payload,
        )
        for seq in range(volume)
    ]
    assert len(constructed) == volume

    reparsed_dicts = json.loads(json.dumps([event.model_dump(mode="json") for event in constructed]))
    assert [(d["agent_id"], d["tick"], d["seq"]) for d in reparsed_dicts] == [
        (event.agent_id, event.tick, event.seq) for event in constructed
    ]

    sample = reparsed_dicts[::1000]
    assert [TraceEvent.model_validate(item) for item in sample] == constructed[::1000]
