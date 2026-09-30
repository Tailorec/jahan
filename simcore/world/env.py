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
from collections.abc import Callable

from simcore.schemas import (
    ActionKind,
    Channel,
    DroppedExposure,
    Exposure,
    ExposureDropped,
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
    wave_ticks,
)

from . import _ids, recsys, wom
from .clock import activated_personas, activation_probability
from .platform import Forum, ForumPreset, is_supported
from .store import Store


# A drop is recorded for a near miss: this many ranked candidates per budget place.
CANDIDATE_WINDOW_MULTIPLE = 3


class RecsysMode(StrEnum):
    """How the world ranks candidate stimuli: the control arm first, then the ranked modes."""

    RANDOM = "random"
    REDDIT_HOT = "reddit_hot"
    TWITTER = "twitter"
    TWHIN = "twhin"


# What the legacy single platform meant as channels: a feed or a forum study ran with word of
# mouth riding beside it, and the survey room ran alone. Explicit `channels` never consult this.
_PLATFORM_CHANNELS: dict[Channel, frozenset[Channel]] = {
    Channel.SURVEY_ROOM: frozenset(),
    Channel.SOCIAL_FEED: frozenset({Channel.SOCIAL_FEED, Channel.WOM}),
    Channel.FORUM: frozenset({Channel.FORUM, Channel.WOM}),
    Channel.WOM: frozenset({Channel.WOM}),
}


@dataclass(frozen=True)
class WorldConfig:
    """How this world behaves, chosen per scenario so mechanics stay study variables.

    Defaults run the survey-room baseline under the random control arm: every
    persona sees the stimulus alone, with no social signal and no ranking.
    """

    # The legacy single platform, kept so existing constructions keep meaning: it derives
    # `channels` when none are named explicitly (survey room → none, feed/forum → itself
    # with word of mouth riding beside it, as it always did). New studies name `channels`.
    platform: Channel = Channel.SURVEY_ROOM
    # Which channels spread information in this world. Explicit always wins over `platform`;
    # the world factory builds this from the scenario, never beside it (ADR 0048).
    channels: frozenset[Channel] | None = None
    recsys_mode: RecsysMode = RecsysMode.RANDOM
    forum_preset: ForumPreset = ForumPreset.REDDIT_GLOBAL
    # None inherits the scenario's exposure budget; the survey room always shows exactly one.
    exposure_budget: int | None = None
    # How attention falls down an impression: the first slot has the persona's full notice and
    # the last has `last_slot_attention` of it, spread evenly between, whatever the budget.
    # `CONTEXT.md` defines noticing as drawing any attention at all, so a study that wants
    # shown-but-unnoticed exposures raises `attention_floor`; by default everything shown is
    # noticed, and what fraction of a feed really goes unnoticed is an open modelling question.
    last_slot_attention: float = 0.5
    attention_floor: float = 0.0
    # How many ranked candidates count as having nearly reached a persona. A drop means a
    # stimulus the budget kept out, so only this window's near misses are recorded; ranking
    # still considers everything published. None is `CANDIDATE_WINDOW_MULTIPLE x` the budget.
    candidate_window: int | None = None
    # Activation: per-persona involvement is `involvement_default` unless named here.
    involvement_default: float = 1.0
    involvement: tuple[tuple[str, float], ...] = ()
    # The runner's per-tick plan scales activation here: degradation is a
    # different plan, never a mutated object the world learns a budget from.
    activation_rate: float = 1.0
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
    # Batch text embedder for stimulus arrival under the `twitter` mode. Called
    # at most once per stimulus text and cached by stimulus id, so ranking
    # never embeds; tests pass a fake, production the run's pinned embed model.
    embed_texts: Callable[[list[str]], list[list[float]]] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Coerce plain strings to their channels and modes, so scenario files read naturally."""
        object.__setattr__(self, "platform", Channel(self.platform))
        object.__setattr__(self, "recsys_mode", RecsysMode(self.recsys_mode))
        object.__setattr__(self, "forum_preset", ForumPreset(self.forum_preset))
        if self.channels is not None:
            named = frozenset(Channel(channel) for channel in self.channels)
            if Channel.SURVEY_ROOM in named:
                raise ValueError("the survey room is a wave's internal channel, never a study choice")
            object.__setattr__(self, "channels", named)

    def resolved_channels(self) -> frozenset[Channel]:
        """The channels spreading information here: the explicit set, else the legacy platform's."""
        if self.channels is not None:
            return self.channels
        # The legacy mapping keeps old constructions meaning what they always did: a feed or a
        # forum study ran with word of mouth riding beside it, and the survey room ran alone.
        return _PLATFORM_CHANNELS[self.platform]

    def involvement_for(self, persona_id: str) -> float:
        """This persona's involvement: its named value, else the study default."""
        return dict(self.involvement).get(persona_id, self.involvement_default)

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
        self._ties: dict[frozenset[str], float] = {}
        self._community_of: dict[str, str] = {}
        if population is not None and population.graph is not None:
            for edge in population.graph.edges:
                self._ties[frozenset((edge.u, edge.v))] = edge.weight
        if population is not None:
            for community in population.communities:
                for member in community.member_ids:
                    self._community_of[member] = community.community_id
        # Degree centralities from the generated graph, computed once here and
        # read by the `twhin` mode — never recomputed per tick.
        self._centralities: dict[str, float] = {}
        if population is not None and population.graph is not None and len(self._personas) > 1:
            degree: dict[str, int] = {persona_id: 0 for persona_id in self._personas}
            for edge in population.graph.edges:
                degree[edge.u] = degree.get(edge.u, 0) + 1
                degree[edge.v] = degree.get(edge.v, 0) + 1
            scale = len(self._personas) - 1
            self._centralities = {persona_id: count / scale for persona_id, count in degree.items()}
        # Stimulus vectors for the `twitter` mode, cached by stimulus id at
        # arrival and read by ranking — ranking itself never embeds.
        self._stimulus_vectors: dict[str, tuple[float, ...]] = {}
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

    @property
    def tick_unit(self) -> str:
        """The scenario's declared tick unit, travelling with the world into every delta's reading."""
        return self._scenario.tick_unit.value

    @property
    def horizon_ticks(self) -> int:
        """How many ticks this world runs before it ends."""
        return self._scenario.horizon_ticks

    # -- the port -----------------------------------------------------------------

    def reset(self) -> WorldDelta:
        """Open the world: publish the study's stimuli as the delta for tick zero.

        The delta also carries the tick-0 survey wave, so the baseline wave is taken after
        launch: every wave tick's answers reflect everything up to and including their tick.
        """
        if self._opened:
            raise ValueError("a world opens once; resume by replaying turns through a fresh instance")
        mode = self._config.recsys_mode
        if mode is RecsysMode.TWITTER and not self._config.profile_vectors:
            raise ValueError("the twitter mode reads profile embeddings from the manifest: none were carried in")
        if mode is RecsysMode.TWHIN and not self._centralities:
            raise ValueError("the twhin mode reads degree centralities from the generated graph: no graph was carried in")
        self._opened = True
        self._last_tick = 0
        published = self._publish_study_stimuli()
        return WorldDelta(
            tick=0,
            published=tuple(published),
            interventions=self._interventions_at(0),
            dropped=(),
            presentations=tuple(self._survey_presentations(0)),
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
        deliveries = self._wom_deliveries(tick, turns)
        presentations, dropped = self._presentations(tick, deliveries)
        delta = WorldDelta(
            tick=tick,
            published=tuple(published),
            interventions=self._interventions_at(tick),
            dropped=tuple(dropped),
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
        self._vectorize([stimulus.stimulus_id for stimulus in stimuli], [stimulus.text for stimulus in stimuli])
        return stimuli

    def _vectorize(self, stimulus_ids: list[str], texts: list[str]) -> None:
        """Cache one vector per new stimulus text for the `twitter` mode.

        Called at arrival — when stimuli are published — so ranking reads
        cached vectors and never embeds. Profile vectors are never embedded
        here at all: they arrive computed once at population build.
        """
        embed = self._config.embed_texts
        if embed is None or self._config.recsys_mode is not RecsysMode.TWITTER:
            return
        fresh = [(sid, text) for sid, text in zip(stimulus_ids, texts) if sid not in self._stimulus_vectors]
        if not fresh:
            return
        for sid, vector in zip([sid for sid, _ in fresh], embed([text for _, text in fresh])):
            self._stimulus_vectors[sid] = tuple(vector)

    def _interventions_at(self, tick: int) -> tuple[InterventionKind, ...]:
        """Every intervention scheduled at this tick: they compose, never overwrite."""
        return tuple(
            intervention.kind for intervention in self._scenario.interventions if intervention.tick == tick
        )

    def _ingest_turns(self, tick: int, turns: tuple[Turn, ...]) -> None:
        """Fold the previous tick's reactions into platform state.

        Counted actions become engagement rows visible from this tick onward;
        authoring actions publish persona stimuli through `_publish_from_turns`.
        An action its channel does not support is recorded as rejected and
        changes no state. A survey answer changes no platform state.
        """
        for turn in turns:
            action = turn.reaction.action
            if action is ActionKind.IGNORE:
                continue
            channel = turn.impression.channel
            if not is_supported(channel, action):
                self._store.record_rejection(
                    persona_id=turn.impression.persona_id,
                    action=action.value,
                    channel=channel.value,
                    tick=turn.impression.tick,
                    world_id=self._world_id,
                    written_tick=tick,
                )
                continue
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
            elif action is ActionKind.FOLLOW:
                # Following means following the author of the stimulus reacted to.
                followee = self._store.stimulus_author(subject)
                if followee is not None and followee != turn.impression.persona_id:
                    self._store.record_follow(
                        follower=turn.impression.persona_id,
                        followee=followee,
                        tick=turn.impression.tick,
                        world_id=self._world_id,
                        written_tick=tick,
                    )

    _AUTHORING = frozenset({ActionKind.POST, ActionKind.COMMENT, ActionKind.REPLY, ActionKind.QUOTE})

    def _publish_from_turns(self, tick: int, turns: tuple[Turn, ...]) -> list[Stimulus]:
        """Persona-authored stimuli for this tick: posts, comments, replies and quotes.

        Turns publish in persona order so stimulus identifiers are stable
        whatever order the runner hands turns in. What a persona authors this
        tick becomes visible from the next tick onward, never within this one.
        """
        ordered = sorted(
            turns,
            key=lambda turn: (
                turn.impression.persona_id,
                turn.reaction.subject_stimulus_id,
                turn.reaction.action.value,
            ),
        )
        stimuli: list[Stimulus] = []
        index = 0
        for turn in ordered:
            action = turn.reaction.action
            if action not in self._AUTHORING or not is_supported(turn.impression.channel, action):
                continue
            if turn.reaction.verbatim is None:
                continue
            if action in (ActionKind.COMMENT, ActionKind.REPLY):
                kind, parent = StimulusKind.PEER_REPLY, turn.reaction.subject_stimulus_id
            else:
                kind, parent = StimulusKind.PEER_POST, None
            stimulus = Stimulus(
                stimulus_id=_ids.stimulus_id(self._world_seed, tick, f"publish:{action.value}", index),
                tick=tick,
                author=turn.impression.persona_id,
                kind=kind,
                text=turn.reaction.verbatim,
                in_reply_to=parent,
            )
            index += 1
            self._store.record_stimulus(
                stimulus_id=stimulus.stimulus_id,
                tick=tick,
                author=stimulus.author,
                kind=stimulus.kind.value,
                text=stimulus.text,
                claim_id=None,
                parent_id=parent,
                world_id=self._world_id,
                written_tick=tick,
            )
            stimuli.append(stimulus)
        self._vectorize([stimulus.stimulus_id for stimulus in stimuli], [stimulus.text for stimulus in stimuli])
        return stimuli

    def _activated(self, tick: int) -> list[str]:
        """Personas taking a turn this tick: involvement × rhythm × the runner's plan, one seeded draw each."""
        overrides = dict(self._config.rhythm)
        scale = max(0.0, min(1.0, self._config.activation_rate))
        probabilities = {
            persona_id: activation_probability(
                self._config.involvement_for(persona_id), self.tick_unit, tick, overrides
            )
            * scale
            for persona_id in self._personas
        }
        return activated_personas(self._personas, probabilities, self._world_seed, tick)

    def _is_wave_tick(self, tick: int) -> bool:
        """Whether this tick surveys every persona: `{0, k, 2k, …} ∪ {horizon − 1}` (ADR 0048)."""
        return tick in wave_ticks(self._scenario.survey_every, self._scenario.horizon_ticks)

    def _presentations(
        self, tick: int, deliveries: dict[str, list[tuple[str, str, float]]]
    ) -> tuple[list[Presentation], list[DroppedExposure]]:
        """One presentation per activated persona on every ticked platform, plus what missed the budget.

        Channel presentations come first, then word of mouth, then the wave last, so a wave
        tick's answers reflect everything up to and including their own tick. Word-of-mouth
        deliveries ride a second impression on the wom channel — except when word of mouth
        is not ticked, and except in a world with no channels, which neither delivers nor
        sparks word of mouth, keeping the baseline the stimulus alone.
        """
        if self._concept_id is None:
            raise ValueError("presentations before the study stimuli were published")
        channels = self._config.resolved_channels()
        presentations: list[Presentation] = []
        dropped: list[DroppedExposure] = []
        if Channel.SOCIAL_FEED in channels:
            feed, feed_drops = self._feed_presentations(tick)
            presentations.extend(feed)
            dropped.extend(feed_drops)
        if Channel.FORUM in channels:
            forum, forum_drops = self._forum_presentations(tick)
            presentations.extend(forum)
            dropped.extend(forum_drops)
        if Channel.WOM in channels:
            extra, extra_drops = self._wom_presentations(tick, deliveries)
            presentations.extend(extra)
            dropped.extend(extra_drops)
        if self._is_wave_tick(tick):
            presentations.extend(self._survey_presentations(tick))
        return presentations, dropped

    def _wom_deliveries(
        self, tick: int, turns: tuple[Turn, ...]
    ) -> dict[str, list[tuple[str, str, float]]]:
        """Who is told what next: teller reactions become recipient exposures.

        Computed from this step's turns and delivered in this step's own
        presentations — the reaction was recorded an earlier tick, so a
        delivery never lands within the tick that produced it. The survey
        room's answers spark nothing.
        """
        deliveries: dict[str, list[tuple[str, str, float]]] = {}
        if Channel.WOM not in self._config.resolved_channels():
            return deliveries
        for turn in turns:
            if turn.impression.channel is Channel.SURVEY_ROOM:
                continue
            teller = turn.impression.persona_id
            sentiment = wom.sentiment_strength(turn.reaction)
            if sentiment < self._config.wom_sentiment_threshold:
                continue
            neighbours = {
                other: strength
                for pair, strength in self._ties.items()
                if teller in pair
                for other in (pair - {teller})
            }
            willing = {
                peer: tie
                for peer, tie in neighbours.items()
                if wom.wants_to_talk(
                    turn.reaction,
                    tie,
                    sentiment_threshold=self._config.wom_sentiment_threshold,
                    tie_threshold=self._config.wom_tie_threshold,
                )
            }
            targets = wom.select_targets(
                teller,
                willing,
                sentiment,
                world_seed=self._world_seed,
                tick=tick,
                sentiment_threshold=self._config.wom_sentiment_threshold,
                tie_threshold=self._config.wom_tie_threshold,
                cap=self._config.wom_cap_per_tick,
            )
            for peer in targets:
                deliveries.setdefault(peer, []).append(
                    (turn.reaction.subject_stimulus_id, teller, willing[peer])
                )
        return deliveries

    def _wom_presentations(
        self, tick: int, deliveries: dict[str, list[tuple[str, str, float]]]
    ) -> tuple[list[Presentation], list[DroppedExposure]]:
        """One wom-channel impression per told persona that is awake this tick."""
        awake = set(self._activated(tick))
        counts = self._store.counts_visible_at(tick)
        authors = {row["stimulus_id"]: row["author"] for row in self._store.stimuli_published_before(tick + 1)}
        budget = self._budget()
        presentations: list[Presentation] = []
        dropped: list[DroppedExposure] = []
        for recipient in sorted(deliveries):
            if recipient not in awake:
                continue
            # Two peers telling you about the same post is one thing heard, not two: an
            # impression holds each stimulus once, and the closest teller is the one whose
            # tie the view records.
            closest: dict[str, tuple[str, float]] = {}
            for subject, teller, tie in deliveries[recipient]:
                held = closest.get(subject)
                if held is None or tie > held[1]:
                    closest[subject] = (teller, tie)
            heard = [(subject, teller, tie) for subject, (teller, tie) in closest.items()]
            told = heard[:budget]
            exposures = tuple(
                Exposure(stimulus_id=subject, reason=ExposureReason.WOM, attention=self._attention_at(rank, len(told)))
                for rank, (subject, _, _) in enumerate(told)
            )
            impression = Impression(
                impression_id=_ids.impression_id(self._world_seed, tick, recipient, Channel.WOM.value),
                persona_id=recipient,
                channel=Channel.WOM,
                tick=tick,
                exposures=exposures,
            )
            contexts = {
                subject: self._context_for(
                    recipient, subject, authors.get(subject), counts,
                    tie_override=(tie, self._teller_shared(recipient, teller)), via=teller,
                )
                for subject, teller, tie in told
            }
            presentations.append(
                Presentation(impression=impression, view=View(impression_id=impression.impression_id, contexts=contexts))
            )
            for subject, _, _ in heard[budget:]:
                dropped.append(
                    DroppedExposure(
                        persona_id=recipient,
                        drop=ExposureDropped(
                            kind="exposure_dropped",
                            stimulus_id=subject,
                            channel=Channel.WOM,
                            reason="budget_exhausted",
                        ),
                    )
                )
        return presentations, dropped

    def _teller_shared(self, recipient: str, teller: str) -> bool | None:
        """Whether teller and told share a community — the relationship the wom view records."""
        if not self._community_of:
            return None
        recipient_community = self._community_of.get(recipient)
        teller_community = self._community_of.get(teller)
        if recipient_community is None or teller_community is None:
            return None
        return recipient_community == teller_community

    def _survey_presentations(self, tick: int) -> list[Presentation]:
        """The survey wave: every persona sees the concept stimulus alone — never gated by
        activation, so a change between waves is movement, not sampling.

        One exposure, on the survey room's internal channel, after the tick's channel
        presentations — so the wave reflects everything up to and including its own tick."""
        assert self._concept_id is not None
        presentations = []
        for persona_id in self._personas:
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

    _FEED_KINDS = frozenset({"concept", "claim_post", "peer_post", "peer_reply"})

    def _attention_at(self, rank: int, count: int) -> float:
        """How much of the persona's notice the stimulus at this rank drew.

        Every exposure used to be built with attention 1.0, so position carried no information
        and nothing shown was ever unnoticed — a case the glossary defines and the agent's
        guardrail depends on. The spread is relative to the impression, so a wider budget
        thins attention rather than pushing the last slot out of sight.
        """
        last = max(0.0, min(1.0, self._config.last_slot_attention))
        value = 1.0 if count <= 1 else 1.0 - (1.0 - last) * rank / (count - 1)
        if value < self._config.attention_floor:
            return 0.0
        return max(0.0, min(1.0, round(value, 4)))

    def _candidate_window(self) -> int:
        """How far down the ranking a miss is still recorded, never fewer than the budget.

        Every unshown stimulus was once recorded as dropped, so the trace grew with the
        corpus: four personas and twenty stimuli wrote 52 drops in a tick, and a real study
        would write millions no one reads. A drop is a near miss — what the budget kept out —
        so the window bounds what is recorded, and never what is shown.
        """
        budget = self._budget()
        if self._config.candidate_window is None:
            return budget * CANDIDATE_WINDOW_MULTIPLE
        return max(budget, self._config.candidate_window)

    def _budget(self) -> int:
        """Stimuli one persona can be shown per channel per tick.

        The scenario's budget is the ceiling — a partition showing more would
        not validate — and the study may tighten it, never loosen it. The
        survey room always shows exactly one.
        """
        scenario_budget = self._scenario.exposure_budget
        if self._config.exposure_budget is None:
            return scenario_budget
        return min(self._config.exposure_budget, scenario_budget)

    def _feed_presentations(self, tick: int) -> tuple[list[Presentation], list[DroppedExposure]]:
        """The social feed: ranked candidates grouped into one impression per persona.

        Everything a persona sees on the feed in one tick arrives as one
        impression — grouped, not flattened — and its view carries only public
        context: counts from earlier ticks, reply ancestry, tie strength and
        shared community with each author.
        """
        candidates = [
            row
            for row in self._store.stimuli_published_before(tick)
            if row["kind"] in self._FEED_KINDS
        ]
        budget = self._budget()
        counts = self._store.counts_visible_at(tick)
        authors = {row["stimulus_id"]: row["author"] for row in candidates}
        candidate_ids = [row["stimulus_id"] for row in candidates]
        reason = recsys.reason_for(self._config.recsys_mode.value)
        presentations: list[Presentation] = []
        dropped: list[DroppedExposure] = []
        for persona_id in self._activated(tick):
            ordered = self._rank_feed(persona_id, tick, candidates, counts)[: self._candidate_window()]
            shown = ordered[:budget]
            exposures = tuple(
                Exposure(stimulus_id=stimulus_id, reason=reason, attention=self._attention_at(rank, len(shown)))
                for rank, stimulus_id in enumerate(shown)
            )
            impression = Impression(
                impression_id=_ids.impression_id(self._world_seed, tick, persona_id, Channel.SOCIAL_FEED.value),
                persona_id=persona_id,
                channel=Channel.SOCIAL_FEED,
                tick=tick,
                exposures=exposures,
            )
            contexts = {
                stimulus_id: self._context_for(persona_id, stimulus_id, authors[stimulus_id], counts)
                for stimulus_id in shown
            }
            presentations.append(
                Presentation(impression=impression, view=View(impression_id=impression.impression_id, contexts=contexts))
            )
            missed = [stimulus_id for stimulus_id in ordered[budget:]]
            for stimulus_id in missed:
                dropped.append(
                    DroppedExposure(
                        persona_id=persona_id,
                        drop=ExposureDropped(
                            kind="exposure_dropped",
                            stimulus_id=stimulus_id,
                            channel=Channel.SOCIAL_FEED,
                            reason="budget_exhausted",
                        ),
                    )
                )
        return presentations, dropped

    def _rank_feed(
        self, persona_id: str, tick: int, rows: list[dict], counts: dict[str, dict[str, int]]
    ) -> list[str]:
        """Order feed candidates for one persona under the world's recsys mode."""
        ids = [row["stimulus_id"] for row in rows]
        mode = self._config.recsys_mode
        if mode is RecsysMode.RANDOM:
            return recsys.random_order(ids, self._world_seed, tick, persona_id)
        if mode is RecsysMode.REDDIT_HOT:
            return self._hot_rank(ids, rows, counts, feed_votes=True, tick=tick)
        if mode is RecsysMode.TWITTER:
            return recsys.interest_order(
                ids,
                self._config.profile_vector_for(persona_id),
                self._stimulus_vectors,
                self._world_seed,
                tick,
                persona_id,
            )
        if mode is RecsysMode.TWHIN:
            authors = {row["stimulus_id"]: row["author"] for row in rows}
            ages = {row["stimulus_id"]: tick - row["tick"] for row in rows}
            return recsys.hub_order(ids, self._centralities, authors, ages, self._world_seed, tick)
        raise ValueError(f"unknown recsys mode {mode}")

    def _hot_rank(
        self, ids: list[str], rows: list[dict], counts: dict[str, dict[str, int]], *, feed_votes: bool, tick: int
    ) -> list[str]:
        """Highest upstream hot score first. Votes reach the order only through that score.

        On the feed every visible approval counts toward the score; on the
        forum only votes do — likes cannot land there, so none can leak in.
        """
        ups: dict[str, int] = {}
        downs: dict[str, int] = {}
        published: dict[str, int] = {}
        for row in rows:
            seen = counts.get(row["stimulus_id"], {})
            ups[row["stimulus_id"]] = seen.get("upvotes", 0) + (0 if not feed_votes else seen.get("likes", 0))
            downs[row["stimulus_id"]] = seen.get("downvotes", 0)
            # When it was published, not how old it is: the upstream score rewards later
            # publication, and an age in its place ranks the oldest stimulus first.
            published[row["stimulus_id"]] = row["tick"]
        return recsys.hot_order(
            ids, ups, downs, published, self._world_seed, tick, recsys.UNIT_SECONDS[self.tick_unit]
        )

    def _scoped_rank(
        self, ids: list[str], rows: list[dict], counts: dict[str, dict[str, int]], *, tick: int
    ) -> list[str]:
        """Recency-and-agreement order for the scoped preset: consensus hardens slowly."""
        ups = {row["stimulus_id"]: counts.get(row["stimulus_id"], {}).get("upvotes", 0) for row in rows}
        downs = {row["stimulus_id"]: counts.get(row["stimulus_id"], {}).get("downvotes", 0) for row in rows}
        ages = {row["stimulus_id"]: tick - row["tick"] for row in rows}
        return recsys.scoped_order(ids, ups, downs, ages, self._world_seed, tick)

    def _context_for(
        self,
        viewer: str,
        stimulus_id: str,
        author: str | None,
        counts: dict[str, dict[str, int]],
        tie_override: tuple[float | None, bool | None] | None = None,
        via: str | None = None,
    ) -> StimulusContext:
        """The public context around one shown stimulus: counts from earlier ticks only,
        its reply ancestry, and the viewer's relationship to its author — nothing else.

        A word-of-mouth exposure overrides the relationship with the tie to the
        teller: the view shows who told you, not who authored it.
        """
        seen = counts.get(stimulus_id, {})
        tie_strength, shared_community = tie_override if tie_override is not None else self._relationship(viewer, author)
        return StimulusContext(
            likes=seen.get("likes", 0),
            reposts=seen.get("reposts", 0),
            replies=seen.get("replies", 0),
            upvotes=seen.get("upvotes", 0),
            downvotes=seen.get("downvotes", 0),
            ancestry=self._store.ancestry(stimulus_id),
            tie_strength=tie_strength,
            shared_community=shared_community,
            via_persona_id=via,
        )

    def _relationship(self, viewer: str, author: str | None) -> tuple[float | None, bool | None]:
        """Tie strength and shared community with an author: absent for the study's and the viewer's own."""
        if author is None or author == viewer:
            return None, None
        tie = self._ties.get(frozenset((viewer, author)), 0.0)
        if not self._community_of:
            return tie, None
        viewer_community = self._community_of.get(viewer)
        author_community = self._community_of.get(author)
        if viewer_community is None or author_community is None:
            return tie, None
        return tie, viewer_community == author_community

    def _forum_presentations(self, tick: int) -> tuple[list[Presentation], list[DroppedExposure]]:
        """The forum: threads any persona may reach under the global preset, ranked by hot score.

        Actions are create_post, reply and vote. Ranking comes from the
        preset — the global preset ranks by the upstream hot score — never
        from the feed's recsys mode, so the comparison stays a study variable.
        """
        forum = Forum(self._config.forum_preset)
        rows = [
            row
            for row in self._store.stimuli_published_before(tick)
            if row["kind"] in self._FEED_KINDS
        ]
        budget = self._budget()
        counts = self._store.counts_visible_at(tick)
        authors = {row["stimulus_id"]: row["author"] for row in rows}
        presentations: list[Presentation] = []
        dropped: list[DroppedExposure] = []
        for persona_id in self._activated(tick):
            threads = forum.threads_for(persona_id, rows, self._community_of)
            ids = [row["stimulus_id"] for row in threads]
            if forum.preset is ForumPreset.REDDIT_GLOBAL:
                ordered = self._hot_rank(ids, threads, counts, feed_votes=False, tick=tick)
            else:
                ordered = self._scoped_rank(ids, threads, counts, tick=tick)
            ordered = ordered[: self._candidate_window()]
            shown = ordered[:budget]
            exposures = tuple(
                Exposure(stimulus_id=stimulus_id, reason=ExposureReason.FORUM, attention=self._attention_at(rank, len(shown)))
                for rank, stimulus_id in enumerate(shown)
            )
            impression = Impression(
                impression_id=_ids.impression_id(self._world_seed, tick, persona_id, Channel.FORUM.value),
                persona_id=persona_id,
                channel=Channel.FORUM,
                tick=tick,
                exposures=exposures,
            )
            contexts = {
                stimulus_id: self._context_for(persona_id, stimulus_id, authors[stimulus_id], counts)
                for stimulus_id in shown
            }
            presentations.append(
                Presentation(impression=impression, view=View(impression_id=impression.impression_id, contexts=contexts))
            )
            for stimulus_id in ordered[budget:]:
                dropped.append(
                    DroppedExposure(
                        persona_id=persona_id,
                        drop=ExposureDropped(
                            kind="exposure_dropped",
                            stimulus_id=stimulus_id,
                            channel=Channel.FORUM,
                            reason="budget_exhausted",
                        ),
                    )
                )
        return presentations, dropped

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

    def rejected_actions(self) -> tuple[dict, ...]:
        """Actions channels did not support, oldest first — what personas tried, not an error."""
        return tuple(self._store.rejections())

    def degree_centrality(self, persona_id: str) -> float:
        """One persona's degree centrality, computed once when the world was built."""
        return self._centralities.get(persona_id, 0.0)

    def vectorized_stimuli(self) -> int:
        """How many stimuli carry cached vectors for the `twitter` mode."""
        return len(self._stimulus_vectors)

    def store_columns(self, table: str) -> list[str]:
        """Column names of a platform table, for asserting provenance travels with every row."""
        return self._store.columns(table)

    def provenance_complete(self) -> bool:
        """Every platform row names its world and the tick it was written at."""
        return self._store.provenance_complete()


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
