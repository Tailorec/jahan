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
    ULID_PATTERN,
    HashDigest,
    Identifier,
    NonNegativeInt,
    PersonaId,
    PopulationHash,
    SimBaseModel,
    StimulusId,
    canonical_hash,
)
from .brief import BriefPack
from .enums import Channel, DropReason, InferenceRole, InterventionKind, LifecyclePhase, ReflectionTrigger, RunStatus
from .errors import SchemaVersionError
from .run import PinnedModelId, RunConfig, Scenario, WorldId, check_scenario_against_brief, derive_world_id
from .sim import BeliefChange, Stimulus, Turn

EventId = Annotated[str, StringConstraints(pattern=rf"^ev-{ULID_PATTERN}$")]
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
    memory_ids: tuple[Identifier, ...] = ()


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

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        if isinstance(values.get("payload"), Mapping):
            raise TypeError("the unvalidated path takes payload models, not mappings; build the payload model first")
        return super().model_construct(_fields_set, **values)

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
    """Written once per partition: the contract it was written under, and everything that identifies its
    world. The world id is derived from the scenario, replicate seed and population, never stated."""

    contract_version: ContractVersion
    pack: BriefPack
    scenario: Scenario
    replicate_seed: NonNegativeInt
    population_hash: PopulationHash

    @model_validator(mode="after")
    def _scenario_tests_the_packed_brief(self) -> Self:
        check_scenario_against_brief(self.scenario, self.pack.brief)
        return self

    @computed_field
    @property
    def world_id(self) -> str:
        return derive_world_id(self.scenario, self.replicate_seed, self.population_hash)


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


def _check_claims(change: BeliefChange, claims: set[str], where: str) -> None:
    unknown = sorted(set(change.claim_credence) - claims)
    if unknown:
        raise ValueError(f"{where} moves credence in claims the brief does not make: {unknown}")


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
