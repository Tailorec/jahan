# Adapted from OASIS (https://github.com/camel-ai/oasis, Apache-2.0):
# `env.py` / `env_action.py` / `make.py` (PettingZoo-style loop). CAMEL model
# access is stripped; turns arrive as recorded trace types and the world never
# calls a model. This file keeps the upstream loop shape so quarterly OASIS
# diffs stay mechanical; the merge is at the interface — one port outward.

"""The world loop: `reset` opens a world at tick zero, `step` advances it one tick.

A step takes the previous tick's recorded turns and returns a `WorldDelta`
built from the trace's own record types: stimuli published, interventions
applied, exposures dropped, and one presentation per activated persona and
channel. The world assigns no event ids and no sequence numbers — the runner
is the partition's only writer — and no world state crosses the boundary: a
world resumes by `reset` and replaying its recorded turns.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from simcore.schemas import (
    ActionKind,
    Channel,
    Exposure,
    ExposureReason,
    Impression,
    InterventionKind,
    PartitionHeader,
    Population,
    Presentation,
    Stimulus,
    StimulusContext,
    StimulusKind,
    Turn,
    View,
    WorldDelta,
    derive_world_seed,
)

from . import _ids
from ._seeds import derive_int
from .store import Store


class RecsysMode(StrEnum):
    """How the world ranks candidate stimuli: the control arm first, then the ranked modes."""

    RANDOM = "random"
    REDDIT_HOT = "reddit_hot"
    TWITTER = "twitter"
    TWHIN = "twhin"


class ForumPreset(StrEnum):
    """The two dynamics of the one forum class: herding globally, slow hardening by community."""

    REDDIT_GLOBAL = "reddit_global"
    COMMUNITY_SCOPED = "community_scoped"


@dataclass(frozen=True)
class WorldConfig:
    """How this world behaves, chosen per scenario so mechanics stay study variables.

    Defaults run the survey-room baseline under the random control arm: every
    persona sees the stimulus alone, with no social signal and no ranking.
    """

    platform: Channel = Channel.SURVEY_ROOM
    recsys_mode: RecsysMode = RecsysMode.RANDOM
    forum_preset: ForumPreset = ForumPreset.REDDIT_GLOBAL
    # None inherits the scenario's exposure budget; the survey room always shows exactly one.
    exposure_budget: int | None = None
    # Activation: per-persona involvement is `involvement_default` unless named here.
    involvement_default: float = 1.0
    involvement: tuple[tuple[str, float], ...] = ()
    # Rhythm overrides per tick unit; absent units run flat at 1.0.
    rhythm: tuple[tuple[str, float], ...] = ()
    # Word of mouth gates and cap (defaults from the PRD).
    wom_sentiment_threshold: float = 0.6
    wom_tie_threshold: float = 0.3
    wom_cap_per_tick: int = 2
    # Profile vectors for the `twitter` mode, keyed by persona id; computed once
    # at population build and carried in, never recomputed per tick.
    profile_vectors: tuple[tuple[str, tuple[float, ...]], ...] = ()
    embedding_model_id: str | None = None

    def involvement_for(self, persona_id: str) -> float:
        """This persona's involvement: its named value, else the study default."""
        return dict(self.involvement).get(persona_id, self.involvement_default)

    def rhythm_for(self, tick_unit: str) -> float:
        """The rhythm multiplier for a tick unit: its override, else flat."""
        return dict(self.rhythm).get(tick_unit, 1.0)

    def profile_vector_for(self, persona_id: str) -> tuple[float, ...] | None:
        """This persona's profile vector for interest matching, if the study carried one."""
        return dict(self.profile_vectors).get(persona_id)


class World:
    """One world's environment mechanics and who sees what.

    Constructed per scenario over the population it runs against, then driven
    through `reset` once and `step` once per tick. Internal state (platform
    facts, counters, pending deliveries) lives in SQLite and never appears in
    a delta; resume replays recorded turns through a fresh instance.
    """

    def __init__(
        self,
        header: PartitionHeader,
        population: Population | None = None,
        config: WorldConfig | None = None,
        *,
        store_path: str | None = None,
    ) -> None:
        if population is not None and (
            population.manifest.population_hash != header.population.population_hash
        ):
            raise ValueError("the population's manifest hash is not the header's population")
        self._header = header
        self._population = population
        self._config = config or WorldConfig()
        self._scenario = header.scenario
        self._world_seed = derive_world_seed(header.replicate_seed, header.scenario.variant.variant_id)
        self._world_id = header.world_id
        members = (
            [persona.persona_id for persona in population.personas]
            if population is not None
            else list(header.population.persona_ids)
        )
        self._personas = sorted(set(members))
        self._store = Store(store_path)
        self._concept_id: str | None = None
        self._opened = False
        self._last_tick = -1

    @property
    def world_id(self) -> str:
        """This world's identity, derived from its scenario, replicate and population."""
        return self._world_id

    @property
    def world_seed(self) -> int:
        """The seed every draw in this world derives from."""
        return self._world_seed

    # -- the port -----------------------------------------------------------------

    def reset(self) -> WorldDelta:
        """Open the world: publish the study's stimuli as the delta for tick zero."""
        if self._opened:
            raise ValueError("a world opens once; resume by replaying turns through a fresh instance")
        self._opened = True
        self._last_tick = 0
        published = self._publish_study_stimuli()
        return WorldDelta(
            tick=0,
            published=tuple(published),
            interventions=self._interventions_at(0),
            dropped=(),
            presentations=(),
        )

    def step(self, tick: int, turns: list[Turn] | tuple[Turn, ...]) -> WorldDelta:
        """Advance to `tick` from the previous tick's recorded turns."""
        if not self._opened:
            raise ValueError("step before reset: open the world first")
        if tick != self._last_tick + 1:
            raise ValueError(f"ticks advance one at a time: last closed {self._last_tick}, asked {tick}")
        if tick >= self._scenario.horizon_ticks:
            raise ValueError(f"tick {tick} is beyond the horizon of {self._scenario.horizon_ticks}")
        turns = tuple(turns)
        for turn in turns:
            if turn.impression.tick >= tick:
                raise ValueError(
                    f"a step takes the previous tick's turns, but a turn from tick "
                    f"{turn.impression.tick} reached step {tick}"
                )
        self._ingest_turns(tick, turns)
        published = self._publish_from_turns(tick, turns)
        presentations = self._presentations(tick)
        delta = WorldDelta(
            tick=tick,
            published=tuple(published),
            interventions=self._interventions_at(tick),
            dropped=self._drops(tick, presentations),
            presentations=tuple(presentations),
        )
        self._last_tick = tick
        return delta

    # -- internals ------------------------------------------------------------------

    def _publish_study_stimuli(self) -> list[Stimulus]:
        """The brief's proposition as stimuli: the concept, then one post per claim."""
        brief = self._header.pack.brief
        stimuli = [
            Stimulus(
                stimulus_id=_ids.stimulus_id(self._world_seed, 0, "study", 0),
                tick=0,
                author=None,
                kind=StimulusKind.CONCEPT,
                text=brief.product.description,
            )
        ]
        for index, claim in enumerate(brief.claims, start=1):
            stimuli.append(
                Stimulus(
                    stimulus_id=_ids.stimulus_id(self._world_seed, 0, "study", index),
                    tick=0,
                    author=None,
                    kind=StimulusKind.CLAIM_POST,
                    text=claim.text,
                    claim_id=claim.id,
                )
            )
        for stimulus in stimuli:
            self._store.record_stimulus(
                stimulus_id=stimulus.stimulus_id,
                tick=0,
                author=None,
                kind=stimulus.kind.value,
                text=stimulus.text,
                claim_id=stimulus.claim_id,
                parent_id=None,
                world_id=self._world_id,
                written_tick=0,
            )
        self._concept_id = stimuli[0].stimulus_id
        return stimuli

    def _interventions_at(self, tick: int) -> tuple[InterventionKind, ...]:
        """Every intervention scheduled at this tick: they compose, never overwrite."""
        return tuple(
            intervention.kind for intervention in self._scenario.interventions if intervention.tick == tick
        )

    def _ingest_turns(self, tick: int, turns: tuple[Turn, ...]) -> None:
        """Fold the previous tick's reactions into platform state.

        Counted actions become engagement rows visible from this tick onward;
        authoring actions publish persona stimuli through `_publish_from_turns`.
        A survey answer changes no platform state.
        """
        for turn in turns:
            action = turn.reaction.action
            subject = turn.reaction.subject_stimulus_id
            if action in (ActionKind.LIKE, ActionKind.REPOST, ActionKind.QUOTE, ActionKind.UPVOTE, ActionKind.DOWNVOTE):
                self._store.record_engagement(
                    stimulus_id=subject,
                    action=action.value,
                    persona_id=turn.impression.persona_id,
                    tick=turn.impression.tick,
                    world_id=self._world_id,
                    written_tick=tick,
                )

    def _publish_from_turns(self, tick: int, turns: tuple[Turn, ...]) -> list[Stimulus]:
        """Persona-authored stimuli for this tick. The survey room authors none."""
        return []

    def _activated(self, tick: int) -> list[str]:
        """Personas taking a turn this tick. The survey baseline wakes everyone."""
        return list(self._personas)

    def _presentations(self, tick: int) -> list[Presentation]:
        """One presentation per activated persona on the survey channel."""
        if self._concept_id is None:
            raise ValueError("presentations before the study stimuli were published")
        presentations = []
        for persona_id in self._activated(tick):
            exposure = Exposure(stimulus_id=self._concept_id, reason=ExposureReason.INTEREST, attention=1.0)
            impression = Impression(
                impression_id=_ids.impression_id(
                    self._world_seed, tick, persona_id, Channel.SURVEY_ROOM.value
                ),
                persona_id=persona_id,
                channel=Channel.SURVEY_ROOM,
                tick=tick,
                exposures=(exposure,),
            )
            view = View(
                impression_id=impression.impression_id,
                contexts={self._concept_id: StimulusContext()},
            )
            presentations.append(Presentation(impression=impression, view=view))
        return presentations

    def _drops(self, tick: int, presentations: list[Presentation]) -> tuple:
        """Exposures withheld this tick. The survey room drops nothing."""
        return ()

    # -- introspection (for tests and replay; never part of a delta) ----------------

    def state_dump(self) -> str:
        """The canonical logical platform state, comparable across processes."""
        return self._store.dump()

    def checkpoint(self) -> bytes:
        """An internal snapshot that makes replay faster; never part of the contract.

        Restoring one must produce exactly what replaying without it produces —
        it changes speed, never output.
        """
        import pickle

        return pickle.dumps(
            {
                "last_tick": self._last_tick,
                "concept_id": self._concept_id,
                "store": self._store.export(),
            }
        )

    @classmethod
    def restore(
        cls,
        header: PartitionHeader,
        data: bytes,
        population: Population | None = None,
        config: WorldConfig | None = None,
    ) -> "World":
        """Rebuild a world from a checkpoint; continuing it replays identically."""
        import pickle

        snapshot = pickle.loads(data)  # noqa: S301
        world = cls(header, population=population, config=config)
        world._opened = True
        world._last_tick = snapshot["last_tick"]
        world._concept_id = snapshot["concept_id"]
        world._store.import_data(snapshot["store"])
        return world

    def concept_id(self) -> str:
        """The study's concept stimulus, the survey room's single exposure."""
        if self._concept_id is None:
            raise ValueError("the study stimuli are published by reset")
        return self._concept_id


_LIVE: dict[str, World] = {}


def reset(
    header: PartitionHeader,
    population: Population | None = None,
    config: WorldConfig | None = None,
) -> WorldDelta:
    """Open a world at tick zero and remember it for `step`."""
    world = World(header, population=population, config=config)
    delta = world.reset()
    _LIVE[world.world_id] = world
    return delta


def step(
    tick: int,
    turns: list[Turn] | tuple[Turn, ...],
    *,
    world_id: str | None = None,
) -> WorldDelta:
    """Advance the live world to `tick` from the previous tick's recorded turns."""
    if world_id is None:
        if len(_LIVE) != 1:
            raise ValueError("no single live world: pass world_id explicitly")
        world = next(iter(_LIVE.values()))
    else:
        world = _LIVE[world_id]
    return world.step(tick, tuple(turns))


def forget(world_id: str | None = None) -> None:
    """Drop remembered live worlds (tests and resume reset this between runs)."""
    if world_id is None:
        _LIVE.clear()
    else:
        _LIVE.pop(world_id, None)


__all__ = [
    "ForumPreset",
    "RecsysMode",
    "World",
    "WorldConfig",
    "forget",
    "reset",
    "step",
]
