"""Phase 1: the loop and the survey room.

`reset` opens a world at tick zero from its header; `step` takes the previous
tick's recorded turns and returns a delta built from the trace's own record
types. The survey room shows every persona the stimulus alone — one exposure
per impression, no social signal, no ranking. Everything is deterministic
under a fixed seed.
"""

import json
import subprocess
import sys

import pytest

from simcore.schemas import Channel, WorldDelta, canonical_json
from simcore.world import World, forget, reset, step
from tests.study_builders import PERSONA_IDS

from .helpers import answer_turn, make_header, make_world

FORBIDDEN_KEYS = frozenset(
    {
        "world_state",
        "world_seed",
        "sqlite",
        "store",
        "population",
        "graph",
        "persona_state",
        "event_id",
        "seq",
        "sequence",
        "world_id",
        "seed",
    }
)


def assert_no_world_state(delta: WorldDelta) -> None:
    """No world state crosses the boundary, asserted over the whole structure."""

    def walk(node, path="delta"):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_KEYS, f"world state at {path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(json.loads(delta.model_dump_json()))


def test_reset_returns_the_opening_delta_as_tick_zero_from_trace_types():
    world = make_world()
    delta = world.reset()
    assert delta.tick == 0
    assert delta.dropped == ()
    # Tick 0 always waves: the baseline survey goes out with the opening delta, after launch.
    assert [p.impression.persona_id for p in delta.presentations] == sorted(PERSONA_IDS)
    for presentation in delta.presentations:
        assert presentation.impression.channel is Channel.SURVEY_ROOM
        assert len(presentation.impression.exposures) == 1
        assert presentation.impression.exposures[0].stimulus_id == world.concept_id()
    kinds = [stimulus.kind.value for stimulus in delta.published]
    assert kinds[0] == "concept"
    assert kinds[1:] == ["claim_post"] * 3
    assert [stimulus.claim_id for stimulus in delta.published[1:]] == ["C1", "C2", "C3"]
    assert all(stimulus.tick == 0 for stimulus in delta.published)
    assert all(stimulus.author is None for stimulus in delta.published)
    assert delta.interventions == ()
    assert_no_world_state(delta)


def test_step_returns_one_survey_presentation_per_persona():
    world = make_world()
    world.reset()
    delta = world.step(1, [])
    assert delta.tick == 1
    assert [p.impression.persona_id for p in delta.presentations] == sorted(PERSONA_IDS)
    for presentation in delta.presentations:
        assert presentation.impression.channel is Channel.SURVEY_ROOM
        assert len(presentation.impression.exposures) == 1
        exposure = presentation.impression.exposures[0]
        assert exposure.stimulus_id == world.concept_id()
        assert exposure.reason.value == "interest"
        assert exposure.attention == 1.0 and exposure.seen is True


def test_survey_view_carries_no_social_signal_even_after_engagement():
    world = make_world()
    world.reset()
    first = world.step(1, [])
    likes = [answer_turn(p, n, action="like") for n, p in enumerate(first.presentations)]
    second = world.step(2, likes)
    for presentation in second.presentations:
        (context,) = presentation.view.contexts.values()
        assert (context.likes, context.reposts, context.replies, context.upvotes, context.downvotes) == (0, 0, 0, 0, 0)
        assert context.tie_strength is None and context.shared_community is None
        assert context.ancestry == ()


def test_step_takes_recorded_turns_and_returns_no_unsurveyed_state():
    world = make_world()
    world.reset()
    first = world.step(1, [])
    turns = [answer_turn(p, n) for n, p in enumerate(first.presentations)]
    second = world.step(2, turns)
    assert second.published == () and second.dropped == ()
    assert len(second.presentations) == len(PERSONA_IDS)
    assert_no_world_state(second)


def test_step_is_deterministic_under_a_fixed_seed():
    first, second = make_world(), make_world()
    deltas_first = [first.reset(), first.step(1, [])]
    deltas_second = [second.reset(), second.step(1, [])]
    assert [canonical_json(delta) for delta in deltas_first] == [
        canonical_json(delta) for delta in deltas_second
    ]
    assert first.state_dump() == second.state_dump()


def test_step_is_bit_identical_across_two_processes(tmp_path):
    script = (
        "import sys; sys.path.insert(0, '.');"
        "from simcore.schemas import PartitionHeader, canonical_json;"
        "from simcore.world import World;"
        "from tests.study_builders import partition_header_payload;"
        "from tests.boundary.world.helpers import answer_turn;"
        "world = World(PartitionHeader.model_validate(partition_header_payload()));"
        "deltas = [world.reset(), world.step(1, [])];"
        "turns = [answer_turn(p, n) for n, p in enumerate(deltas[1].presentations)];"
        "deltas.append(world.step(2, turns));"
        "print('\\n'.join(canonical_json(d) for d in deltas))"
    )
    world = make_world()
    in_process = [world.reset(), world.step(1, [])]
    in_process.append(world.step(2, [answer_turn(p, n) for n, p in enumerate(in_process[1].presentations)]))
    expected = [canonical_json(delta) for delta in in_process]
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=".")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().split("\n") == expected


def test_ticks_advance_one_at_a_time_within_the_horizon():
    world = make_world()
    world.reset()
    with pytest.raises(ValueError, match="one at a time"):
        world.step(2, [])
    world.step(1, [])
    horizon = make_header().scenario.horizon_ticks
    tick = 2
    while tick < horizon:
        world.step(tick, [])
        tick += 1
    with pytest.raises(ValueError, match="beyond the horizon"):
        world.step(horizon, [])


def test_step_refuses_turns_from_the_future():
    world = make_world()
    world.reset()
    first = world.step(1, [])
    turn = answer_turn(first.presentations[0], 0)
    future = turn.model_copy(
        update={"impression": turn.impression.model_copy(update={"tick": 5})}
    )
    with pytest.raises(ValueError, match="previous tick"):
        world.step(2, [future])


def test_module_functions_open_and_advance_a_single_live_world():
    forget()
    try:
        header = make_header()
        opening = reset(header)
        assert opening.tick == 0
        following = step(1, [])
        assert [p.impression.persona_id for p in following.presentations] == sorted(PERSONA_IDS)
    finally:
        forget()
