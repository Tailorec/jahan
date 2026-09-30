import copy
import json
import random

import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    InferenceRole,
    ModelPins,
    Degraded,
    TickClosed,
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
    GuardrailViolation,
    TurnRecorded,
    WorldRecord,
    canonical_hash,
    derive_world_id,
    read_partition,
)
from tests.study_builders import (
    PARTITION_ROLES,
    R,
    event,
    partition_header_payload,
    partition_run_config,
    partition_payload,
    persona_payload,
    resequence,
    population_payload,
    run_config_payload,
    scenario_payload,
    ssr_payload,
    stimulus_id,
    turn_event,
    turn_payload,
    ulid,
    violation_event,
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
    assert set(kinds) == {"lifecycle", "stimulus_published", "turn", "cost", "exposure_dropped", "intervention", "reflection",
                          "tick_closed", "degraded", "guardrail_violation", "memory", "belief_snapshot", "probe"}
    assert len(set(kinds.values())) == len(kinds)


def test_each_kind_is_the_only_record_of_what_it_describes():
    assert not {"exposure", "reaction", "ssr", "belief_delta"} & {TypeAdapter(TracePayload).validate_python(e["payload"]).kind for e in events_of(partition_payload())}
    turn = TracePartition.model_validate(partition_payload()).in_sequence[R["first_turn"]].payload
    assert isinstance(turn, TurnRecorded)
    assert turn.turn.impression.exposures and turn.turn.reaction.intent is not None


def test_event_with_a_payload_that_does_not_fit_its_kind_refused():
    bad = event(R["first_turn_cost"], 1, {"kind": "cost", "stimulus_id": stimulus_id(1)}, "p-000001")
    with pytest.raises(ValidationError):
        TraceEvent.model_validate(bad)


def test_events_carry_no_seed_and_no_contract_version_field():
    assert not {"seed", "world_seed", "contract_version", "schema_version", "agent_id"} & set(TraceEvent.model_fields)
    with pytest.raises(ValidationError):
        TraceEvent.model_validate({**events_of(partition_payload())[R["started"]], "seed": 4021})


@pytest.mark.parametrize(
    ("index", "persona", "match"),
    [(R["first_turn"], None, "must name it"), (R["drop"], None, "must name it"), (R["concept"], "p-000001", "belongs to the world"), (R["launch"], "p-000001", "belongs to the world")],
    ids=["turn-unattributed", "drop-unattributed", "stimulus-attributed", "intervention-attributed"],
)
def test_events_are_attributed_to_personas_exactly_when_they_describe_one(index, persona, match):
    record = copy.deepcopy(events_of(partition_payload())[index])
    record["persona_id"] = persona
    with pytest.raises(ValidationError, match=match):
        TraceEvent.model_validate(record)


def test_turn_event_must_agree_with_the_impression_it_records():
    record = copy.deepcopy(events_of(partition_payload())[R["first_turn"]])
    with pytest.raises(ValidationError, match="shown to"):
        TraceEvent.model_validate({**record, "persona_id": "p-000099"})
    with pytest.raises(ValidationError, match="impression from tick"):
        TraceEvent.model_validate({**record, "tick": 2})


def test_stimulus_event_must_agree_with_the_stimulus_date():
    with pytest.raises(ValidationError, match="dated tick"):
        TraceEvent.model_validate({**events_of(partition_payload())[R["concept"]], "tick": 5})


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
    record = events_of(partition_payload())[R["first_turn_cost"]]
    with pytest.raises(TypeError, match="takes models, not mappings"):
        TraceEvent.model_construct(**record)
    built = TraceEvent.model_construct(**{**record, "payload": CostRecorded.model_validate(record["payload"])})
    assert built.payload.kind == "cost"
    assert TraceEvent.model_validate(built.model_dump(mode="json")) == built


# --- partitions -------------------------------------------------------------------------------


def test_representative_partition_validates_and_round_trips():
    partition = TracePartition.model_validate(partition_payload())
    assert [e.seq for e in partition.in_sequence] == list(range(len(PARTITION_ROLES)))
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
    record = copy.deepcopy(events_of(partition_payload())[R["completed"]])
    record["world_id"] = "ffffffffffff"
    with pytest.raises(ValidationError, match="other worlds"):
        TracePartition.model_validate(with_event(R["completed"], record))


@pytest.mark.parametrize(("seq", "match"), [(len(PARTITION_ROLES), "without gaps"), (3, "without gaps")], ids=["gap", "repeat"])
def test_sequence_must_be_gapless(seq, match):
    record = copy.deepcopy(events_of(partition_payload())[R["completed"]])
    record["seq"] = seq
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_event(R["completed"], record))


def test_repeated_event_ids_refused():
    record = copy.deepcopy(events_of(partition_payload())[R["completed"]])
    record["event_id"] = events_of(partition_payload())[R["started"]]["event_id"]
    with pytest.raises(ValidationError, match="event ids repeated"):
        TracePartition.model_validate(with_event(R["completed"], record))


def test_events_cannot_go_back_in_time_or_past_the_horizon():
    back = copy.deepcopy(events_of(partition_payload())[R["reflection"]])
    back["tick"] = 2
    with pytest.raises(ValidationError, match="back in time"):
        TracePartition.model_validate(with_event(R["reflection"], back))
    late = copy.deepcopy(events_of(partition_payload())[R["completed"]])
    late["tick"] = 30
    with pytest.raises(ValidationError, match="beyond the scenario horizon"):
        TracePartition.model_validate(with_event(R["completed"], late))


def test_stored_order_does_not_matter_but_sequence_order_is_recovered():
    data = partition_payload()
    random.Random(7).shuffle(data["events"])
    partition = TracePartition.model_validate(data)
    assert [e.seq for e in partition.in_sequence] == list(range(len(PARTITION_ROLES)))


@pytest.mark.parametrize(
    ("index", "replacement", "match"),
    [
        (R["first_turn"], turn_event(R["first_turn"], 1, turn_payload("p-000001", 1, [(7, "interest", 0.8)], {"subject_stimulus_id": stimulus_id(7), "action": "like"}, n=1), "p-000001"), "never published"),
        (R["drop"], event(R["drop"], 1, {"kind": "exposure_dropped", "stimulus_id": stimulus_id(8), "channel": "social_feed", "reason": "budget_exhausted"}, "p-000002"), "never published"),
        (R["peer_reply"], event(R["peer_reply"], 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(4), "tick": 2, "author": "p-000002", "kind": "peer_reply", "text": "?", "in_reply_to": stimulus_id(9)}}), "never published"),
        (R["peer_post"], event(R["peer_post"], 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(1), "tick": 2, "author": "p-000001", "kind": "peer_post", "text": "again"}}), "republishes"),
    ],
    ids=["turn-shows-unpublished", "drop-of-unpublished", "reply-to-unpublished", "republished"],
)
def test_stimuli_must_be_published_before_they_are_shown_dropped_or_replied_to(index, replacement, match):
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_event(index, replacement))


@pytest.mark.parametrize(
    ("index", "replacement"),
    [
        (R["claim_post"], event(R["claim_post"], 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(2), "tick": 0, "kind": "claim_post", "text": "x", "claim_id": "C9"}})),
        (R["reflection"], event(R["reflection"], 3, {"kind": "reflection", "trigger": "belief_shift", "change": {"claim_credence": {"C9": 0.2}}}, "p-000001")),
        (R["second_turn"], turn_event(R["second_turn"], 3, turn_payload("p-000002", 3, [(3, "wom", 0.6)], {"subject_stimulus_id": stimulus_id(3), "action": "like", "belief_change": {"claim_credence": {"C9": 0.1}}}, n=2), "p-000002")),
    ],
    ids=["stimulus-claim", "reflection-change", "turn-change"],
)
def test_claims_named_anywhere_in_the_trace_must_be_the_briefs(index, replacement):
    with pytest.raises(ValidationError, match="brief does not make"):
        TracePartition.model_validate(with_event(index, replacement))


def test_impressions_are_bounded_by_the_scenarios_exposure_budget():
    four = [(1, "interest", 0.8), (2, "random", 0.1), (3, "wom", 0.2), (4, "forum", 0.3)]
    views = {3: {"replies": 1, "tie_strength": 0.8, "shared_community": True}, 4: {"ancestry": [stimulus_id(3)]}}
    crowded = turn_event(R["second_turn"], 3, turn_payload("p-000002", 3, four, {"subject_stimulus_id": stimulus_id(3), "action": "like"}, contexts=views, n=2), "p-000002")
    with pytest.raises(ValidationError, match="budget of 3"):
        TracePartition.model_validate(with_event(R["second_turn"], crowded))
    wide_scenario = scenario_payload(exposure_budget=5)
    data = partition_payload(scenario=wide_scenario)
    world = world_id_for(wide_scenario)
    data["events"][R["second_turn"]] = crowded
    for record in data["events"]:
        record["world_id"] = world
    assert TracePartition.model_validate(data).header.scenario.exposure_budget == 5


def test_only_scheduled_interventions_are_applied():
    promo = event(R["launch"], 3, {"kind": "intervention", "intervention_kind": "promotion"})
    with pytest.raises(ValidationError, match="does not schedule"):
        TracePartition.model_validate(with_event(R["launch"], promo))


def test_impressions_and_reactions_are_recorded_once():
    data = partition_payload()
    repeat = copy.deepcopy(data["events"][R["first_turn"]])
    repeat["payload"]["turn"]["impression"]["tick"] = 3
    repeat.update(seq=R["second_turn"], tick=3, event_id=data["events"][R["second_turn"]]["event_id"])
    data["events"][R["second_turn"]] = repeat
    with pytest.raises(ValidationError, match="repeats impression"):
        TracePartition.model_validate(data)


def test_turn_inside_a_partition_still_refuses_a_subject_not_shown():
    wrong = turn_event(R["second_turn"], 3, turn_payload("p-000002", 3, [(3, "wom", 0.6)], {"subject_stimulus_id": stimulus_id(1), "action": "like"}, n=2), "p-000002")
    with pytest.raises(ValidationError, match="did not show"):
        TracePartition.model_validate(with_event(R["second_turn"], wrong))


def test_events_at_realistic_volume_round_trip_fully_validated_in_any_stored_order():
    turns = 20_000
    header = partition_header_payload(persona_ids=[f"p-{i:06d}" for i in range(2000)])
    world = PartitionHeader.model_validate(header).world_id
    constructed = [TraceEvent.model_validate(event(0, 0, {"kind": "lifecycle", "phase": "started"}, world=world))]
    for s in range(1, 51):
        constructed.append(TraceEvent.model_validate(event(len(constructed), 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(s), "tick": 0, "kind": "concept", "text": f"copy {s}"}}, world=world)))
    template = TurnRecorded.model_validate(turn_event(0, 1, turn_payload("p-000000", 1, [(1, "interest", 0.7)], {"subject_stimulus_id": stimulus_id(1), "action": "ignore"}), "p-000000")["payload"])
    for t in range(turns):
        tick, persona = 1 + (t * 29) // turns, f"p-{t % 2000:06d}"
        impression = template.turn.impression.model_construct(
            impression_id=f"im-{ulid(10_000 + t)}", persona_id=persona, channel=template.turn.impression.channel, tick=tick,
            exposures=template.turn.impression.exposures,
        )
        reaction = template.turn.reaction.model_construct(**{**dict(template.turn.reaction), "reaction_id": f"rc-{ulid(10_000 + t)}"})
        view = template.turn.view.model_construct(impression_id=impression.impression_id, contexts=template.turn.view.contexts)
        turn = template.turn.model_construct(impression=impression, view=view, reaction=reaction)
        payload = template.model_construct(**{**dict(template), "turn": turn})
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
    payload = {"config": run_config_payload(), "contract_version": SCHEMA_VERSION, "status": "running",
               "engine_version": "0a35555"}
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


def test_header_refuses_a_run_that_does_not_pin_an_anchor_set_its_ontology_names():
    config = partition_run_config(anchor_set_hashes={"pi-snacks-v9": "ef" * 32})
    with pytest.raises(ValidationError, match=r"does not pin anchor sets this partition's ontology names: \['purchase-intent-v1'\]"):
        PartitionHeader.model_validate({**partition_header_payload(), "config": config})


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
        (R["second_turn"], lambda e: e.update(persona_id="p-999999") or e["payload"]["turn"]["impression"].update(persona_id="p-999999"), "not in this population"),
        (R["peer_post"], lambda e: e["payload"]["stimulus"].update(author="p-999999"), "not in this population"),
        (R["first_turn"], lambda e: e["payload"].update(template_id="unpinned_template"), "does not pin"),
        (R["first_turn"], lambda e: e["payload"]["turn"]["reaction"]["intent"].update(embed_model_id="voyage/voyage-3-large"), "pins openai/text-embedding-3-small for every embedding"),
        (R["first_turn"], lambda e: e["payload"]["turn"]["reaction"]["intent"].update(anchor_set_id="pi-snacks-v9"), "does not pin"),
        (R["first_turn"], lambda e: e["payload"]["turn"]["reaction"]["intent"].update(category="snack_bar"), "anchors for a 'beverage_protein' brief"),
        (R["first_turn"], lambda e: e["payload"]["turn"]["reaction"]["intent"].update(construct_id="brand_trust"), "which the ontology names no anchor set for"),
        (R["first_turn_cost"], lambda e: e["payload"].update(model_id="openai/gpt-4o-2024-08-06"), "but the run pins"),
    ],
    ids=["turn-by-stranger", "stimulus-by-stranger", "unpinned-template", "other-embedding-model", "unpinned-anchor-set", "foreign-category", "unnamed-construct", "unpinned-cost-model"],
)
def test_events_must_honour_the_run_and_its_population(index, change, match):
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(with_payload_change(index, change))


def test_an_elicitation_is_scored_against_the_anchor_set_its_ontology_names():
    data = partition_payload()
    # The run pins both anchor sets, so only the ontology decides which one purchase intent is scored against.
    data["header"]["config"] = partition_run_config(anchor_set_hashes={"purchase-intent-v1": "ef" * 32, "pi-snacks-v9": "ab" * 32})
    data["events"][R["first_turn"]]["payload"]["turn"]["reaction"]["intent"]["anchor_set_id"] = "pi-snacks-v9"
    with pytest.raises(ValidationError, match="but the ontology names 'purchase-intent-v1' for 'purchase_intent'"):
        TracePartition.model_validate(data)


def test_turns_recall_only_earlier_memories_of_the_same_persona():
    data = partition_payload()
    own_turn = data["events"][R["first_turn_memory"]]["payload"]["memory"]["memory_id"]
    own_reflection = data["events"][R["reflection_memory"]]["payload"]["memory"]["memory_id"]
    # p-000002 recalling p-000001's memory
    data["events"][R["second_turn"]]["payload"]["memory_ids"] = [own_turn]
    with pytest.raises(ValidationError, match="not an earlier memory of p-000002"):
        TracePartition.model_validate(data)
    # p-000001 recalling its own memory before it was written
    data = partition_payload()
    data["events"][R["first_turn"]]["payload"]["memory_ids"] = [own_reflection]
    with pytest.raises(ValidationError, match="not an earlier memory"):
        TracePartition.model_validate(data)
    # a memory written twice is not two memories
    data = partition_payload()
    data["events"][R["reflection_memory"]]["payload"]["memory"]["memory_id"] = own_turn
    with pytest.raises(ValidationError, match="a second time; a memory is written once"):
        TracePartition.model_validate(data)
    data = partition_payload()
    data["events"][R["second_turn"]]["payload"]["turn"]["impression"]["persona_id"] = "p-000001"
    data["events"][R["second_turn"]]["persona_id"] = "p-000001"
    data["events"][R["second_turn"]]["payload"]["memory_ids"] = [own_turn, own_reflection]
    contexts = data["events"][R["second_turn"]]["payload"]["turn"]["view"]["contexts"]
    # p-000001 authored st3, so its own turn records no relationship to it — and nobody told it
    # about its own post either.
    contexts[stimulus_id(3)].update(tie_strength=None, shared_community=None, via_persona_id=None)
    contexts[stimulus_id(4)].update(tie_strength=0.8, shared_community=True)
    assert TracePartition.model_validate(data).in_sequence[R["second_turn"]].payload.memory_ids == (own_turn, own_reflection)


@pytest.mark.parametrize(
    ("phases", "match"),
    [
        ({R["started"]: "completed"}, "moves the world from nothing to completed"),
        ({R["completed"]: "started"}, "moves the world from started to started"),
        ({R["launch"]: "paused"}, "which only follows a pause rung"),
    ],
    ids=["completed-first", "started-twice", "paused-without-the-pause-rung"],
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
    data["events"][R["warned"]] = event(R["warned"], 3, PAUSE_RUNG)
    data["events"][R["launch"]] = event(R["launch"], 3, {"kind": "lifecycle", "phase": "paused"})
    data["events"][R["reflection"]] = event(R["reflection"], 3, {"kind": "lifecycle", "phase": "started"})
    data["events"][R["second_turn"]] = event(R["second_turn"], 3, {"kind": "intervention", "intervention_kind": "launch"})
    data["events"][R["third_turn"]] = event(R["third_turn"], 4, COST_AT_TICK)
    data["events"][R["violation"]] = event(R["violation"], 4, COST_AT_TICK)
    assert TracePartition.model_validate(data).in_sequence[R["reflection"]].payload.phase.value == "started"
    data = partition_payload()
    data["events"].append(event(len(data["events"]), 5, COST_AT_TICK))
    with pytest.raises(ValidationError, match="while the world is completed"):
        TracePartition.model_validate(data)


PAUSE_RUNG = {"kind": "degraded", "rung": "pause", "activation_rate": 0.40, "tier_b_frozen": True}
COST_AT_TICK = {"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b", "cost_source": "cache", "route": "cache", "input_tokens": 1, "output_tokens": 1, "cost": 0.0}


# --- views ------------------------------------------------------------------------------------


def contexts_of(data: dict, role: str) -> dict:
    payload = data["events"][R[role]]["payload"]
    return payload.get("turn", payload)["view"]["contexts"]


def with_turn_before_completion(data: dict, tick: int, turn: dict, persona: str) -> dict:
    completed = data["events"].pop(R["completed"])
    data["events"].append(turn_event(R["completed"], tick, turn, persona))
    completed.update(seq=R["completed"] + 1, tick=tick, event_id=f"ev-{ulid(5000)}")
    data["events"].append(completed)
    return data


def test_representative_views_count_engagement_from_the_partitions_own_earlier_turns():
    partition = TracePartition.model_validate(partition_payload())
    second = partition.in_sequence[R["second_turn"]].payload.turn.view.contexts[stimulus_id(3)]
    third = partition.in_sequence[R["third_turn"]].payload.turn.view.contexts
    assert (second.likes, second.replies) == (0, 1)
    assert (third[stimulus_id(3)].likes, third[stimulus_id(3)].replies) == (1, 1)
    assert third[stimulus_id(4)].ancestry == (stimulus_id(3),)
    assert TracePartition.model_validate_json(partition.model_dump_json()) == partition


@pytest.mark.parametrize("likes", [0, 2])
def test_view_counts_must_equal_engagement_visible_from_earlier_ticks(likes):
    data = partition_payload()
    contexts_of(data, "third_turn")[stimulus_id(3)]["likes"] = likes
    with pytest.raises(ValidationError, match="1 were visible from earlier ticks"):
        TracePartition.model_validate(data)


def test_engagement_from_the_same_tick_is_not_yet_visible():
    data = partition_payload()
    third = data["events"][R["third_turn"]]
    third["tick"] = third["payload"]["turn"]["impression"]["tick"] = 3
    close_3 = data["events"].pop(R["close_3"])
    data["events"].insert(R["third_turn"], close_3)
    data["events"].pop(R["close_4"])
    resequence(data)
    with pytest.raises(ValidationError, match="shows 1 likes .* but 0 were visible"):
        TracePartition.model_validate(data)


@pytest.mark.parametrize(("upvotes", "downvotes", "valid"), [(1, 0, True), (0, 1, False), (0, 0, False)])
def test_upvotes_and_downvotes_are_counted_separately(upvotes, downvotes, valid):
    viewer_turn = turn_payload("p-000004", 5, [(4, "forum", 0.7)], {"subject_stimulus_id": stimulus_id(4), "action": "downvote"},
                               contexts={4: {"upvotes": upvotes, "downvotes": downvotes, "ancestry": [stimulus_id(3)], "tie_strength": 0.0}}, n=4)
    data = with_turn_before_completion(partition_payload(), 5, viewer_turn, "p-000004")
    if valid:
        assert TracePartition.model_validate(data).in_sequence[R["completed"]].payload.turn.view.contexts[stimulus_id(4)].upvotes == 1
    else:
        with pytest.raises(ValidationError, match="were visible from earlier ticks"):
            TracePartition.model_validate(data)


@pytest.mark.parametrize("ancestry", [[], [stimulus_id(1)], [stimulus_id(3), stimulus_id(1)]], ids=["missing-parent", "wrong-parent", "extra-ancestor"])
def test_view_ancestry_must_follow_the_reply_chain(ancestry):
    data = partition_payload()
    contexts_of(data, "third_turn")[stimulus_id(4)]["ancestry"] = ancestry
    with pytest.raises(ValidationError, match="its reply chain is"):
        TracePartition.model_validate(data)


@pytest.mark.parametrize(
    ("role", "stimulus", "change", "match"),
    [
        ("first_turn", 1, {"tie_strength": 0.3}, "which is the study's"),
        ("second_turn", 4, {"shared_community": True}, "which is the viewer's own"),
        ("third_turn", 3, {"tie_strength": None}, "records no tie strength"),
    ],
    ids=["study-authored", "viewers-own", "peer-authored-without-tie"],
)
def test_author_relationship_exists_only_for_other_personas_stimuli(role, stimulus, change, match):
    data = partition_payload()
    contexts_of(data, role)[stimulus_id(stimulus)].update(change)
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(data)


# --- world records ----------------------------------------------------------------------------


def world_record_payload() -> dict:
    return {"population": population_payload(), "partition": partition_payload()}


def test_world_record_joins_a_partition_with_its_population():
    record = WorldRecord.model_validate(world_record_payload())
    assert record.partition.header.population == record.population.manifest
    assert WorldRecord.model_validate_json(record.model_dump_json()) == record


def test_world_record_refuses_a_population_the_partition_did_not_run_over():
    other = population_payload(personas=[{**persona_payload(i), "attributes": {"diet_protein_focus": "low", "spend_band": "5_10"}} for i in range(4)])
    with pytest.raises(ValidationError, match="not this population's"):
        WorldRecord.model_validate({"population": other, "partition": partition_payload()})


@pytest.mark.parametrize(
    ("role", "stimulus", "change", "match"),
    [
        ("third_turn", 4, {"tie_strength": 0.3}, "but the graph has 0.2"),
        ("third_turn", 3, {"tie_strength": 0.5}, "but the graph has 0.0"),
        ("second_turn", 3, {"shared_community": False}, "a shared community"),
        ("third_turn", 4, {"shared_community": True}, "different communities"),
    ],
    ids=["wrong-tie", "tie-where-none-exists", "shared-community-denied", "different-communities-claimed-shared"],
)
def test_world_record_refuses_views_whose_ties_or_communities_disagree_with_the_population(role, stimulus, change, match):
    record = world_record_payload()
    contexts_of(record["partition"], role)[stimulus_id(stimulus)].update(change)
    TracePartition.model_validate(record["partition"])
    with pytest.raises(ValidationError, match=match):
        WorldRecord.model_validate(record)


def test_shared_community_is_absent_when_the_population_has_no_communities():
    population = population_payload(communities=[])
    manifest = population["manifest"]
    data = partition_payload()
    data["header"]["population"] = manifest
    data["header"]["config"]["population_hash"] = manifest["population_hash"]
    world = PartitionHeader.model_validate(data["header"]).world_id
    for record in data["events"]:
        record["world_id"] = world
    with pytest.raises(ValidationError, match="no communities"):
        WorldRecord.model_validate({"population": population, "partition": data})
    for role in ("second_turn", "third_turn", "violation"):
        for context in contexts_of(data, role).values():
            if context.get("shared_community") is not None:
                context["shared_community"] = None
    assert WorldRecord.model_validate({"population": population, "partition": data}).population.communities == ()



# --- closed ticks -----------------------------------------------------------------------------


def test_representative_partition_closes_every_tick_in_order():
    partition = TracePartition.model_validate(partition_payload())
    closes = [e.tick for e in partition.in_sequence if isinstance(e.payload, TickClosed)]
    assert closes == [0, 1, 2, 3, 4]


@pytest.mark.parametrize(
    ("close", "tick", "match"),
    [("close_1", 2, "closes tick 2, but ticks close in order and the next is 1"), ("close_0", 1, "the next is 0")],
    ids=["skipping-a-tick", "not-starting-at-zero"],
)
def test_ticks_close_in_order(close, tick, match):
    data = partition_payload()
    data["events"][R[close]]["tick"] = tick
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(data)


def test_nothing_is_recorded_for_a_tick_after_it_closed():
    data = partition_payload()
    late_drop = data["events"].pop(R["drop"])
    data["events"].insert(R["close_1"], late_drop)
    resequence(data)
    with pytest.raises(ValidationError, match="recorded for tick 1 after that tick closed"):
        TracePartition.model_validate(data)


def test_closing_a_tick_twice_is_refused():
    data = partition_payload()
    data["events"].insert(R["close_1"] + 1, copy.deepcopy(data["events"][R["close_1"]]))
    resequence(data)
    with pytest.raises(ValidationError, match="closes tick 1, but ticks close in order and the next is 2"):
        TracePartition.model_validate(data)


def test_a_tick_close_belongs_to_the_world_not_a_persona():
    record = copy.deepcopy(events_of(partition_payload())[R["close_0"]])
    record["persona_id"] = "p-000001"
    with pytest.raises(ValidationError, match="belongs to the world"):
        TraceEvent.model_validate(record)



# --- degradation ------------------------------------------------------------------------------


def rung(name: str, activation: float) -> dict:
    return {"kind": "degraded", "rung": name, "activation_rate": activation, "tier_b_frozen": name != "warn"}


def test_representative_partition_records_a_degradation_rung_and_round_trips():
    partition = TracePartition.model_validate(partition_payload())
    degraded = partition.in_sequence[R["warned"]].payload
    assert (degraded.rung.value, degraded.activation_rate, degraded.tier_b_frozen) == ("warn", 0.62, False)
    assert TracePartition.model_validate_json(partition.model_dump_json()) == partition


@pytest.mark.parametrize(
    ("name", "frozen"),
    [("warn", True), ("freeze_optional_tier_b", False), ("subsample_activation", False), ("pause", False)],
)
def test_a_rung_states_the_tier_b_freeze_it_implies(name, frozen):
    with pytest.raises(ValidationError, match="frozen from the freeze_optional_tier_b rung onwards"):
        Degraded.model_validate({"kind": "degraded", "rung": name, "activation_rate": 0.5, "tier_b_frozen": frozen})


def test_degradation_climbs_the_ladder_one_way():
    data = partition_payload()
    ladder = [rung("freeze_optional_tier_b", 0.62), rung("subsample_activation", 0.40), rung("pause", 0.40)]
    for offset, record in enumerate(ladder, start=1):
        data["events"].insert(R["warned"] + offset, event(0, 3, record))
    resequence(data)
    rungs = [e.payload.rung.value for e in TracePartition.model_validate(data).in_sequence if isinstance(e.payload, Degraded)]
    assert rungs == ["warn", "freeze_optional_tier_b", "subsample_activation", "pause"]


@pytest.mark.parametrize(
    ("second", "match"),
    [(rung("warn", 0.62), "degradation only escalates"), (rung("subsample_activation", 0.80), "degradation never restores it")],
    ids=["same-rung-again", "activation-raised"],
)
def test_degradation_that_does_not_escalate_is_refused(second, match):
    data = partition_payload()
    data["events"].insert(R["warned"] + 1, event(0, 3, second))
    resequence(data)
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(data)


def test_a_pause_follows_the_pause_rung_and_nothing_is_recorded_while_paused():
    data = partition_payload()
    data["events"][R["warned"]] = event(R["warned"], 3, PAUSE_RUNG)
    data["events"][R["launch"]] = event(R["launch"], 3, {"kind": "lifecycle", "phase": "paused"})
    with pytest.raises(ValidationError, match="recorded while the world is paused"):
        TracePartition.model_validate(data)


def test_degradation_belongs_to_the_world_not_a_persona():
    record = copy.deepcopy(events_of(partition_payload())[R["warned"]])
    record["persona_id"] = "p-000001"
    with pytest.raises(ValidationError, match="belongs to the world"):
        TraceEvent.model_validate(record)



# --- routes -----------------------------------------------------------------------------------


def cost(**overrides) -> dict:
    return {**events_of(partition_payload())[R["first_turn_cost"]]["payload"], **overrides}


@pytest.mark.parametrize(("route", "cached"), [("primary", False), ("fallback", False), ("cache", True)])
def test_a_cost_names_its_route_and_cache_service_follows_from_it(route, cached):
    source = {"cost_source": "cache"} if route == "cache" else {}
    record = CostRecorded.model_validate(cost(route=route, cost=0.0, **source))
    assert record.cache_hit is cached
    assert "cache_hit" not in CostRecorded.model_fields
    assert CostRecorded.model_validate_json(record.model_dump_json()) == record


def test_a_stated_cache_hit_contradicting_the_route_is_refused():
    with pytest.raises(ValidationError, match="computed"):
        CostRecorded.model_validate({**cost(route="primary"), "cache_hit": True})
    with pytest.raises(ValidationError):
        CostRecorded.model_validate({k: v for k, v in cost().items() if k != "route"})


def test_a_call_served_from_the_cache_bills_nothing():
    with pytest.raises(ValidationError, match="bills nothing"):
        CostRecorded.model_validate(cost(route="cache", cost_source="cache", cost=0.004))


# --- fallbacks --------------------------------------------------------------------------------


def pins(**overrides) -> dict:
    return {**run_config_payload()["pins"], **overrides}


def test_pins_accept_one_fallback_per_role():
    parsed = ModelPins.model_validate(pins(fallbacks={"tier_a": "openrouter/qwen/qwen-2.5-7b-instruct", "tier_b": "openai/gpt-4o-2024-08-06"}))
    assert {role: pin.model_id for role, pin in parsed.fallbacks.items()} == {InferenceRole.TIER_A: "openrouter/qwen/qwen-2.5-7b-instruct", InferenceRole.TIER_B: "openai/gpt-4o-2024-08-06"}
    assert ModelPins.model_validate(pins(fallbacks={})).fallbacks == {}


@pytest.mark.parametrize(
    ("fallbacks", "overrides", "match"),
    [
        ({"embed": "openai/text-embedding-3-large"}, {}, "never falls back"),
        ({"tier_a": "openrouter/camel-ai/persona-8b"}, {}, "is its primary model"),
        ({"safety": "openai/omni-moderation-2024-09-26"}, {"safety": None}, "no primary model"),
        ({"tier_a": "openrouter/qwen/qwen-latest"}, {}, "floating"),
    ],
    ids=["embedding-fallback", "fallback-is-primary", "fallback-without-primary", "floating-fallback"],
)
def test_pins_refuse_fallbacks_that_are_not_real_pinned_alternatives(fallbacks, overrides, match):
    with pytest.raises(ValidationError, match=match):
        ModelPins.model_validate(pins(fallbacks=fallbacks, **overrides))


def test_representative_partition_bills_a_fallback_served_turn():
    billed = TracePartition.model_validate(partition_payload()).in_sequence[R["second_turn_cost"]].payload
    assert (billed.route.value, billed.model_id) == ("fallback", "openrouter/qwen/qwen-2.5-7b-instruct")


@pytest.mark.parametrize(
    ("role", "change", "valid"),
    [
        ("first_turn_cost", {"route": "primary", "model_id": "anthropic/claude-sonnet-4-5-20250929"}, True),
        ("first_turn_cost", {"route": "fallback", "model_id": "anthropic/claude-sonnet-4-5-20250929"}, False),
        ("second_turn_cost", {"route": "primary", "model_id": "openrouter/qwen/qwen-2.5-7b-instruct"}, False),
        ("second_turn_cost", {"route": "cache", "cost_source": "cache", "model_id": "openrouter/qwen/qwen-2.5-7b-instruct", "cost": 0.0}, True),
        ("second_turn_cost", {"route": "cache", "cost_source": "cache", "model_id": "openrouter/camel-ai/persona-8b", "cost": 0.0}, True),
        ("second_turn_cost", {"route": "cache", "cost_source": "cache", "model_id": "openai/gpt-4o-2024-08-06", "cost": 0.0}, False),
        ("second_turn_cost", {"route": "fallback", "model_id": "openrouter/camel-ai/persona-8b"}, False),
    ],
    ids=["primary-on-primary", "tier-b-without-fallback", "fallback-on-primary-route", "cached-fallback",
         "cached-primary", "cached-unpinned", "primary-on-fallback-route"],
)
def test_a_billed_model_must_match_its_route(role, change, valid):
    data = partition_payload()
    data["events"][R[role]]["payload"].update(change)
    if valid:
        assert TracePartition.model_validate(data).in_sequence[R[role]].payload.route.value == change["route"]
    else:
        with pytest.raises(ValidationError, match="but the run pins"):
            TracePartition.model_validate(data)



# --- guardrail retries ------------------------------------------------------------------------


def test_representative_first_turn_was_accepted_on_its_retry():
    turn = TracePartition.model_validate(partition_payload()).in_sequence[R["first_turn"]].payload
    assert turn.rejected_prompt_hashes == ("56" * 32,) and turn.prompt_hash not in turn.rejected_prompt_hashes


@pytest.mark.parametrize(
    ("rejected", "match"),
    [(["56" * 32, "78" * 32], "retried at most once"), (["12" * 32], "cannot also be the one rejected")],
    ids=["two-rejections", "rejected-is-accepted"],
)
def test_a_turn_names_at_most_one_rejected_prompt_distinct_from_the_accepted_one(rejected, match):
    record = copy.deepcopy(events_of(partition_payload())[R["first_turn"]])
    record["payload"]["rejected_prompt_hashes"] = rejected
    with pytest.raises(ValidationError, match=match):
        TraceEvent.model_validate(record)


def test_a_turn_accepted_first_time_names_no_rejected_prompt():
    assert TracePartition.model_validate(partition_payload()).in_sequence[R["second_turn"]].payload.rejected_prompt_hashes == ()


# --- guardrail violations ---------------------------------------------------------------------


def violation_record() -> dict:
    return copy.deepcopy(events_of(partition_payload())[R["violation"]])


def test_representative_violation_records_what_was_presented_and_no_reaction():
    partition = TracePartition.model_validate(partition_payload())
    violation = partition.in_sequence[R["violation"]].payload
    assert isinstance(violation, GuardrailViolation)
    assert violation.rule.value == "references_unshown_stimulus"
    assert violation.prompt_hashes == ("9a" * 32, "9b" * 32)
    assert violation.view.impression_id == violation.impression.impression_id
    assert set(GuardrailViolation.model_fields) == {"kind", "impression", "view", "prompt_hashes", "rule"}
    assert TracePartition.model_validate_json(partition.model_dump_json()) == partition


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda p: p.update(prompt_hashes=["9a" * 32, "9a" * 32]), "two rejected prompts differ"),
        (lambda p: p.update(prompt_hashes=["9a" * 32]), "prompt_hashes"),
        (lambda p: p.update(prompt_hashes=["9a" * 32, "9b" * 32, "9c" * 32]), "prompt_hashes"),
        (lambda p: p.update(rule="invented_rule"), "rule"),
        (lambda p: p.update(reaction={"reaction_id": f"rc-{ulid(305)}", "subject_stimulus_id": stimulus_id(3), "action": "like"}), "reaction"),
        (lambda p: p["view"]["contexts"].pop(stimulus_id(4)), "a view covers exactly the stimuli of its impression"),
    ],
    ids=["same-prompt-twice", "one-attempt", "three-attempts", "unknown-rule", "with-a-reaction", "view-misses-a-stimulus"],
)
def test_a_violation_carries_two_distinct_rejected_prompts_a_known_rule_and_no_reaction(change, match):
    record = violation_record()
    change(record["payload"])
    with pytest.raises(ValidationError, match=match):
        TraceEvent.model_validate(record)


@pytest.mark.parametrize(
    ("change", "match"),
    [({"persona_id": "p-000003"}, "shown to p-000004"), ({"tick": 3}, "impression from tick 4"), ({"persona_id": None}, "must name it")],
    ids=["other-persona", "other-tick", "unattributed"],
)
def test_a_violation_belongs_to_its_impressions_persona_and_tick(change, match):
    with pytest.raises(ValidationError, match=match):
        TraceEvent.model_validate({**violation_record(), **change})


def test_an_impression_is_either_a_turn_or_a_violation_never_both():
    data = partition_payload()
    third = data["events"][R["third_turn"]]["payload"]["turn"]["impression"]["impression_id"]
    violation = data["events"][R["violation"]]["payload"]
    violation["impression"]["impression_id"] = violation["view"]["impression_id"] = third
    with pytest.raises(ValidationError, match=f"repeats impression {third}"):
        TracePartition.model_validate(data)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda p: p["view"]["contexts"][stimulus_id(3)].update(likes=0), "1 were visible from earlier ticks"),
        (lambda p: p["view"]["contexts"][stimulus_id(4)].update(upvotes=1), "0 were visible from earlier ticks"),
        (lambda p: p["view"]["contexts"][stimulus_id(4)].update(ancestry=[]), "its reply chain is"),
        (lambda p: p["view"]["contexts"][stimulus_id(3)].update(tie_strength=None), "records no tie strength"),
    ],
    ids=["hidden-like", "same-tick-upvote", "broken-reply-chain", "peer-without-tie"],
)
def test_a_partition_verifies_a_violations_view_as_it_does_a_turns(change, match):
    data = partition_payload()
    change(data["events"][R["violation"]]["payload"])
    with pytest.raises(ValidationError, match=match):
        TracePartition.model_validate(data)


def test_a_violation_shows_only_published_stimuli_within_the_budget():
    data = partition_payload()
    data["events"][R["violation"]] = violation_event(R["violation"], 4, [(3, "wom", 0.4), (9, "forum", 0.4)], "p-000004", n=5)
    with pytest.raises(ValidationError, match="never published"):
        TracePartition.model_validate(data)


def test_a_violation_adds_no_engagement_to_later_views():
    later = turn_payload("p-000001", 5, [(4, "forum", 0.7)], {"subject_stimulus_id": stimulus_id(4), "action": "ignore"},
                         contexts={4: {"upvotes": 1, "ancestry": [stimulus_id(3)], "tie_strength": 0.8, "shared_community": True}}, n=6)
    assert TracePartition.model_validate(with_turn_before_completion(partition_payload(), 5, later, "p-000001"))


@pytest.mark.parametrize(
    ("stimulus", "change", "match"),
    [(3, {"tie_strength": 0.6}, "but the graph has 0.0"), (4, {"shared_community": True}, "different communities")],
    ids=["invented-tie", "claimed-shared-community"],
)
def test_world_record_checks_a_violations_view_against_the_population(stimulus, change, match):
    data = world_record_payload()
    data["partition"]["events"][R["violation"]]["payload"]["view"]["contexts"][stimulus_id(stimulus)].update(change)
    with pytest.raises(ValidationError, match=match):
        WorldRecord.model_validate(data)


def test_engagement_counts_only_where_the_channel_affords_the_action():
    """A persona may attempt anything; the channel decides what lands. A feed has no votes, so an
    upvote there changes no state and no view shows it — but the partition counted every action
    as engagement whatever channel it happened on, and then refused the world's own honest view.
    Found by the first real study, whose personas voted on a feed."""
    from simcore.schemas import action_lands, Channel, ActionKind

    assert action_lands(Channel.FORUM, ActionKind.UPVOTE)
    assert not action_lands(Channel.SOCIAL_FEED, ActionKind.UPVOTE)
    assert action_lands(Channel.SOCIAL_FEED, ActionKind.LIKE)
    assert action_lands(Channel.SURVEY_ROOM, ActionKind.IGNORE)

    data = partition_payload()
    # p-000002 upvotes on the feed at tick 3. The feed affords no votes, so nothing lands and
    # nothing is visible to the turn that follows at tick 4 — not as an upvote, and not as the
    # like that turn's view used to show.
    second = data["events"][R["second_turn"]]
    second["payload"]["turn"]["reaction"]["action"] = "upvote"
    second["payload"]["turn"]["reaction"].pop("verbatim", None)
    for context in data["events"][R["third_turn"]]["payload"]["turn"]["view"]["contexts"].values():
        context["likes"] = 0
    for context in data["events"][R["violation"]]["payload"]["view"]["contexts"].values():
        context["likes"] = 0
    partition = TracePartition.model_validate(data)
    third = partition.in_sequence[R["third_turn"]].payload
    assert all(context.upvotes == 0 and context.likes == 0 for context in third.turn.view.contexts.values())


def test_a_told_stimulus_records_the_tie_to_whoever_told_you():
    """Word of mouth carries a tie to the teller, not to the author, so a peer can tell you about
    the study's own concept — which has no author at all. The rule assumed every relationship was
    to an author and refused that view. Found the moment beliefs began moving and word of mouth
    started firing: a persona told a peer about the concept, and the engine rejected its own
    honest record."""
    data = partition_payload()
    # the first turn was shown the concept, which the study wrote; a peer passed it on
    contexts = data["events"][R["first_turn"]]["payload"]["turn"]["view"]["contexts"]
    contexts[stimulus_id(1)].update(via_persona_id="p-000003", tie_strength=0.7, shared_community=True)
    partition = TracePartition.model_validate(data)
    told = partition.in_sequence[R["first_turn"]].payload.turn.view.contexts[stimulus_id(1)]
    assert told.via_persona_id == "p-000003" and told.tie_strength == 0.7

    # and with nobody named as teller, a relationship on the study's own stimulus is still refused
    data = partition_payload()
    data["events"][R["first_turn"]]["payload"]["turn"]["view"]["contexts"][stimulus_id(1)]["tie_strength"] = 0.7
    with pytest.raises(ValidationError, match="which is the study's"):
        TracePartition.model_validate(data)

    # a viewer cannot be told about something by itself
    data = partition_payload()
    data["events"][R["first_turn"]]["payload"]["turn"]["view"]["contexts"][stimulus_id(1)].update(
        via_persona_id="p-000001", tie_strength=0.7
    )
    with pytest.raises(ValidationError, match="told by itself|its own"):
        TracePartition.model_validate(data)
