import copy
import json
import random

import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    SCHEMA_VERSION,
    ContractMigration,
    CostRecorded,
    EventId,
    PartitionHeader,
    RunConfig,
    RunRegistryEntry,
    SchemaVersionError,
    TraceEvent,
    TracePartition,
    TracePayload,
    TurnRecorded,
    canonical_hash,
    derive_world_id,
    read_partition,
)
from tests.study_builders import (
    event,
    partition_header_payload,
    partition_payload,
    run_config_payload,
    scenario_payload,
    ssr_payload,
    stimulus_id,
    turn_event,
    turn_payload,
    ulid,
    world_id_for,
)


def events_of(data: dict) -> list[dict]:
    return data["events"]


def with_event(index: int, replacement: dict) -> dict:
    data = partition_payload()
    data["events"][index] = replacement
    return data


# --- events -----------------------------------------------------------------------------------


def test_payload_kinds_are_distinct_types_that_dispatch_on_kind_alone():
    adapter = TypeAdapter(TracePayload)
    kinds = {adapter.validate_python(e["payload"]).kind: type(adapter.validate_python(e["payload"])) for e in events_of(partition_payload())}
    assert set(kinds) == {"lifecycle", "stimulus_published", "turn", "cost", "exposure_dropped", "intervention", "reflection"}
    assert len(set(kinds.values())) == len(kinds)


def test_each_kind_is_the_only_record_of_what_it_describes():
    assert not {"exposure", "reaction", "ssr", "belief_delta"} & {TypeAdapter(TracePayload).validate_python(e["payload"]).kind for e in events_of(partition_payload())}
    turn = TracePartition.model_validate(partition_payload()).in_sequence[3].payload
    assert isinstance(turn, TurnRecorded)
    assert turn.turn.impression.exposures and turn.turn.reaction.intent is not None


def test_event_with_a_payload_that_does_not_fit_its_kind_refused():
    bad = event(4, 1, {"kind": "cost", "stimulus_id": stimulus_id(1)}, "p-000001")
    with pytest.raises(ValidationError):
        TraceEvent.model_validate(bad)


def test_events_carry_no_seed_and_no_contract_version_field():
    assert not {"seed", "world_seed", "contract_version", "schema_version", "agent_id"} & set(TraceEvent.model_fields)
    with pytest.raises(ValidationError):
        TraceEvent.model_validate({**events_of(partition_payload())[0], "seed": 4021})


@pytest.mark.parametrize(
    ("index", "persona", "match"),
    [(3, None, "must name it"), (5, None, "must name it"), (1, "p-000001", "belongs to the world"), (8, "p-000001", "belongs to the world")],
    ids=["turn-unattributed", "drop-unattributed", "stimulus-attributed", "intervention-attributed"],
)
def test_events_are_attributed_to_personas_exactly_when_they_describe_one(index, persona, match):
    record = copy.deepcopy(events_of(partition_payload())[index])
    record["persona_id"] = persona
    with pytest.raises(ValidationError, match=match):
        TraceEvent.model_validate(record)


def test_turn_event_must_agree_with_the_impression_it_records():
    record = copy.deepcopy(events_of(partition_payload())[3])
    with pytest.raises(ValidationError, match="shown to"):
        TraceEvent.model_validate({**record, "persona_id": "p-000099"})
    with pytest.raises(ValidationError, match="impression from tick"):
        TraceEvent.model_validate({**record, "tick": 2})


def test_stimulus_event_must_agree_with_the_stimulus_date():
    with pytest.raises(ValidationError, match="dated tick"):
        TraceEvent.model_validate({**events_of(partition_payload())[1], "tick": 5})


def test_turn_records_template_and_hashes_but_never_a_full_prompt():
    fields = set(TurnRecorded.model_fields)
    assert {"template_id", "prompt_hash", "persona_block_hash"} <= fields
    assert not {"prompt", "prompt_text", "context", "messages"} & fields


def test_event_id_format():
    assert TypeAdapter(EventId).validate_python(f"ev-{ulid(1)}")
    for bad in (ulid(1), f"st-{ulid(1)}", f"ev-{ulid(10**9).upper()}"):
        with pytest.raises(ValidationError):
            TypeAdapter(EventId).validate_python(bad)


def test_unvalidated_construction_takes_payload_models_not_mappings():
    record = events_of(partition_payload())[4]
    with pytest.raises(TypeError, match="takes models, not mappings"):
        TraceEvent.model_construct(**record)
    built = TraceEvent.model_construct(**{**record, "payload": CostRecorded.model_validate(record["payload"])})
    assert built.payload.kind == "cost"
    assert TraceEvent.model_validate(built.model_dump(mode="json")) == built


# --- partitions -------------------------------------------------------------------------------


def test_representative_partition_validates_and_round_trips():
    partition = TracePartition.model_validate(partition_payload())
    assert [e.seq for e in partition.in_sequence] == list(range(12))
    assert TracePartition.model_validate_json(partition.model_dump_json()) == partition


def test_world_id_is_derived_by_the_header_never_stated():
    partition = TracePartition.model_validate(partition_payload())
    assert partition.header.world_id == derive_world_id(partition.header.scenario, 4021, partition.header.population.population_hash)
    data = partition_payload()
    data["header"]["world_id"] = "ffffffffffff"
    with pytest.raises(ValidationError, match="computed"):
        TracePartition.model_validate(data)


def test_header_scenario_must_test_the_packed_brief():
    with pytest.raises(ValidationError, match="does not declare"):
        TracePartition.model_validate(partition_payload(scenario=scenario_payload(audience_weights={"gym_regular": 1.0})))


def test_events_from_another_world_refused():
    record = copy.deepcopy(events_of(partition_payload())[11])
    record["world_id"] = "ffffffffffff"
    with pytest.raises(ValidationError, match="other worlds"):
        TracePartition.model_validate(with_event(11, record))


@pytest.mark.parametrize(("seq", "match"), [(12, "without gaps"), (3, "without gaps")], ids=["gap", "repeat"])
def test_sequence_must_be_gapless(seq, match):
    record = copy.deepcopy(events_of(partition_payload())[11])
    record["seq"] = seq
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_event(11, record))


def test_repeated_event_ids_refused():
    record = copy.deepcopy(events_of(partition_payload())[11])
    record["event_id"] = events_of(partition_payload())[0]["event_id"]
    with pytest.raises(ValidationError, match="event ids repeated"):
        TracePartition.model_validate(with_event(11, record))


def test_events_cannot_go_back_in_time_or_past_the_horizon():
    back = copy.deepcopy(events_of(partition_payload())[9])
    back["tick"] = 2
    with pytest.raises(ValidationError, match="back in time"):
        TracePartition.model_validate(with_event(9, back))
    late = copy.deepcopy(events_of(partition_payload())[11])
    late["tick"] = 30
    with pytest.raises(ValidationError, match="beyond the scenario horizon"):
        TracePartition.model_validate(with_event(11, late))


def test_stored_order_does_not_matter_but_sequence_order_is_recovered():
    data = partition_payload()
    random.Random(7).shuffle(data["events"])
    partition = TracePartition.model_validate(data)
    assert [e.seq for e in partition.in_sequence] == list(range(12))


@pytest.mark.parametrize(
    ("index", "replacement", "match"),
    [
        (3, turn_event(3, 1, turn_payload("p-000001", 1, [(7, "interest", 0.8)], {"subject_stimulus_id": stimulus_id(7), "action": "like"}, n=1), "p-000001"), "never published"),
        (5, event(5, 1, {"kind": "exposure_dropped", "stimulus_id": stimulus_id(8), "channel": "social_feed", "reason": "budget_exhausted"}, "p-000002"), "never published"),
        (7, event(7, 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(4), "tick": 2, "author": "p-000002", "kind": "peer_reply", "text": "?", "in_reply_to": stimulus_id(9)}}), "never published"),
        (6, event(6, 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(1), "tick": 2, "author": "p-000001", "kind": "peer_post", "text": "again"}}), "republishes"),
    ],
    ids=["turn-shows-unpublished", "drop-of-unpublished", "reply-to-unpublished", "republished"],
)
def test_stimuli_must_be_published_before_they_are_shown_dropped_or_replied_to(index, replacement, match):
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_event(index, replacement))


@pytest.mark.parametrize(
    ("index", "replacement"),
    [
        (2, event(2, 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(2), "tick": 0, "kind": "claim_post", "text": "x", "claim_id": "C9"}})),
        (9, event(9, 3, {"kind": "reflection", "trigger": "belief_shift", "change": {"claim_credence": {"C9": 0.2}}}, "p-000001")),
        (10, turn_event(10, 3, turn_payload("p-000002", 3, [(3, "wom", 0.6)], {"subject_stimulus_id": stimulus_id(3), "action": "like", "belief_change": {"claim_credence": {"C9": 0.1}}}, n=2), "p-000002")),
    ],
    ids=["stimulus-claim", "reflection-change", "turn-change"],
)
def test_claims_named_anywhere_in_the_trace_must_be_the_briefs(index, replacement):
    with pytest.raises(ValidationError, match="brief does not make"):
        TracePartition.model_validate(with_event(index, replacement))


def test_impressions_are_bounded_by_the_scenarios_exposure_budget():
    four = [(1, "interest", 0.8), (2, "random", 0.1), (3, "wom", 0.2), (4, "forum", 0.3)]
    crowded = turn_event(10, 3, turn_payload("p-000002", 3, four, {"subject_stimulus_id": stimulus_id(1), "action": "like"}, n=2), "p-000002")
    with pytest.raises(ValidationError, match="budget of 3"):
        TracePartition.model_validate(with_event(10, crowded))
    wide_scenario = scenario_payload(exposure_budget=5)
    data = partition_payload(scenario=wide_scenario)
    world = world_id_for(wide_scenario)
    data["events"][10] = crowded
    for record in data["events"]:
        record["world_id"] = world
    assert TracePartition.model_validate(data).header.scenario.exposure_budget == 5


def test_only_scheduled_interventions_are_applied():
    promo = event(8, 3, {"kind": "intervention", "intervention_kind": "promotion"})
    with pytest.raises(ValidationError, match="does not schedule"):
        TracePartition.model_validate(with_event(8, promo))


def test_impressions_and_reactions_are_recorded_once():
    data = partition_payload()
    repeat = copy.deepcopy(data["events"][3])
    repeat["payload"]["turn"]["impression"]["tick"] = 3
    repeat.update(seq=10, tick=3, event_id=data["events"][10]["event_id"])
    data["events"][10] = repeat
    with pytest.raises(ValidationError, match="repeats impression"):
        TracePartition.model_validate(data)


def test_turn_inside_a_partition_still_refuses_a_subject_not_shown():
    wrong = turn_event(10, 3, turn_payload("p-000002", 3, [(3, "wom", 0.6)], {"subject_stimulus_id": stimulus_id(1), "action": "like"}, n=2), "p-000002")
    with pytest.raises(ValidationError, match="did not show"):
        TracePartition.model_validate(with_event(10, wrong))


def test_events_at_realistic_volume_round_trip_fully_validated_in_any_stored_order():
    turns = 20_000
    header = partition_header_payload(persona_ids=[f"p-{i:06d}" for i in range(2000)])
    world = PartitionHeader.model_validate(header).world_id
    constructed = [TraceEvent.model_validate(event(0, 0, {"kind": "lifecycle", "phase": "started"}, world=world))]
    for s in range(1, 51):
        constructed.append(TraceEvent.model_validate(event(len(constructed), 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(s), "tick": 0, "kind": "concept", "text": f"copy {s}"}}, world=world)))
    template = TurnRecorded.model_validate(turn_event(0, 1, turn_payload("p-000000", 1, [(1, "interest", 0.7)], {"subject_stimulus_id": stimulus_id(1), "action": "like"}), "p-000000")["payload"])
    for t in range(turns):
        tick, persona = 1 + (t * 29) // turns, f"p-{t % 2000:06d}"
        impression = template.turn.impression.model_construct(
            impression_id=f"im-{ulid(10_000 + t)}", persona_id=persona, channel=template.turn.impression.channel, tick=tick,
            exposures=template.turn.impression.exposures,
        )
        reaction = template.turn.reaction.model_construct(**{**dict(template.turn.reaction), "reaction_id": f"rc-{ulid(10_000 + t)}"})
        payload = template.model_construct(**{**dict(template), "turn": template.turn.model_construct(impression=impression, reaction=reaction)})
        constructed.append(TraceEvent.model_construct(event_id=f"ev-{ulid(10_000 + t)}", world_id=world, tick=tick, seq=len(constructed), persona_id=persona, payload=payload))

    stored = sorted((json.loads(json.dumps(e.model_dump(mode="json"))) for e in constructed), key=lambda e: (e["persona_id"] or "", e["tick"], e["seq"]))
    partition = TracePartition.model_validate({"header": header, "events": stored})
    assert len(partition.events) == len(constructed)
    assert list(partition.in_sequence) == constructed


# --- read path --------------------------------------------------------------------------------


def dumped_partition(version: str = SCHEMA_VERSION) -> dict:
    data = json.loads(TracePartition.model_validate(partition_payload()).model_dump_json())
    data["header"]["contract_version"] = version
    return data


def test_current_contract_partition_loads_unchanged():
    assert read_partition(dumped_partition()) == TracePartition.model_validate(partition_payload())


@pytest.mark.parametrize("version", ["1.0.1", "2.0.0"])
def test_partition_from_a_newer_contract_is_refused_not_guessed_at(version):
    with pytest.raises(SchemaVersionError, match="newer than this engine"):
        read_partition(dumped_partition(version))


@pytest.mark.parametrize("version", ["banana", "1.0", None])
def test_partition_without_a_valid_contract_version_refused(version):
    data = dumped_partition()
    data["header"]["contract_version"] = version
    with pytest.raises(SchemaVersionError, match="not a contract version"):
        read_partition(data)


def legacy_partition() -> dict:
    """A partition in an imagined 0.9.0 shape: each event carried its seed and called the persona an agent."""
    data = dumped_partition("0.9.0")
    for record in data["events"]:
        record["seed"] = 4021
        record["agent_id"] = record.pop("persona_id")
    return data


def to_1_0_0(raw: dict) -> dict:
    for record in raw["events"]:
        record.pop("seed", None)
        record["persona_id"] = record.pop("agent_id", None)
    return raw


def test_earlier_contract_partition_loads_through_its_registered_migration():
    legacy = legacy_partition()
    with pytest.raises(ValidationError):
        TracePartition.model_validate(legacy)
    loaded = read_partition(legacy, migrations=[ContractMigration("1.0.0", to_1_0_0)])
    assert loaded.header.contract_version == "0.9.0"
    assert [e.persona_id for e in loaded.in_sequence] == [e.persona_id for e in TracePartition.model_validate(partition_payload()).in_sequence]


def test_migrations_apply_in_order_and_only_past_the_written_contract():
    applied = []

    def step(name):
        def migrate(raw):
            applied.append(name)
            return to_1_0_0(raw) if name == "1.0.0" else raw
        return migrate

    migrations = [ContractMigration("1.0.0", step("1.0.0")), ContractMigration("0.9.0", step("0.9.0")), ContractMigration("0.5.0", step("0.5.0"))]
    read_partition(legacy_partition(), migrations=migrations)
    assert applied == ["1.0.0"]
    applied.clear()
    data = legacy_partition()
    data["header"]["contract_version"] = "0.4.0"
    read_partition(data, migrations=migrations)
    assert applied == ["0.5.0", "0.9.0", "1.0.0"]


def test_read_path_never_mutates_its_input_and_never_writes_a_legacy_shape():
    legacy = legacy_partition()
    before = copy.deepcopy(legacy)
    loaded = read_partition(legacy, migrations=[ContractMigration("1.0.0", to_1_0_0)])
    assert legacy == before
    rewritten = json.loads(loaded.model_dump_json())
    assert all("seed" not in e and "agent_id" not in e for e in rewritten["events"])


# --- registry ---------------------------------------------------------------------------------


def registry_payload(**overrides):
    payload = {"config": run_config_payload(), "contract_version": SCHEMA_VERSION, "status": "running"}
    payload.update(overrides)
    return payload


def test_registry_entry_derives_config_hash_and_world_ids_from_its_configuration():
    entry = RunRegistryEntry.model_validate(registry_payload())
    config = RunConfig.model_validate(run_config_payload())
    assert entry.config_hash == canonical_hash(config)
    assert set(entry.world_ids) == {derive_world_id(s, seed, config.population_hash) for s in config.scenarios for seed in config.seeds}
    assert RunRegistryEntry.model_validate_json(entry.model_dump_json()) == entry


def test_registry_entry_pins_everything_replay_needs():
    entry = RunRegistryEntry.model_validate(registry_payload())
    config = entry.config
    assert config.pins and config.seeds and config.template_hashes and config.brief_hash and config.ontology_hash and config.population_hash
    assert "anchor_set_hashes" in RunConfig.model_fields and "graph_hash" in RunConfig.model_fields


@pytest.mark.parametrize("field", ["config_hash", "world_ids"])
def test_registry_entry_refuses_a_stated_value_contradicting_its_configuration(field):
    stated = {"config_hash": "00" * 32, "world_ids": ["ffffffffffff"]}[field]
    with pytest.raises(ValidationError, match="computed"):
        RunRegistryEntry.model_validate({**registry_payload(), field: stated})


def test_registry_entry_keeps_the_hash_it_was_registered_under():
    old = RunRegistryEntry.model_validate(registry_payload(contract_version="0.9.0"))
    assert old.config_hash == canonical_hash(old.config, schema_version="0.9.0")
    assert old.config_hash != RunRegistryEntry.model_validate(registry_payload()).config_hash
    assert RunRegistryEntry.model_validate(json.loads(old.model_dump_json())) == old


def test_registry_entry_cannot_repeat_seeds_or_worlds():
    with pytest.raises(ValidationError, match="seeds repeated"):
        RunRegistryEntry.model_validate(registry_payload(config=run_config_payload(seeds=[4021, 4021])))


# --- the run and population a partition belongs to --------------------------------------------


@pytest.mark.parametrize(
    ("config_override", "match"),
    [
        ({"brief_hash": "00" * 32}, "different brief"),
        ({"ontology_hash": "00" * 32}, "different ontology"),
        ({"population_hash": "00" * 32}, "different population"),
        ({"graph_hash": None}, "different social graph"),
        ({"seeds": [1, 2]}, "not one of the run's seeds"),
    ],
    ids=["brief", "ontology", "population", "graph", "seed"],
)
def test_header_verifies_every_pin_against_the_object_it_pins(config_override, match):
    header = partition_header_payload()
    header["config"].update(config_override)
    with pytest.raises(ValidationError, match=match):
        PartitionHeader.model_validate(header)


def test_header_scenario_must_be_one_the_run_configures():
    header = partition_header_payload()
    header["config"]["scenarios"] = [scenario_payload(horizon_ticks=60)]
    with pytest.raises(ValidationError, match="not one the run configures"):
        PartitionHeader.model_validate(header)


def with_payload_change(index: int, change) -> dict:
    data = partition_payload()
    change(data["events"][index])
    return data


@pytest.mark.parametrize(
    ("index", "change", "match"),
    [
        (10, lambda e: e.update(persona_id="p-999999") or e["payload"]["turn"]["impression"].update(persona_id="p-999999"), "not in this population"),
        (6, lambda e: e["payload"]["stimulus"].update(author="p-999999"), "not in this population"),
        (3, lambda e: e["payload"].update(template_id="unpinned_template"), "does not pin"),
        (3, lambda e: e["payload"]["turn"]["reaction"]["intent"].update(embed_model_id="voyage/voyage-3-large"), "pins openai/text-embedding-3-small for every embedding"),
        (3, lambda e: e["payload"]["turn"]["reaction"]["intent"].update(anchor_set_id="pi-snacks-v9"), "does not pin"),
        (3, lambda e: e["payload"]["turn"]["reaction"]["intent"].update(category="snack_bar"), "anchors for a 'beverage_protein' brief"),
        (4, lambda e: e["payload"].update(model_id="openai/gpt-4o-2024-08-06"), "but the run pins"),
    ],
    ids=["turn-by-stranger", "stimulus-by-stranger", "unpinned-template", "other-embedding-model", "unpinned-anchor-set", "foreign-category", "unpinned-cost-model"],
)
def test_events_must_honour_the_run_and_its_population(index, change, match):
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_payload_change(index, change))


def test_turns_recall_only_earlier_turns_or_reflections_of_the_same_persona():
    data = partition_payload()
    own_turn, own_reflection = data["events"][3]["event_id"], data["events"][9]["event_id"]
    data["events"][10]["payload"]["memory_ids"] = [data["events"][3]["event_id"]]
    with pytest.raises(ValidationError, match="not an earlier turn or reflection of p-000002"):
        TracePartition.model_validate(data)
    data = partition_payload()
    data["events"][3]["payload"]["memory_ids"] = [data["events"][9]["event_id"]]
    with pytest.raises(ValidationError, match="not an earlier turn or reflection"):
        TracePartition.model_validate(data)
    data = partition_payload()
    data["events"][10]["payload"]["turn"]["impression"]["persona_id"] = "p-000001"
    data["events"][10]["persona_id"] = "p-000001"
    data["events"][10]["payload"]["memory_ids"] = [own_turn, own_reflection]
    assert TracePartition.model_validate(data).in_sequence[10].payload.memory_ids == (own_turn, own_reflection)


@pytest.mark.parametrize(
    ("phases", "match"),
    [
        ({0: "completed"}, "moves the world from nothing to completed"),
        ({11: "started"}, "moves the world from started to started"),
        ({8: "paused"}, "recorded while the world is paused"),
    ],
    ids=["completed-first", "started-twice", "events-while-paused"],
)
def test_lifecycle_moves_through_valid_phases_and_nothing_happens_while_stopped(phases, match):
    data = partition_payload()
    for index, phase in phases.items():
        data["events"][index] = event(index, data["events"][index]["tick"], {"kind": "lifecycle", "phase": phase})
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(data)


def test_partition_must_open_with_the_world_starting():
    data = partition_payload()
    data["events"] = [e for e in data["events"] if e["seq"] != 0]
    for record in data["events"]:
        record["seq"] -= 1
    with pytest.raises(ValidationError, match="precedes the world starting"):
        TracePartition.model_validate(data)


def test_paused_world_may_resume_and_events_after_completion_are_refused():
    data = partition_payload()
    data["events"][8] = event(8, 3, {"kind": "lifecycle", "phase": "paused"})
    data["events"][9] = event(9, 3, {"kind": "lifecycle", "phase": "started"})
    data["events"][10] = event(10, 3, {"kind": "intervention", "intervention_kind": "launch"})
    assert TracePartition.model_validate(data).in_sequence[9].payload.phase.value == "started"
    data = partition_payload()
    data["events"][11], data["events"][10] = event(10, 4, {"kind": "lifecycle", "phase": "completed"}), event(11, 4, {"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b", "input_tokens": 1, "output_tokens": 1, "cache_hit": True, "cost": 0.0})
    with pytest.raises(ValidationError, match="while the world is completed"):
        TracePartition.model_validate(data)
