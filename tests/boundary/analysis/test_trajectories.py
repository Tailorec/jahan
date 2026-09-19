"""Phase 9: trajectories per audience and per community per tick.

A derived shape in `analysis`, matching the same quantities recomputed from raw events.
"""

from collections import defaultdict
from pathlib import Path

from simcore.analysis import trajectories
from simcore.analysis._audience import audience_of_persona
from simcore.schemas import Population, Scenario, TraceEvent
from simcore.trace import TraceStore
from tests.boundary.trace.support import seed_header_and_entry, write_by_tick
from tests.study_builders import partition_payload, population_payload, scenario_payload


def test_trajectories_match_quantities_recomputed_from_raw_events(tmp_path: Path):
    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    raw_payload_events = partition_payload()["events"]
    events = [TraceEvent.model_validate(record) for record in raw_payload_events]
    write_by_tick(store, events)

    view = store.view(entry.config.run_id, header.world_id)
    population = Population.model_validate(population_payload())
    scenario = Scenario.model_validate(scenario_payload())

    traj = trajectories(view, scenario=scenario, population=population)

    # Independently recompute from raw events
    audience_of = {
        p.persona_id: audience_of_persona(
            p, tuple(population.pack.brief.audiences), population.pack.ontology
        )
        for p in population.personas
    }
    community_of = {
        m: c.community_id
        for c in population.communities
        for m in c.member_ids
    }

    expected_aud: dict[tuple[int, str], list[dict[str, float]]] = defaultdict(list)
    expected_comm: dict[tuple[int, str], list[dict[str, float]]] = defaultdict(list)

    for record in raw_payload_events:
        if record["payload"]["kind"] != "belief_snapshot" or not record.get("persona_id"):
            continue
        tick = record["tick"]
        dims = record["payload"]["beliefs"]["dimensions"]
        pid = record["persona_id"]
        aud = audience_of.get(pid)
        if aud:
            expected_aud[(tick, aud)].append(dims)
        comm = community_of.get(pid)
        if comm:
            expected_comm[(tick, comm)].append(dims)

    # Check audience trajectories match
    for aud, points in traj.audiences.items():
        for pt in points:
            raw_dims_list = expected_aud[(pt.tick, aud)]
            assert pt.count == len(raw_dims_list)
            for dim_key, dim_val in pt.dimensions.items():
                expected_mean = sum(d[dim_key] for d in raw_dims_list) / len(raw_dims_list)
                assert abs(dim_val - expected_mean) < 1e-6
            expected_overall = sum(pt.dimensions.values()) / len(pt.dimensions)
            assert abs(pt.mean_belief - expected_overall) < 1e-6

    # Check community trajectories match
    for comm, points in traj.communities.items():
        for pt in points:
            raw_dims_list = expected_comm[(pt.tick, comm)]
            assert pt.count == len(raw_dims_list)
            for dim_key, dim_val in pt.dimensions.items():
                expected_mean = sum(d[dim_key] for d in raw_dims_list) / len(raw_dims_list)
                assert abs(dim_val - expected_mean) < 1e-6
            expected_overall = sum(pt.dimensions.values()) / len(pt.dimensions)
            assert abs(pt.mean_belief - expected_overall) < 1e-6
