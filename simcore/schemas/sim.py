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
from .enums import ActionKind, BeliefDim, Channel, ElicitationFailureKind, ExposureReason, MemorySource, StimulusKind
from .run import PinnedModelId

ImpressionId = Annotated[str, StringConstraints(pattern=rf"^im-{ULID_PATTERN}$")]
ReactionId = Annotated[str, StringConstraints(pattern=rf"^rc-{ULID_PATTERN}$")]
MemoryId = Annotated[str, StringConstraints(pattern=rf"^me-{ULID_PATTERN}$")]

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


def _non_negative(mass: tuple[float, ...]) -> tuple[float, ...]:
    if any(value < 0.0 for value in mass):
        raise ValueError("a per-set mass contains a negative value")
    return mass


def _range_check(mass: tuple[float, ...], low: float, high: float) -> tuple[float, ...]:
    if any(not (low <= value <= high) for value in mass):
        raise ValueError(f"similarities must lie in [{low}, {high}]")
    return mass


AnchorSimplex5 = Annotated[
    tuple[float, float, float, float, float],
    AfterValidator(_non_negative),
    AfterValidator(_mass_sums_to_one),
]

Similarity5 = Annotated[
    tuple[float, float, float, float, float],
    AfterValidator(lambda mass: _range_check(mass, 0.0, 1.0)),
]


def _tempered_mean(sets: tuple[tuple[float, ...], ...], temperature: float) -> tuple[float, float, float, float, float]:
    """Temperature applied once, after the mean across sets; zero gives a one-hot at the most likely point."""
    mean = [sum(mass[point] for mass in sets) / len(sets) for point in range(5)]
    if temperature == 0.0:
        if all(value == mean[0] for value in mean):
            return (0.2, 0.2, 0.2, 0.2, 0.2)
        top = max(range(5), key=lambda point: mean[point])
        return tuple(1.0 if point == top else 0.0 for point in range(5))
    if temperature == 1.0:
        return (mean[0], mean[1], mean[2], mean[3], mean[4])
    shaped = [value ** (1.0 / temperature) if value > 0 else 0.0 for value in mean]
    total = sum(shaped)
    if total <= 0.0:
        return (0.2, 0.2, 0.2, 0.2, 0.2)
    return tuple(value / total for value in shaped)


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


class MemoryEvent(SimBaseModel):
    """One thing that happened to one persona, as that persona would recall it.

    Live state carries the embedding retrieval scores against; the trace records what was remembered
    and not the vector it was indexed by, so a partition stays readable and small (ADR 0030).
    """

    memory_id: MemoryId
    tick: NonNegativeInt
    description: NonEmptyStr
    importance: UnitInterval
    source: MemorySource
    embedding: tuple[float, ...] | None = None
    embed_model_id: PinnedModelId | None = None

    @model_validator(mode="after")
    def _an_embedding_names_its_model(self) -> Self:
        if (self.embedding is None) != (self.embed_model_id is None):
            raise ValueError(
                "an embedding names the model that produced it, and a model with no embedding indexes nothing: "
                "give both, or neither for a memory read back from a trace"
            )
        if self.embedding is not None and not self.embedding:
            raise ValueError("an embedding with no dimensions retrieves nothing")
        return self


class PersonaState(SimBaseModel):
    """What one persona carries between ticks: what it believes, what it remembers, and when it last
    reflected. It travels with the persona's job and is never shared between personas (ADR 0030)."""

    persona_id: PersonaId
    beliefs: Beliefs
    memories: tuple[MemoryEvent, ...] = ()
    last_reflection_tick: NonNegativeInt = 0
    turns_since_reflection: NonNegativeInt = 0

    @model_validator(mode="after")
    def _each_memory_once(self) -> Self:
        repeated = sorted(mid for mid, count in Counter(item.memory_id for item in self.memories).items() if count > 1)
        if repeated:
            raise ValueError(f"a persona remembers each thing once; held more than once: {repeated}")
        return self


class ProbeAnswer(SimBaseModel):
    """One character-probe question, what the persona's own attributes say, and what it answered.

    The question is closed: the persona chooses between its own value and distractors from the
    attribute's domain. An open question cannot be marked wrong — a persona answering "three or
    four times a week" holds `3_plus_weekly` and would read as drift — so `options` carries what
    was offered, and an answer naming none of them is `answered=False` rather than disagreement.
    """

    question: NonEmptyStr
    attribute: Identifier
    expected: NonEmptyStr
    answer: NonEmptyStr
    agreed: bool
    options: tuple[NonEmptyStr, ...] = ()
    # False when the call failed, or its answer named no option: silence is not drift.
    answered: bool = True

    @model_validator(mode="after")
    def _an_unanswered_probe_agrees_with_nothing(self) -> Self:
        if not self.answered and self.agreed:
            raise ValueError("a probe that was never answered cannot agree")
        if self.options and self.expected not in self.options:
            raise ValueError(f"the persona's own value {self.expected!r} is not among the options it was offered")
        return self


class ProbeResult(SimBaseModel):
    """Whether a persona still answers as itself. Drift is measured, never corrected."""

    persona_id: PersonaId
    tick: NonNegativeInt
    answers: tuple[ProbeAnswer, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _each_attribute_once(self) -> Self:
        repeated = sorted(a for a, count in Counter(item.attribute for item in self.answers).items() if count > 1)
        if repeated:
            raise ValueError(f"a probe asks about an attribute once; asked more than once: {repeated}")
        return self

    @computed_field
    @property
    def answered_count(self) -> int:
        return sum(answer.answered for answer in self.answers)

    @computed_field
    @property
    def disagreement_rate(self) -> float:
        """Drift among the questions the persona actually answered; an unread probe says nothing."""
        answered = [answer for answer in self.answers if answer.answered]
        if not answered:
            return 0.0
        return sum(not answer.agreed for answer in answered) / len(answered)


class SsrResult(SimBaseModel):
    """The elicitation record: free text in, one response mass per anchor reference set, and every
    identifier needed to detect an anchor/response embedding-model mismatch from the record alone.
    The headline mass is temperature applied to the mean of the per-set masses, so it cannot
    disagree with them. The raw per-set similarities make a change of ε or temperature arithmetic."""

    response_text: NonEmptyStr
    per_set_pmfs: tuple[AnchorSimplex5, ...] = Field(min_length=MIN_REFERENCE_SETS)
    per_set_similarities: tuple[Similarity5, ...] = Field(min_length=MIN_REFERENCE_SETS)
    construct_id: Identifier
    category: Identifier
    anchor_set_id: Identifier
    anchor_version: Identifier
    embed_model_id: PinnedModelId
    temperature: Annotated[float, Field(ge=0.0)] = 1.0
    epsilon: Annotated[float, Field(ge=0.0)] = 0.0

    @model_validator(mode="after")
    def _similarities_match_the_distributions(self) -> Self:
        if len(self.per_set_similarities) != len(self.per_set_pmfs):
            raise ValueError(
                f"one similarity vector of five per anchor set beside each set's distribution: "
                f"{len(self.per_set_similarities)} similarities for {len(self.per_set_pmfs)} distributions"
            )
        return self

    @computed_field
    @property
    def pmf(self) -> tuple[float, float, float, float, float]:
        return _tempered_mean(self.per_set_pmfs, self.temperature)


class ElicitationFailure(SimBaseModel):
    """A response that produced no distribution: what went wrong, with no mass to misread."""

    kind: ElicitationFailureKind
    detail: NonEmptyStr
    response_text: str = ""
    construct_id: Identifier


SsrOutcome = SsrResult | ElicitationFailure


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
    # When no anchor version is pinned the verbatim is kept and the recorded failure
    # stands in place of a distribution, so a run without intent data is visibly that.
    elicitation_failure: ElicitationFailure | None = None

    @model_validator(mode="after")
    def _a_distribution_or_the_failure_in_its_place(self) -> Self:
        if self.intent is not None and self.elicitation_failure is not None:
            raise ValueError("a reaction carries a distribution or the failure that stands in its place, never both")
        return self

    @model_validator(mode="after")
    def _verbatim_matches_action(self) -> Self:
        if self.action in _TEXT_ACTIONS and self.verbatim is None:
            raise ValueError(f"a {self.action.value} produces text, so it needs a verbatim")
        if self.action is ActionKind.IGNORE and (self.verbatim is not None or self.intent is not None):
            raise ValueError("an ignored impression produces neither a verbatim nor an elicitation")
        return self


# What each channel lets a persona do. A persona may attempt anything; the channel decides what
# lands, and an action it does not afford changes no state and appears in no view. `world` enforces
# it and the partition counts engagement by it — one rule, so the record and the world cannot
# disagree about whether an upvote on a feed ever happened.
CHANNEL_AFFORDANCES: dict[Channel, frozenset[ActionKind]] = {
    Channel.SURVEY_ROOM: frozenset({ActionKind.ANSWER}),
    Channel.SOCIAL_FEED: frozenset(
        {ActionKind.POST, ActionKind.COMMENT, ActionKind.LIKE, ActionKind.REPOST, ActionKind.QUOTE, ActionKind.FOLLOW}
    ),
    Channel.FORUM: frozenset({ActionKind.POST, ActionKind.REPLY, ActionKind.UPVOTE, ActionKind.DOWNVOTE}),
    Channel.WOM: frozenset({ActionKind.ASK_PEER, ActionKind.COMMENT, ActionKind.COMPLAIN, ActionKind.REJECT, ActionKind.BUY}),
}


def action_lands(channel: Channel, action: ActionKind) -> bool:
    """Whether an action lands on a channel. Ignoring always lands; anything else must be afforded."""
    if action is ActionKind.IGNORE:
        return True
    return action in CHANNEL_AFFORDANCES[channel]


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
    # Who passed this on, when a peer did: word of mouth travels from a teller, and the tie
    # strength beside it is the tie to that teller rather than to the author. Without it the
    # record cannot say who told whom, so a word-of-mouth path could not be read back.
    via_persona_id: PersonaId | None = None

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


def check_view_covers_impression(view: View, impression: Impression) -> None:
    """A view names its impression and covers exactly the stimuli that impression shows."""
    if view.impression_id != impression.impression_id:
        raise ValueError(f"view names impression {view.impression_id}, but it is paired with {impression.impression_id}")
    shown = set(impression.stimulus_ids)
    covered = set(view.contexts)
    if covered != shown:
        raise ValueError(
            f"a view covers exactly the stimuli of its impression: uncovered {sorted(shown - covered)}, extra {sorted(covered - shown)}"
        )


class Presentation(SimBaseModel):
    """An impression delivered with its view — everything a persona is given to react to in one turn."""

    impression: Impression
    view: View

    @model_validator(mode="after")
    def _view_matches_the_impression(self) -> Self:
        check_view_covers_impression(self.view, self.impression)
        return self


class Turn(SimBaseModel):
    """One persona reacting to one impression; the unit of simulation and of cost. The view
    it was shown travels with the turn, so social proof is part of the record."""

    impression: Impression
    view: View
    reaction: Reaction

    @model_validator(mode="after")
    def _view_matches_the_impression(self) -> Self:
        check_view_covers_impression(self.view, self.impression)
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
