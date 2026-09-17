"""Shared builders for world boundary tests: headers, worlds and turns."""

from simcore.schemas import PartitionHeader, Presentation, Reaction, Turn
from simcore.world import World, WorldConfig
from tests.study_builders import partition_header_payload, ulid


def make_header(**overrides):
    """The representative partition header, valid against its pinned run config."""
    return PartitionHeader.model_validate(partition_header_payload(**overrides))


def make_world(config: WorldConfig | None = None, **overrides) -> World:
    """A fresh world over the representative header."""
    return World(make_header(**overrides), config=config)


def answer_turn(presentation: Presentation, n: int, action: str = "answer") -> Turn:
    """A turn reacting to one of this world's own presentations."""
    subject = presentation.impression.exposures[0].stimulus_id
    if action == "ignore":
        reaction = Reaction(
            reaction_id=f"rc-{ulid(900 + n)}", subject_stimulus_id=subject, action="ignore"
        )
    elif action == "like":
        reaction = Reaction(
            reaction_id=f"rc-{ulid(900 + n)}", subject_stimulus_id=subject, action="like"
        )
    else:
        reaction = Reaction(
            reaction_id=f"rc-{ulid(900 + n)}",
            subject_stimulus_id=subject,
            action="answer",
            verbatim="clear protein water after training, I would try it",
        )
    return Turn(impression=presentation.impression, view=presentation.view, reaction=reaction)


def drive(world: World, ticks, action: str = "answer"):
    """Drive a world through `ticks`, answering every presentation.

    Returns the deltas (opening first) and the turns keyed by the tick they
    were recorded at — the only two things a replay needs beside the header.
    """
    deltas = [world.reset()]
    turns_by_tick: dict[int, list] = {}
    counter = 0
    for tick in ticks:
        previous = turns_by_tick.get(tick - 1, [])
        delta = world.step(tick, previous)
        deltas.append(delta)
        turns = []
        for presentation in delta.presentations:
            turns.append(answer_turn(presentation, counter, action=action))
            counter += 1
        turns_by_tick[tick] = turns
    return deltas, turns_by_tick
