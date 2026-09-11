"""The simulation domain: stimuli, exposures, impressions, reactions, turns, beliefs, memory and elicitation."""

from collections import Counter
from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, computed_field, model_validator

from .base import (
    ULID_PATTERN,
    FrozenDict,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PersonaId,
    SignedUnitInterval,
    SimBaseModel,
    StimulusId,
    UnitInterval,
)
from .brief import ClaimId
from .enums import ActionKind, BeliefDim, Channel, ExposureReason, StimulusKind
from .run import PinnedModelId

ImpressionId = Annotated[str, StringConstraints(pattern=rf"^im-{ULID_PATTERN}$")]
ReactionId = Annotated[str, StringConstraints(pattern=rf"^rc-{ULID_PATTERN}$")]

# The elicitation method averages several anchor reference sets; rank stability across them is its acceptance test.
MIN_REFERENCE_SETS = 6


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


class Exposure(SimBaseModel):
    """One stimulus shown to one persona: why it got through and how much attention it drew.

    An exposure can be shown without being noticed; noticing is attention above zero.
    """

    stimulus_id: StimulusId
    reason: ExposureReason
    attention: UnitInterval

    @computed_field
    @property
    def seen(self) -> bool:
        return self.attention > 0.0


class Impression(SimBaseModel):
    """Everything one persona is shown on one channel in one tick; exposures are grouped, not flattened.

    A survey room impression holds exactly one exposure. Other channels are bounded by the
    scenario's exposure budget, checked where the impression meets its scenario.
    """

    impression_id: ImpressionId
    persona_id: PersonaId
    channel: Channel
    tick: NonNegativeInt
    exposures: tuple[Exposure, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _survey_room_shows_one_stimulus(self) -> Self:
        if self.channel is Channel.SURVEY_ROOM and len(self.exposures) != 1:
            raise ValueError(f"a survey room impression holds exactly one exposure, got {len(self.exposures)}")
        return self

    @model_validator(mode="after")
    def _each_stimulus_shown_once(self) -> Self:
        repeated = sorted(sid for sid, count in Counter(e.stimulus_id for e in self.exposures).items() if count > 1)
        if repeated:
            raise ValueError(f"stimuli shown more than once in one impression: {repeated}")
        return self

    @property
    def stimulus_ids(self) -> frozenset[str]:
        return frozenset(exposure.stimulus_id for exposure in self.exposures)


_STUDY_AUTHORED = frozenset({StimulusKind.CONCEPT, StimulusKind.CLAIM_POST})


class Stimulus(SimBaseModel):
    """Something a persona can be shown. Study-authored kinds carry no author; persona-authored kinds must."""

    stimulus_id: StimulusId
    tick: NonNegativeInt
    author: PersonaId | None = None
    kind: StimulusKind
    text: NonEmptyStr
    claim_id: ClaimId | None = None
    in_reply_to: StimulusId | None = None

    @model_validator(mode="after")
    def _authorship_matches_kind(self) -> Self:
        study_authored = self.kind in _STUDY_AUTHORED
        if study_authored and self.author is not None:
            raise ValueError(f"a {self.kind.value} is authored by the study and carries no persona author")
        if not study_authored and self.author is None:
            raise ValueError(f"a {self.kind.value} is authored by a persona and must name its author")
        return self

    @model_validator(mode="after")
    def _references_match_kind(self) -> Self:
        if self.kind is StimulusKind.CLAIM_POST and self.claim_id is None:
            raise ValueError("a claim post must name the claim it renders")
        if (self.kind is StimulusKind.PEER_REPLY) != (self.in_reply_to is not None):
            raise ValueError("a peer reply, and only a peer reply, names the stimulus it replies to")
        if self.in_reply_to == self.stimulus_id:
            raise ValueError("a stimulus cannot reply to itself")
        return self


class Beliefs(SimBaseModel):
    """What a persona currently holds: every belief dimension, and credence in each claim of the brief.

    Which claims must appear is the brief's to say; it is checked where beliefs meet the brief.
    """

    dimensions: FrozenDict[BeliefDim, UnitInterval]
    claim_credence: FrozenDict[ClaimId, UnitInterval]

    @model_validator(mode="after")
    def _dimensions_are_the_closed_set(self) -> Self:
        missing = sorted(dimension.value for dimension in BeliefDim if dimension not in self.dimensions)
        if missing:
            raise ValueError(f"beliefs cover the closed dimension set; missing {missing}")
        return self

    @model_validator(mode="after")
    def _credence_is_held_for_some_claim(self) -> Self:
        if not self.claim_credence:
            raise ValueError("beliefs hold credence for the brief's claims, and a brief makes at least one")
        return self


class BeliefChange(SimBaseModel):
    """How a turn or reflection moved beliefs; only moved entries appear."""

    dimensions: FrozenDict[BeliefDim, SignedUnitInterval] = FrozenDict({})
    claim_credence: FrozenDict[ClaimId, SignedUnitInterval] = FrozenDict({})


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

    @model_validator(mode="after")
    def _each_memory_once(self) -> Self:
        repeated = sorted(mid for mid, count in Counter(item.memory_id for item in self.items).items() if count > 1)
        if repeated:
            raise ValueError(f"memories retrieved more than once: {repeated}")
        return self


class SsrResult(SimBaseModel):
    """The elicitation record: free text in, one response mass per anchor reference set, and every
    identifier needed to detect an anchor/response embedding-model mismatch from the record alone.
    The headline mass is computed as the mean of the per-set masses, so it cannot disagree with them."""

    response_text: NonEmptyStr
    per_set_pmfs: tuple[PMF5, ...] = Field(min_length=MIN_REFERENCE_SETS)
    construct_id: Identifier
    category: Identifier
    anchor_set_id: Identifier
    anchor_version: Identifier
    embed_model_id: PinnedModelId
    tau: Annotated[float, Field(gt=0.0)]

    @computed_field
    @property
    def pmf(self) -> tuple[float, float, float, float, float]:
        sets = len(self.per_set_pmfs)
        return tuple(sum(mass[point] for mass in self.per_set_pmfs) / sets for point in range(5))


_TEXT_ACTIONS = frozenset(
    {ActionKind.ANSWER, ActionKind.POST, ActionKind.COMMENT, ActionKind.REPLY, ActionKind.QUOTE, ActionKind.COMPLAIN, ActionKind.ASK_PEER}
)


class Reaction(SimBaseModel):
    """What a persona produced from an impression: what they did and said, how their beliefs moved,
    which stimulus they were responding to, and — when asked purchase intent — the elicitation record.

    Whose reaction it is, and when, belongs to the impression; a reaction travels inside its turn."""

    reaction_id: ReactionId
    subject_stimulus_id: StimulusId
    action: ActionKind
    verbatim: NonEmptyStr | None = None
    belief_change: BeliefChange = BeliefChange()
    intent: SsrResult | None = None

    @model_validator(mode="after")
    def _verbatim_matches_action(self) -> Self:
        if self.action in _TEXT_ACTIONS and self.verbatim is None:
            raise ValueError(f"a {self.action.value} produces text, so it needs a verbatim")
        if self.action is ActionKind.IGNORE and (self.verbatim is not None or self.intent is not None):
            raise ValueError("an ignored impression produces neither a verbatim nor an elicitation")
        return self


class StimulusContext(SimBaseModel):
    """The public context around one shown stimulus: the engagement counts beside it, its reply
    ancestry from nearest parent to root, and the viewer's relationship to its author.

    Reposts count quotes too — both reshare. Counts include only engagement from earlier ticks. Tie
    strength and shared community are absent for study-authored stimuli and the viewer's own; shared
    community says only whether the two share one, never which. No other persona's attributes,
    beliefs or private reactions appear here, and no aggregate outcome — a view is what one persona
    can see, never what the study knows.
    """

    likes: NonNegativeInt = 0
    reposts: NonNegativeInt = 0
    replies: NonNegativeInt = 0
    upvotes: NonNegativeInt = 0
    downvotes: NonNegativeInt = 0
    ancestry: tuple[StimulusId, ...] = ()
    tie_strength: UnitInterval | None = None
    shared_community: bool | None = None

    @model_validator(mode="after")
    def _ancestry_has_no_cycles(self) -> Self:
        if len(set(self.ancestry)) != len(self.ancestry):
            raise ValueError(f"a reply ancestry cannot visit a stimulus twice: {list(self.ancestry)}")
        return self


class View(SimBaseModel):
    """The public context around everything one persona is shown: one entry per stimulus of
    its impression. Social proof only works through what is visible, so this is the whole of it."""

    impression_id: ImpressionId
    contexts: FrozenDict[StimulusId, StimulusContext]

    @model_validator(mode="after")
    def _covers_something(self) -> Self:
        if not self.contexts:
            raise ValueError("a view covers the stimuli of an impression, and an impression shows at least one")
        return self


class Turn(SimBaseModel):
    """One persona reacting to one impression; the unit of simulation and of cost. The view
    it was shown travels with the turn, so social proof is part of the record."""

    impression: Impression
    view: View
    reaction: Reaction

    @model_validator(mode="after")
    def _view_matches_the_impression(self) -> Self:
        if self.view.impression_id != self.impression.impression_id:
            raise ValueError(
                f"view names impression {self.view.impression_id}, but the turn shows {self.impression.impression_id}"
            )
        shown = {exposure.stimulus_id for exposure in self.impression.exposures}
        covered = set(self.view.contexts)
        if covered != shown:
            raise ValueError(
                f"a view covers exactly the stimuli of its impression: uncovered {sorted(shown - covered)}, "
                f"extra {sorted(covered - shown)}"
            )
        return self

    @model_validator(mode="after")
    def _reaction_is_about_something_shown(self) -> Self:
        subject = self.reaction.subject_stimulus_id
        shown = {exposure.stimulus_id: exposure for exposure in self.impression.exposures}
        if subject not in shown:
            raise ValueError(f"reaction is about {subject}, which the impression did not show: {sorted(shown)}")
        if self.reaction.action is not ActionKind.IGNORE and not shown[subject].seen:
            raise ValueError(f"reaction engages with {subject}, which the persona did not notice")
        return self
