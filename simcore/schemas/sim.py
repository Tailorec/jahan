"""The simulation domain: stimuli, exposures, impressions, reactions, beliefs, memory and elicitation."""

from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .base import (
    FrozenDict,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PersonaId,
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
