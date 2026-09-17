"""Shared builders for world boundary tests: headers, worlds and turns."""

from simcore.schemas import PartitionHeader, Population, Presentation, Reaction, Turn
from simcore.world import World, WorldConfig
from tests.study_builders import partition_header_payload, population_payload, ulid


def make_header(**overrides):
    """The representative partition header, valid against its pinned run config."""
    return PartitionHeader.model_validate(partition_header_payload(**overrides))


def make_population(**overrides):
    """The representative population, matching the representative header's manifest."""
    payload = population_payload()
    payload.update(overrides)
    return Population.model_validate(payload)


def make_world(
    config: WorldConfig | None = None, population: Population | None = None, **overrides
) -> World:
    """A fresh world over the representative header, optionally over its population."""
    return World(make_header(**overrides), population=population, config=config)


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


def act_turn(
    presentation: Presentation, n: int, action: str, verbatim: str | None = None, subject_id: str | None = None
) -> Turn:
    """A turn performing a platform action, on the given stimulus or the first exposure."""
    subject = subject_id or presentation.impression.exposures[0].stimulus_id
    reaction = Reaction(
        reaction_id=f"rc-{ulid(950 + n)}",
        subject_stimulus_id=subject,
        action=action,  # type: ignore[arg-type]
        verbatim=verbatim,
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
