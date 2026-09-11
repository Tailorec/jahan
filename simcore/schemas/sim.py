"""The simulation domain: stimuli, exposures, impressions, reactions, beliefs, memory and elicitation."""

from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .base import (
    FrozenDict,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PersonaId,
    SignedUnitInterval,
    SimBaseModel,
    StimulusId,
    UnitInterval,
    _ULID,
)
from .brief import ClaimId
from .enums import ActionKind, BeliefDim, Channel, StimulusKind
from .run import PinnedModelId

ImpressionId = Annotated[str, StringConstraints(pattern=rf"^im-{_ULID}$")]
ReactionId = Annotated[str, StringConstraints(pattern=rf"^rc-{_ULID}$")]


def _strictly_positive(mass: tuple[float, ...]) -> tuple[float, ...]:
    if any(value <= 0.0 for value in mass):
        raise ValueError("a response mass contains a zero, which the SSR softmax cannot emit")
    return mass


def _mass_sums_to_one(mass: tuple[float, ...]) -> tuple[float, ...]:
    total = sum(mass)
    if not 0.999 <= total <= 1.001:
        raise ValueError(f"a response mass must sum to one within 0.001, got {total}")
    return mass


PMF5 = Annotated[
    tuple[float, float, float, float, float],
    AfterValidator(_strictly_positive),
    AfterValidator(_mass_sums_to_one),
]

CHANNEL_EXPOSURE_BUDGETS = FrozenDict(
    {Channel.SURVEY_ROOM: 1, Channel.SOCIAL_FEED: 3, Channel.FORUM: 3, Channel.WOM: 3}
)


class Exposure(SimBaseModel):
    """One stimulus reaching one persona: why it got through and how much attention it drew."""

    stimulus_id: StimulusId
    reason: NonEmptyStr
    attention: UnitInterval
    seen: bool


class Impression(SimBaseModel):
    """Everything one persona sees on one channel in one tick; exposures are grouped, not flattened."""

    impression_id: ImpressionId
    persona_id: PersonaId
    channel: Channel
    tick: NonNegativeInt
    exposures: tuple[Exposure, ...]

    @model_validator(mode="after")
    def _within_the_channel_budget(self) -> Self:
        count = len(self.exposures)
        budget = CHANNEL_EXPOSURE_BUDGETS[self.channel]
        if not 1 <= count <= budget:
            raise ValueError(
                f"an impression on {self.channel.value} holds one to {budget} exposures, got {count}"
            )
        return self


class Stimulus(SimBaseModel):
    """Something a persona can be shown; a persona-authored stimulus carries an author."""

    stimulus_id: StimulusId
    tick: NonNegativeInt
    author: PersonaId | None = None
    kind: StimulusKind
    text: NonEmptyStr
    claim_id: ClaimId | None = None


class Beliefs(SimBaseModel):
    """What a persona currently holds: where they stand on each dimension and how much
    they credit each individual claim of the brief."""

    claim_ids: frozenset[ClaimId] = Field(min_length=1)
    dimensions: FrozenDict[BeliefDim, UnitInterval]
    claim_credence: FrozenDict[ClaimId, UnitInterval]

    @model_validator(mode="after")
    def _dimensions_are_the_closed_set(self) -> Self:
        missing = sorted(dimension.value for dimension in BeliefDim if dimension not in self.dimensions)
        if missing:
            raise ValueError(f"beliefs cover the closed dimension set; missing {missing}")
        return self

    @model_validator(mode="after")
    def _credence_keys_match_the_tracked_claims(self) -> Self:
        if set(self.claim_credence) != set(self.claim_ids):
            raise ValueError(
                f"credence keys must match the tracked claims exactly: "
                f"tracked {sorted(self.claim_ids)}, credence {sorted(self.claim_credence)}"
            )
        return self


class BeliefChange(SimBaseModel):
    """How a turn or reflection moved beliefs; only moved entries appear."""

    claim_ids: frozenset[ClaimId] = Field(min_length=1)
    dimensions: FrozenDict[BeliefDim, SignedUnitInterval] = FrozenDict({})
    claim_credence: FrozenDict[ClaimId, SignedUnitInterval] = FrozenDict({})

    @model_validator(mode="after")
    def _changed_keys_stay_within_the_closed_vocabulary(self) -> Self:
        unknown_claims = sorted(set(self.claim_credence) - set(self.claim_ids))
        if unknown_claims:
            raise ValueError(f"credence changed for untracked claims: {unknown_claims}")
        return self


class RetrievedMemory(SimBaseModel):
    """One remembered experience as retrieval returned it."""

    memory_id: Identifier
    tick: NonNegativeInt
    description: NonEmptyStr
    importance: UnitInterval
    relevance: UnitInterval


class MemoryView(SimBaseModel):
    """What memory retrieval returned for one turn; possibly nothing."""

    items: tuple[RetrievedMemory, ...]


class SsrResult(SimBaseModel):
    """The elicitation record: free text in, a response mass out, and every identifier
    needed to detect an anchor/response embedding-model mismatch from the record alone."""

    response_text: NonEmptyStr
    pmf: PMF5
    per_set_pmfs: tuple[PMF5, ...] = Field(min_length=1)
    construct_id: Identifier
    category: Identifier
    anchor_set_id: Identifier
    anchor_version: Identifier
    embed_model_id: PinnedModelId
    tau: Annotated[float, Field(gt=0.0)]


class Reaction(SimBaseModel):
    """What a persona produced from one impression: what they did and said, how their
    beliefs moved, and — when the turn asked purchase intent — the elicitation record."""

    reaction_id: ReactionId
    persona_id: PersonaId
    impression_id: ImpressionId
    subject_stimulus_id: StimulusId
    tick: NonNegativeInt
    action: ActionKind
    verbatim: NonEmptyStr
    belief_change: BeliefChange
    intent: SsrResult | None = None
