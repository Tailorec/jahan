"""Reading a run one world at a time.

`digest(view) -> OutcomeDigest` yields one digest, and a digest names one scenario and one
tick unit, so a sweep's worlds have to be readable apart (ADR 0037 keeps them comparable only
when they ran at the same rung). A run-wide view that merged them, with no way to ask for one,
would have made per-cell digests impossible.
"""

import pytest

from simcore.schemas import EventFilter
from simcore.trace import TraceStore
from tests.boundary.trace.support import partition_events, seed_header_and_entry, write_by_tick

def test_a_sweep_can_be_read_one_world_at_a_time(tmp_path):
    """`digest(view)` yields one digest, and a digest names one scenario and tick unit — so a
    sweep's worlds have to be readable apart. A run-wide view merged them with no way to ask
    for one, which would have made per-cell digests impossible."""
    from simcore.schemas import PartitionHeader
    from tests.study_builders import partition_header_payload

    store = TraceStore(tmp_path)
    header, entry = seed_header_and_entry(store)
    events, _ = partition_events()
    write_by_tick(store, events)
    run_id = entry.config.run_id

    # a second world of the same run: the other replicate seed the config declares
    other_seed = next(seed for seed in entry.config.seeds if seed != header.replicate_seed)
    second = PartitionHeader.model_validate({**partition_header_payload(), "replicate_seed": other_seed})
    store.create_world(run_id, second)
    second_events = [
        event.model_copy(update={"world_id": second.world_id, "event_id": f"ev-{'1' * 22}{index:04d}"})
        for index, event in enumerate(events)
    ]
    write_by_tick(store, second_events)

    whole = store.view(run_id)
    assert len({event.world_id for event in whole.events(EventFilter())}) == 2

    scoped = store.view(run_id, header.world_id)
    worlds = {event.world_id for event in scoped.events(EventFilter())}
    assert worlds == {header.world_id}
    assert scoped.edges() == store.view(run_id, header.world_id).edges()

    # and the filter can narrow within a view
    narrowed = whole.events(EventFilter(world_ids=(second.world_id,)))
    assert {event.world_id for event in narrowed} == {second.world_id}


def test_a_view_refuses_a_world_that_is_not_in_the_run(tmp_path):
    store = TraceStore(tmp_path)
    _, entry = seed_header_and_entry(store)
    with pytest.raises(Exception, match="not a world of"):
        store.view(entry.config.run_id, "ffffffffffff")
