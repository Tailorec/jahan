"""Phase 2: a digest of one world, derived from its trace view."""

from collections import Counter

from simcore.analysis import digest
from simcore.schemas import (
    BeliefDim,
    EventFilter,
    Population,
    Scenario,
    canonical_hash,
)
from simcore.trace import TraceStore
from tests.boundary.trace.support import seed_header_and_entry, write_by_tick
from tests.study_builders import (
    partition_payload,
    population_payload,
    scenario_payload,
    ssr_payload,
)


def _population(**overrides):
    return Population.model_validate(population_payload(**overrides))


def _scenario(**overrides):
    return Scenario.model_validate(scenario_payload(**overrides))


def _seed_world(store: TraceStore, *, payload=None):
    from simcore.schemas import TraceEvent

    payload = payload or partition_payload()
    header, entry = seed_header_and_entry(store)
    events = [TraceEvent.model_validate(record) for record in payload["events"]]
    write_by_tick(store, events)
    return header, entry, events


def _strip_intent(payload: dict) -> dict:
    for record in payload["events"]:
        turn = (record.get("payload") or {}).get("turn")
        if turn is None:
            continue
        reaction = turn["reaction"]
        reaction["intent"] = None
        reaction["elicitation_failure"] = {
            "kind": "unpinned_anchors",
            "detail": "no anchor version is pinned for purchase_intent",
            "response_text": reaction.get("verbatim") or "",
            "construct_id": "purchase_intent",
        }
    return payload


def test_digest_of_a_real_recorded_world_names_its_scenario_and_tick_unit(tmp_path):
    store = TraceStore(tmp_path)
    header, _, _ = _seed_world(store)
    view = store.view(header.config.run_id, header.world_id)
    result = digest(view, scenario=header.scenario, population=_population(), seed=header.replicate_seed)
    assert result.scenario_hash == canonical_hash(header.scenario)
    assert result.tick_unit is header.scenario.tick_unit


def test_world_with_scored_intent_reports_masses_with_shares_and_sizes(tmp_path):
    store = TraceStore(tmp_path)
    header, _, _ = _seed_world(store)
    view = store.view(header.config.run_id, header.world_id)
    result = digest(view, scenario=header.scenario, population=_population(), seed=header.replicate_seed)
    assert result.adoption is not None
    assert set(result.audience_pmfs) == set(result.audience_shares) == {"gym_regulars"}
    assert abs(sum(result.audience_shares.values()) - 1.0) < 1e-3
    assert set(result.community_pmfs) == set(result.community_sizes)
    assert result.unmeasured_reason is None
    assert result.turns_without_intent == 2


def test_world_with_no_scored_intent_reports_unmeasured_with_the_count(tmp_path):
    store = TraceStore(tmp_path)
    header, _, _ = _seed_world(store, payload=_strip_intent(partition_payload()))
    view = store.view(header.config.run_id, header.world_id)
    result = digest(view, scenario=header.scenario, population=_population(), seed=header.replicate_seed)
    assert result.adoption is None
    assert result.polarization is None
    assert result.audience_divergence is None
    assert result.unmeasured_reason is not None
    assert result.turns_without_intent == result.turn_count == 3


def test_action_mix_belief_movement_and_wom_match_recomputation(tmp_path):
    store = TraceStore(tmp_path)
    header, _, _ = _seed_world(store)
    view = store.view(header.config.run_id, header.world_id)
    result = digest(view, scenario=header.scenario, population=_population(), seed=header.replicate_seed)

    events = view.events(EventFilter())
    turns = [event for event in events if event.payload.kind == "turn"]
    assert dict(result.action_mix) == dict(Counter(turn.reaction.action.value for turn in (t.payload.turn for t in turns)))
    assert result.turn_count == len(turns)

    for dim in BeliefDim:
        deltas = [float(turn.payload.turn.reaction.belief_change.dimensions.get(dim, 0.0)) for turn in turns]
        assert result.belief_movement_mean[dim] == sum(deltas) / len(deltas)
        assert result.belief_movement_abs[dim] == sum(abs(d) for d in deltas) / len(deltas)

    edges = view.edges()
    assert result.wom_deliveries == sum(edge.count for edge in edges)
    assert result.wom_reach == len({edge.v for edge in edges})


def test_persona_counted_in_exactly_one_audience(tmp_path):
    from simcore.schemas import Persona

    population = _population()
    personas = []
    for persona in population.personas:
        if persona.persona_id in ("p-000003", "p-000004"):
            personas.append(Persona.model_copy(
                persona, update={"conditioning": {"age": "25_34", "sex": "female", "exercise_frequency": "never"}}))
        else:
            personas.append(persona)
    from simcore.schemas import derive_population_hash

    population_hash = derive_population_hash(
        population.pack, population.manifest.population_seed, personas, population.graph, population.communities)
    manifest = population.manifest.model_copy(update={"population_hash": population_hash})
    population = Population.model_copy(population, update={"personas": tuple(personas), "manifest": manifest})

    from simcore.analysis._audience import audience_of_persona

    assigned = [audience_of_persona(p, tuple(population.pack.brief.audiences), population.pack.ontology) for p in personas]
    assert assigned[:2] == ["gym_regulars", "gym_regulars"]
    assert assigned[2:] == ["protein_dieters", "protein_dieters"]

    from simcore.schemas import PartitionHeader, RunRegistryEntry, TraceEvent
    from tests.study_builders import partition_header_payload, partition_run_config

    store = TraceStore(tmp_path)
    payload = partition_payload()
    # Score a community-2 turn so both audiences and both communities carry masses.
    for record in payload["events"]:
        turn = (record.get("payload") or {}).get("turn")
        if turn is not None and turn["impression"]["persona_id"] == "p-000003":
            turn["reaction"]["intent"] = ssr_payload()
    scenario_dict = scenario_payload()
    header_dict = partition_header_payload(scenario_dict)
    header_dict["population"] = manifest.model_dump(mode="json")
    header_dict["config"] = partition_run_config(
        scenario_dict, population_hash=manifest.population_hash, graph_hash=manifest.graph_hash)
    header = PartitionHeader.model_validate(header_dict)
    store.registry.record(RunRegistryEntry.model_validate({
        "config": header.config.model_dump(mode="json"), "contract_version": header.contract_version,
        "status": "running", "engine_version": "0a35555"}))
    store.create_world(header.config.run_id, header)
    events = [TraceEvent.model_validate({**record, "world_id": header.world_id}) for record in payload["events"]]
    write_by_tick(store, events)
    view = store.view(header.config.run_id, header.world_id)
    result = digest(view, scenario=_scenario(), population=population, seed=header.replicate_seed)
    assert set(result.audience_pmfs) == {"gym_regulars", "protein_dieters"}
    assert set(result.community_pmfs) == {"community-1", "community-2"}


def test_digesting_the_same_view_twice_is_identical(tmp_path):
    store = TraceStore(tmp_path)
    header, _, _ = _seed_world(store)
    population = _population()
    first = digest(store.view(header.config.run_id, header.world_id), scenario=header.scenario, population=population, seed=header.replicate_seed)
    second = digest(store.view(header.config.run_id, header.world_id), scenario=header.scenario, population=population, seed=header.replicate_seed)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
