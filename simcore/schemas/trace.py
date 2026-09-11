"""The trace domain: the append-only record — whole turns as single sources of truth, strict events,
self-verifying partitions, a version-aware read path, and the registry entry that pins a run for replay."""

import copy
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated, Any, Literal, NamedTuple, Self

from pydantic import Field, StringConstraints, computed_field, model_validator

from . import base
from .base import (
    EventId,
    HashDigest,
    Identifier,
    NonNegativeInt,
    PersonaId,
    SimBaseModel,
    StimulusId,
    canonical_hash,
)
from .brief import BriefPack
from .enums import ActionKind, Channel, DropReason, InferenceRole, InterventionKind, LifecyclePhase, ReflectionTrigger, RunStatus
from .errors import SchemaVersionError
from .population import Population, PopulationManifest
from .run import PinnedModelId, RunConfig, Scenario, WorldId, check_scenario_against_brief, derive_world_id
from .sim import BeliefChange, Stimulus, Turn, View

ContractVersion = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class StimulusPublished(SimBaseModel):
    kind: Literal["stimulus_published"]
    stimulus: Stimulus


class ExposureDropped(SimBaseModel):
    """A stimulus that could have reached the event's persona and did not."""

    kind: Literal["exposure_dropped"]
    stimulus_id: StimulusId
    channel: Channel
    reason: DropReason


class TurnRecorded(SimBaseModel):
    """One whole turn — the impression as shown, grouped, and the reaction to it. Context is never stored
    whole: only the template that rendered it and hashes of its parts and of the prompt."""

    kind: Literal["turn"]
    turn: Turn
    template_id: Identifier
    prompt_hash: HashDigest
    persona_block_hash: HashDigest
    # A remembered experience is an earlier turn or reflection of the same persona, cited by its event id.
    memory_ids: tuple[EventId, ...] = ()


class ReflectionRecorded(SimBaseModel):
    """The event's persona consolidating experience into revised beliefs."""

    kind: Literal["reflection"]
    trigger: ReflectionTrigger
    change: BeliefChange


class CostRecorded(SimBaseModel):
    kind: Literal["cost"]
    role: InferenceRole
    model_id: PinnedModelId
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cache_hit: bool
    cost: Annotated[float, Field(ge=0.0)]


class InterventionApplied(SimBaseModel):
    """The partition's scenario applying one of its interventions at the event's tick."""

    kind: Literal["intervention"]
    intervention_kind: InterventionKind


class LifecycleRecorded(SimBaseModel):
    kind: Literal["lifecycle"]
    phase: LifecyclePhase


TracePayload = Annotated[
    StimulusPublished
    | ExposureDropped
    | TurnRecorded
    | ReflectionRecorded
    | CostRecorded
    | InterventionApplied
    | LifecycleRecorded,
    Field(discriminator="kind"),
]

_PERSONA_EVENTS = frozenset({"exposure_dropped", "turn", "reflection"})
_WORLD_EVENTS = frozenset({"stimulus_published", "intervention", "lifecycle"})


class TraceEvent(SimBaseModel):
    """One append-only record. It carries no seed and no contract version: the partition header
    derives the world, the registry holds every seed, and the contract version is recorded once.

    This is the hottest write path in the engine: it may be built with `model_construct`, from payload
    models rather than raw mappings, and the same records are fully validated in continuous integration.
    """

    event_id: EventId
    world_id: WorldId
    tick: NonNegativeInt
    seq: NonNegativeInt
    persona_id: PersonaId | None = None
    payload: TracePayload

    @model_validator(mode="after")
    def _attributed_to_the_right_persona(self) -> Self:
        kind = self.payload.kind
        if kind in _PERSONA_EVENTS and self.persona_id is None:
            raise ValueError(f"a {kind} event belongs to a persona and must name it")
        if kind in _WORLD_EVENTS and self.persona_id is not None:
            raise ValueError(f"a {kind} event belongs to the world, not to a persona")
        if isinstance(self.payload, TurnRecorded):
            impression = self.payload.turn.impression
            if impression.persona_id != self.persona_id:
                raise ValueError(f"turn event for {self.persona_id} records an impression shown to {impression.persona_id}")
            if impression.tick != self.tick:
                raise ValueError(f"turn event at tick {self.tick} records an impression from tick {impression.tick}")
        if isinstance(self.payload, StimulusPublished) and self.payload.stimulus.tick != self.tick:
            raise ValueError(f"stimulus published at tick {self.tick} is dated tick {self.payload.stimulus.tick}")
        return self


class PartitionHeader(SimBaseModel):
    """Written once per partition: the contract it was written under, the run it belongs to, and everything
    that identifies its world. Every pin the run configuration states is verified here against the object it
    pins — the brief, the ontology, the population and its graph, the scenario and the replicate seed — and the
    world id is derived from them, never stated."""

    contract_version: ContractVersion
    config: RunConfig
    pack: BriefPack
    population: PopulationManifest
    scenario: Scenario
    replicate_seed: NonNegativeInt

    @model_validator(mode="after")
    def _run_pins_are_the_objects_carried(self) -> Self:
        config = self.config
        if canonical_hash(self.pack.brief) != config.brief_hash:
            raise ValueError("the run pins a different brief than this partition carries")
        if canonical_hash(self.pack.ontology) != config.ontology_hash:
            raise ValueError("the run pins a different ontology than this partition carries")
        if self.population.population_hash != config.population_hash:
            raise ValueError("the run pins a different population than this partition carries")
        if self.population.graph_hash != config.graph_hash:
            raise ValueError("the run pins a different social graph than this partition's population has")
        if canonical_hash(self.scenario) not in {canonical_hash(scenario) for scenario in config.scenarios}:
            raise ValueError("this partition's scenario is not one the run configures")
        if self.replicate_seed not in config.seeds:
            raise ValueError(f"replicate seed {self.replicate_seed} is not one of the run's seeds {list(config.seeds)}")
        check_scenario_against_brief(self.scenario, self.pack.brief)
        return self

    @computed_field
    @property
    def world_id(self) -> str:
        return derive_world_id(self.scenario, self.replicate_seed, self.population.population_hash)


class TracePartition(SimBaseModel):
    """One world's append-only record, checked as a whole. Events may be stored in any order —
    storage sorts by persona and tick — but in sequence order they must be gapless, never go back in
    time, and only reference stimuli published earlier, within the scenario and brief the header names."""

    header: PartitionHeader
    events: tuple[TraceEvent, ...]

    @property
    def in_sequence(self) -> tuple[TraceEvent, ...]:
        return tuple(sorted(self.events, key=lambda event: event.seq))

    @model_validator(mode="after")
    def _events_form_one_gapless_world_record(self) -> Self:
        world = self.header.world_id
        strangers = sorted({event.world_id for event in self.events} - {world})
        if strangers:
            raise ValueError(f"partition for world {world} holds events from other worlds: {strangers}")
        repeated = sorted(eid for eid, count in Counter(event.event_id for event in self.events).items() if count > 1)
        if repeated:
            raise ValueError(f"event ids repeated: {repeated}")
        sequence = [event.seq for event in self.in_sequence]
        if sequence != list(range(len(sequence))):
            raise ValueError("event sequence numbers must run from 0 without gaps or repeats; a gap is a lost event")
        return self

    @model_validator(mode="after")
    def _events_are_consistent_with_their_world(self) -> Self:
        scenario, brief = self.header.scenario, self.header.pack.brief
        claims = {claim.id for claim in brief.claims}
        scheduled = Counter((intervention.tick, intervention.kind) for intervention in scenario.interventions)
        published: set[str] = set()
        impressions: set[str] = set()
        reactions: set[str] = set()
        last_tick = 0
        for event in self.in_sequence:
            where = f"event {event.seq} ({event.payload.kind})"
            if event.tick < last_tick:
                raise ValueError(f"{where} goes back in time from tick {last_tick} to {event.tick}")
            if event.tick >= scenario.horizon_ticks:
                raise ValueError(f"{where} at tick {event.tick} is beyond the scenario horizon of {scenario.horizon_ticks}")
            last_tick = event.tick
            payload = event.payload
            if isinstance(payload, StimulusPublished):
                stimulus = payload.stimulus
                if stimulus.stimulus_id in published:
                    raise ValueError(f"{where} republishes {stimulus.stimulus_id}")
                if stimulus.in_reply_to is not None and stimulus.in_reply_to not in published:
                    raise ValueError(f"{where} replies to {stimulus.in_reply_to}, which was never published before it")
                if stimulus.claim_id is not None and stimulus.claim_id not in claims:
                    raise ValueError(f"{where} renders claim {stimulus.claim_id}, which the brief does not make")
                published.add(stimulus.stimulus_id)
            elif isinstance(payload, ExposureDropped):
                if payload.stimulus_id not in published:
                    raise ValueError(f"{where} drops {payload.stimulus_id}, which was never published before it")
            elif isinstance(payload, TurnRecorded):
                impression, reaction = payload.turn.impression, payload.turn.reaction
                unpublished = sorted(impression.stimulus_ids - published)
                if unpublished:
                    raise ValueError(f"{where} shows stimuli never published before it: {unpublished}")
                if impression.channel is not Channel.SURVEY_ROOM and len(impression.exposures) > scenario.exposure_budget:
                    raise ValueError(
                        f"{where} shows {len(impression.exposures)} stimuli, over the scenario's budget of {scenario.exposure_budget}"
                    )
                if impression.impression_id in impressions or reaction.reaction_id in reactions:
                    raise ValueError(f"{where} repeats impression {impression.impression_id} or reaction {reaction.reaction_id}")
                impressions.add(impression.impression_id)
                reactions.add(reaction.reaction_id)
                _check_claims(reaction.belief_change, claims, where)
            elif isinstance(payload, ReflectionRecorded):
                _check_claims(payload.change, claims, where)
            elif isinstance(payload, InterventionApplied):
                key = (event.tick, payload.intervention_kind)
                if scheduled[key] == 0:
                    raise ValueError(f"{where} applies a {payload.intervention_kind.value} the scenario does not schedule at tick {event.tick}")
                scheduled[key] -= 1
        return self


    @model_validator(mode="after")
    def _events_honour_the_run_and_its_population(self) -> Self:
        config, members = self.header.config, set(self.header.population.persona_ids)
        category = self.header.pack.brief.product.category
        lifecycle: LifecyclePhase | None = None
        remembered: dict[str, str] = {}
        for event in self.in_sequence:
            where = f"event {event.seq} ({event.payload.kind})"
            payload = event.payload
            if lifecycle is None and not isinstance(payload, LifecycleRecorded):
                raise ValueError(f"{where} precedes the world starting; a partition opens with a started event")
            if isinstance(payload, LifecycleRecorded):
                allowed = _LIFECYCLE_TRANSITIONS[lifecycle]
                if payload.phase not in allowed:
                    raise ValueError(f"{where} moves the world from {lifecycle.value if lifecycle else 'nothing'} to {payload.phase.value}")
                lifecycle = payload.phase
                continue
            if lifecycle is not LifecyclePhase.STARTED:
                raise ValueError(f"{where} is recorded while the world is {lifecycle.value}")
            if event.persona_id is not None and event.persona_id not in members:
                raise ValueError(f"{where} belongs to {event.persona_id}, who is not in this population")
            if isinstance(payload, StimulusPublished) and payload.stimulus.author is not None and payload.stimulus.author not in members:
                raise ValueError(f"{where} is authored by {payload.stimulus.author}, who is not in this population")
            if isinstance(payload, CostRecorded):
                pinned = getattr(config.pins, payload.role.value)
                if payload.model_id != pinned:
                    raise ValueError(f"{where} bills {payload.model_id} for {payload.role.value}, but the run pins {pinned}")
            if isinstance(payload, TurnRecorded):
                if payload.template_id not in config.template_hashes:
                    raise ValueError(f"{where} renders template {payload.template_id!r}, which the run does not pin")
                for memory in payload.memory_ids:
                    if remembered.get(memory) != event.persona_id:
                        raise ValueError(f"{where} recalls {memory}, which is not an earlier turn or reflection of {event.persona_id}")
                intent = payload.turn.reaction.intent
                if intent is not None:
                    if intent.embed_model_id != config.pins.embed:
                        raise ValueError(f"{where} elicited with {intent.embed_model_id}, but the run pins {config.pins.embed} for every embedding")
                    if intent.anchor_set_id not in config.anchor_set_hashes:
                        raise ValueError(f"{where} scored against anchor set {intent.anchor_set_id!r}, which the run does not pin")
                    if intent.category != category:
                        raise ValueError(f"{where} scored against {intent.category!r} anchors for a {category!r} brief")
            if isinstance(payload, (TurnRecorded, ReflectionRecorded)):
                remembered[event.event_id] = event.persona_id
        if lifecycle is None:
            raise ValueError("a partition opens with a started event")
        return self


    # Runs after every other check: a view is verified only once the events it describes are known to be sound.
    @model_validator(mode="after")
    def _views_show_what_was_visible(self) -> Self:
        authors: dict[str, str | None] = {}
        parents: dict[str, str | None] = {}
        visible: dict[str, Counter[str]] = {}
        pending: dict[str, Counter[str]] = {}
        current_tick = 0
        for event in self.in_sequence:
            if event.tick > current_tick:
                for stimulus_id, counts in pending.items():
                    visible.setdefault(stimulus_id, Counter()).update(counts)
                pending, current_tick = {}, event.tick
            payload = event.payload
            if isinstance(payload, StimulusPublished):
                stimulus = payload.stimulus
                authors[stimulus.stimulus_id] = stimulus.author
                parents[stimulus.stimulus_id] = stimulus.in_reply_to
                if stimulus.in_reply_to is not None:
                    pending.setdefault(stimulus.in_reply_to, Counter())["replies"] += 1
            elif isinstance(payload, TurnRecorded):
                where = f"event {event.seq} (turn)"
                turn = payload.turn
                _check_view(turn.view, turn.impression.persona_id, authors, parents, visible, where)
                counted = _ENGAGEMENT.get(turn.reaction.action)
                if counted is not None:
                    pending.setdefault(turn.reaction.subject_stimulus_id, Counter())[counted] += 1
        return self


# Which count a reaction adds to the stimulus it is about; reposts count quotes too.
_ENGAGEMENT: dict[ActionKind, str] = {
    ActionKind.LIKE: "likes",
    ActionKind.REPOST: "reposts",
    ActionKind.QUOTE: "reposts",
    ActionKind.UPVOTE: "upvotes",
    ActionKind.DOWNVOTE: "downvotes",
}
_COUNTS = ("likes", "reposts", "replies", "upvotes", "downvotes")


def _check_view(
    view: View,
    viewer: str,
    authors: Mapping[str, str | None],
    parents: Mapping[str, str | None],
    visible: Mapping[str, Counter[str]],
    where: str,
) -> None:
    """A view must show exactly what was visible: engagement from earlier ticks, the stimulus's reply chain,
    and an author relationship only where one can exist."""
    for stimulus_id, context in view.contexts.items():
        seen = visible.get(stimulus_id, Counter())
        for name in _COUNTS:
            if getattr(context, name) != seen[name]:
                raise ValueError(
                    f"{where} shows {getattr(context, name)} {name} on {stimulus_id}, but {seen[name]} were visible from earlier ticks"
                )
        chain, parent = [], parents.get(stimulus_id)
        while parent is not None:
            chain.append(parent)
            parent = parents.get(parent)
        if list(context.ancestry) != chain:
            raise ValueError(f"{where} shows ancestry {list(context.ancestry)} for {stimulus_id}, but its reply chain is {chain}")
        author = authors.get(stimulus_id)
        if author is None or author == viewer:
            if context.tie_strength is not None or context.shared_community is not None:
                whose = "the study's" if author is None else "the viewer's own"
                raise ValueError(f"{where} records an author relationship for {stimulus_id}, which is {whose}")
        elif context.tie_strength is None:
            raise ValueError(f"{where} records no tie strength to {author}, the author of {stimulus_id}")


_LIFECYCLE_TRANSITIONS: dict[LifecyclePhase | None, frozenset[LifecyclePhase]] = {
    None: frozenset({LifecyclePhase.STARTED}),
    LifecyclePhase.STARTED: frozenset({LifecyclePhase.PAUSED, LifecyclePhase.COMPLETED}),
    LifecyclePhase.PAUSED: frozenset({LifecyclePhase.STARTED}),
    LifecyclePhase.COMPLETED: frozenset(),
}


def _check_claims(change: BeliefChange, claims: set[str], where: str) -> None:
    unknown = sorted(set(change.claim_credence) - claims)
    if unknown:
        raise ValueError(f"{where} moves credence in claims the brief does not make: {unknown}")


class WorldRecord(SimBaseModel):
    """A world's partition joined with the population it ran over. A partition carries only the population's
    manifest, so this is where a view's recorded ties and communities meet the real social graph."""

    population: Population
    partition: TracePartition

    @model_validator(mode="after")
    def _partition_ran_over_this_population(self) -> Self:
        if self.partition.header.population != self.population.manifest:
            raise ValueError("the partition's population manifest is not this population's")
        return self

    @model_validator(mode="after")
    def _views_record_the_real_ties_and_communities(self) -> Self:
        graph = self.population.graph
        ties = {frozenset((edge.u, edge.v)): edge.weight for edge in (graph.edges if graph is not None else ())}
        community_of = {member: community.community_id for community in self.population.communities for member in community.member_ids}
        authors: dict[str, str | None] = {}
        for event in self.partition.in_sequence:
            payload = event.payload
            if isinstance(payload, StimulusPublished):
                authors[payload.stimulus.stimulus_id] = payload.stimulus.author
                continue
            if not isinstance(payload, TurnRecorded):
                continue
            viewer = payload.turn.impression.persona_id
            for stimulus_id, context in payload.turn.view.contexts.items():
                author = authors.get(stimulus_id)
                if author is None or author == viewer:
                    continue
                tie = ties.get(frozenset((viewer, author)), 0.0)
                if context.tie_strength != tie:
                    raise ValueError(
                        f"event {event.seq} records tie strength {context.tie_strength} between {viewer} and {author}, but the graph has {tie}"
                    )
                shared = community_of.get(viewer) == community_of.get(author) if community_of else None
                if context.shared_community != shared:
                    expected = "no communities" if shared is None else ("a shared community" if shared else "different communities")
                    raise ValueError(
                        f"event {event.seq} records shared community {context.shared_community} for {viewer} and {author}, but the population has {expected}"
                    )
        return self


class ContractMigration(NamedTuple):
    """Rewrites a raw partition from the shape before `introduced_in` to the shape of `introduced_in`."""

    introduced_in: str
    migrate: Callable[[dict[str, Any]], dict[str, Any]]


# Contract 1.0.0 is the first released contract, so no migration exists yet. Each later contract that
# changes the partition's shape registers the step that rewrites the previous shape into its own.
CONTRACT_MIGRATIONS: tuple[ContractMigration, ...] = ()


def _parse_contract_version(text: Any) -> tuple[int, int, int]:
    if not isinstance(text, str) or not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise SchemaVersionError(f"not a contract version: {text!r}")
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def read_partition(
    data: Mapping[str, Any],
    *,
    engine_version: str | None = None,
    migrations: Iterable[ContractMigration] = CONTRACT_MIGRATIONS,
) -> TracePartition:
    """The read path: a partition written under an earlier contract loads under a later one by applying,
    in order, every registered migration newer than the contract it was written under. A partition from a
    newer contract than this engine is refused rather than guessed at. The result is a strict partition;
    nothing is ever written back through this path, so the writer never sees a legacy shape."""
    engine = _parse_contract_version(engine_version or base.SCHEMA_VERSION)
    header = data.get("header") if isinstance(data, Mapping) else None
    written_text = header.get("contract_version") if isinstance(header, Mapping) else None
    written = _parse_contract_version(written_text)
    if written > engine:
        raise SchemaVersionError(
            f"partition written under contract {written_text}, newer than this engine's {engine_version or base.SCHEMA_VERSION}"
        )
    raw = copy.deepcopy(dict(data))
    for step in sorted(migrations, key=lambda step: _parse_contract_version(step.introduced_in)):
        if written < _parse_contract_version(step.introduced_in) <= engine:
            raw = step.migrate(raw)
    return TracePartition.model_validate(raw)


class RunRegistryEntry(SimBaseModel):
    """Everything needed to reproduce a run. The configuration carries every hash, seed, model pin,
    template and anchor set; the config hash and world ids are derived from it, never stated."""

    config: RunConfig
    contract_version: ContractVersion
    status: RunStatus

    @computed_field
    @property
    def config_hash(self) -> str:
        return canonical_hash(self.config, schema_version=self.contract_version)

    @computed_field
    @property
    def world_ids(self) -> tuple[str, ...]:
        return tuple(
            derive_world_id(scenario, seed, self.config.population_hash)
            for scenario in self.config.scenarios
            for seed in self.config.seeds
        )
