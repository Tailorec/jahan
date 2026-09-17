"""Phase 2: replay and resume.

A world reconstructed by `reset` and replaying its recorded turns reproduces
every recorded delta exactly, so resume and the determinism check are the
same mechanism. Internal checkpoints may speed replay up; a run with
checkpoints produces what a run without them produces.
"""

import pytest

from simcore.schemas import canonical_json
from simcore.world import ReplayDivergence, World, check_replay, replay_run, resume

from .helpers import drive, make_header, make_world


def test_replaying_recorded_turns_reproduces_every_delta_field_for_field():
    world = make_world()
    recorded, turns_by_tick = drive(world, [1, 2, 3])
    replayed = replay_run(make_header(), turns_by_tick)
    assert [canonical_json(delta) for delta in replayed] == [canonical_json(delta) for delta in recorded]
    check_replay(recorded, make_header(), turns_by_tick)


def test_a_world_resumed_at_tick_n_continues_identically():
    world = make_world()
    recorded, turns_by_tick = drive(world, [1, 2, 3, 4])
    resumed = resume(make_header(), turns_by_tick, through_tick=2)
    continued = [resumed.step(3, turns_by_tick[2]), resumed.step(4, turns_by_tick[3])]
    assert [canonical_json(delta) for delta in continued] == [
        canonical_json(delta) for delta in recorded[3:]
    ]


def test_a_checkpoint_changes_speed_and_never_output():
    world = make_world()
    recorded, turns_by_tick = drive(world, [1, 2, 3, 4])
    early = make_world()
    early.reset()
    early.step(1, [])
    early.step(2, turns_by_tick[1])
    snapshot = early.checkpoint()
    restarted = World.restore(make_header(), snapshot)
    continued = [restarted.step(3, turns_by_tick[2]), restarted.step(4, turns_by_tick[3])]
    assert [canonical_json(delta) for delta in continued] == [
        canonical_json(delta) for delta in recorded[3:]
    ]
    assert restarted.state_dump() == world.state_dump()


def test_a_replay_that_diverges_fails_loudly_naming_tick_and_field():
    world = make_world()
    recorded, turns_by_tick = drive(world, [1, 2])
    tampered = recorded[1].model_copy(
        update={
            "presentations": tuple(
                p.model_copy(
                    update={
                        "impression": p.impression.model_copy(
                            update={
                                "exposures": tuple(
                                    e.model_copy(update={"attention": 0.5}) for e in p.impression.exposures
                                )
                            }
                        )
                    }
                )
                for p in recorded[1].presentations
            )
        }
    )
    with pytest.raises(ReplayDivergence, match=r"tick 1.*presentations"):
        check_replay([recorded[0], tampered, recorded[2]], make_header(), turns_by_tick)


def test_replay_needs_nothing_but_the_header_and_the_recorded_turns():
    world = make_world()
    recorded, turns_by_tick = drive(world, [1, 2])
    fresh_header = make_header()
    replayed = replay_run(fresh_header, turns_by_tick)
    assert [canonical_json(delta) for delta in replayed] == [canonical_json(delta) for delta in recorded]
