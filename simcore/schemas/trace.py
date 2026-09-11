"""The trace domain: the append-only record's contract — typed payloads over eleven kinds,
strict events, partition versioning with a lenient read path, and the replay-pinning registry."""

from collections.abc import Iterable
from typing import Annotated, Any, Literal, Mapping

from pydantic import Field, StringConstraints

from .base import (
    BriefHash,
    ConfigHash,
    HashDigest,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    OntologyHash,
    PersonaId,
    PopulationHash,
    SCHEMA_VERSION,
    SimBaseModel,
    _ULID,
)
from .enums import InferenceRole, InterventionKind, LifecyclePhase, ReflectionTrigger, RunStatus
from .run import ModelPins, PinnedModelId, RunId, VariantId, WorldId
from .sim import (
    BeliefChange,
    Exposure,
    ImpressionId,
    Reaction,
    ReactionId,
    SsrResult,
    Stimulus,
)

EventId = Annotated[str, StringConstraints(pattern=rf"^ev-{_ULID}$")]
ContractVersion = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class StimulusPublished(SimBaseModel):
    kind: Literal["stimulus_published"]
    stimulus: Stimulus


class ExposureRecorded(SimBaseModel):
    kind: Literal["exposure"]
    persona_id: PersonaId
    exposure: Exposure


class ExposureDropped(SimBaseModel):
    kind: Literal["exposure_dropped"]
    persona_id: PersonaId
    stimulus_id: Identifier
    reason: NonEmptyStr


class TurnRecorded(SimBaseModel):
    """One persona reacting to one impression; the unit of simulation and of cost.

    Context is never stored whole — only hashes of its parts and of the prompt.
    """

    kind: Literal["turn"]
    persona_id: PersonaId
    impression_id: ImpressionId
    reaction_id: ReactionId
    prompt_hash: HashDigest
    persona_block_hash: HashDigest
    memory_ids: tuple[Identifier, ...] = ()


class ReactionRecorded(SimBaseModel):
    kind: Literal["reaction"]
    reaction: Reaction


class BeliefDeltaRecorded(SimBaseModel):
    kind: Literal["belief_delta"]
    persona_id: PersonaId
    change: BeliefChange
    trigger: ReflectionTrigger


class ReflectionRecorded(SimBaseModel):
    kind: Literal["reflection"]
    persona_id: PersonaId
    trigger: ReflectionTrigger


class SsrRecorded(SimBaseModel):
    kind: Literal["ssr"]
    result: SsrResult


class CostRecorded(SimBaseModel):
    kind: Literal["cost"]
    role: InferenceRole
    model_id: PinnedModelId
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cache_hit: bool
    cost: Annotated[float, Field(ge=0.0)]


class InterventionApplied(SimBaseModel):
    kind: Literal["intervention"]
    variant_id: VariantId
    intervention_kind: InterventionKind


class LifecycleRecorded(SimBaseModel):
    kind: Literal["lifecycle"]
    phase: LifecyclePhase


TracePayload = Annotated[
    StimulusPublished
    | ExposureRecorded
    | ExposureDropped
    | TurnRecorded
    | ReactionRecorded
    | BeliefDeltaRecorded
    | ReflectionRecorded
    | SsrRecorded
    | CostRecorded
    | InterventionApplied
    | LifecycleRecorded,
    Field(discriminator="kind"),
]


class TraceEvent(SimBaseModel):
    """One append-only record. It carries no seed and no contract version: the world id
    resolves the world, the registry holds every seed, and the contract version is a
    constant recorded once per partition."""

    event_id: EventId
    world_id: WorldId
    tick: NonNegativeInt
    agent_id: PersonaId | None = None
    seq: NonNegativeInt
    payload: TracePayload


class PartitionHeader(SimBaseModel):
    """The metadata written once per partition; the contract version travels here, not per event."""

    contract_version: ContractVersion
    world_id: WorldId


class RunRegistryEntry(SimBaseModel):
    """Everything needed to reproduce a run: every hash, every seed, every model pin."""

    run_id: RunId
    contract_version: ContractVersion
    config_hash: ConfigHash
    brief_hash: BriefHash
    ontology_hash: OntologyHash
    population_hash: PopulationHash
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    pins: ModelPins
    world_ids: tuple[WorldId, ...] = Field(min_length=1)
    status: RunStatus


_FIELDS_REMOVED_BY_LATER_CONTRACTS = frozenset({"seed"})


def read_events_lenient(
    events: Iterable[Mapping[str, Any]], contract_version: str
) -> tuple[TraceEvent, ...]:
    """The lenient read path: a partition written under an earlier contract loads under a
    later one. Fields removed by later contracts are dropped, never interpreted; the strict
    write path refuses them. This path reads — it is never used to write."""
    if contract_version != SCHEMA_VERSION:
        events = (
            {key: value for key, value in event.items() if key not in _FIELDS_REMOVED_BY_LATER_CONTRACTS}
            for event in events
        )
    return tuple(TraceEvent.model_validate(event) for event in events)
