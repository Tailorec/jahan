"""Phase 4: platform state in SQLite.

The salvaged platform tables, extended with provenance columns written at the
time the row is written, hold published stimuli, engagement, follows and
rejections. Actions arriving in recorded turns are applied to them; an action
its channel does not support is rejected and recorded rather than raised.
"""

import subprocess
import sys

from simcore.schemas import Turn, WorldDelta
from simcore.world import World, resume
from tests.study_builders import stimulus_id, turn_payload

from .helpers import answer_turn, drive, make_header, make_world


def feed_like(persona: str = "p-000001", tick: int = 1) -> Turn:
    """A like on the feed channel: supported, counted, and visible from the next tick."""
    return Turn.model_validate(
        turn_payload(
            persona,
            tick,
            [(1, "interest", 0.8)],
            {"subject_stimulus_id": stimulus_id(1), "action": "like"},
        )
    )


def test_platform_state_is_sqlite_internal_and_absent_from_any_delta():
    assert set(WorldDelta.model_fields) == {"tick", "published", "interventions", "dropped", "presentations"}
    world = make_world()
    world.reset()
    for table in ("stimuli", "engagements", "follows", "rejected"):
        columns = world.store_columns(table)
        assert "world_id" in columns and "written_tick" in columns


def test_supported_actions_apply_and_the_state_they_produce_survives_replay():
    world = make_world()
    world.reset()
    world.step(1, [])
    world.step(2, [feed_like()])
    assert "engagement:" in world.state_dump()
    assert world.provenance_complete()
    replayed = resume(make_header(), {1: [feed_like()]}, through_tick=2)
    assert replayed.state_dump() == world.state_dump()


def test_an_unsupported_action_is_rejected_and_changes_no_state():
    world = make_world()
    world.reset()
    first = world.step(1, [])
    liked = [answer_turn(p, n, action="like") for n, p in enumerate(first.presentations)]
    before = world.state_dump()
    world.step(2, liked)
    rejected = world.rejected_actions()
    assert len(rejected) == len(first.presentations)
    assert all(entry["action"] == "like" and entry["channel"] == "survey_room" for entry in rejected)
    after = world.state_dump()
    assert "engagement:" not in after
    assert [line for line in after.splitlines() if not line.startswith("rejected:")] == before.splitlines()


def test_provenance_columns_are_written_at_write_time_not_backfilled():
    world = make_world()
    world.reset()
    world.step(1, [])
    world.step(2, [feed_like(), feed_like("p-000002")])
    assert world.provenance_complete()
    dump = world.state_dump()
    assert f"|{world.world_id}|" in dump


def test_two_processes_reach_identical_state_from_the_same_turns():
    script = (
        "import sys; sys.path.insert(0, '.');"
        "from simcore.schemas import Turn;"
        "from simcore.world import World;"
        "from tests.study_builders import stimulus_id, turn_payload, partition_header_payload;"
        "from simcore.schemas import PartitionHeader;"
        "world = World(PartitionHeader.model_validate(partition_header_payload()));"
        "world.reset(); world.step(1, []);"
        "turn = Turn.model_validate(turn_payload('p-000001', 1, [(1, 'interest', 0.8)],"
        " {'subject_stimulus_id': stimulus_id(1), 'action': 'like'}));"
        "world.step(2, [turn]);"
        "print(world.state_dump(), end='')"
    )
    world = make_world()
    world.reset()
    world.step(1, [])
    world.step(2, [feed_like()])
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=".")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == world.state_dump()
