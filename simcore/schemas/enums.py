"""Closed vocabularies shared across domains."""

from enum import StrEnum
from typing import Final


class ClaimSource(StrEnum):
    """Where a statement in the brief came from; claims and assumptions alike."""

    USER_ASSERTED = "user_asserted"
    PUBLIC_SOURCE = "public_source"
    ASSUMED = "assumed"


class PersonaFieldDomain(StrEnum):
    """Which kind of persona field a dataset attribute belongs to.

    Demographics and psychographics are never synthesizable; the completion
    policy may only ever list the remaining domains.
    """

    DEMOGRAPHIC = "demographic"
    PSYCHOGRAPHIC = "psychographic"
    CATEGORY_BEHAVIOUR = "category_behaviour"
    ECONOMIC = "economic"
    DECISION_RULE = "decision_rule"
    MEDIA = "media"


class FieldOrigin(StrEnum):
    """Where a persona field's value came from; grounding is stated, never inferred."""

    GROUNDED = "grounded"
    SYNTHESIZED = "synthesized"
    CALIBRATED = "calibrated"


class TickUnit(StrEnum):
    """The declared real-world duration of one tick; two studies compare only under equal units."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"


class InterventionKind(StrEnum):
    """Something the study does to the world at a tick; interventions compose."""

    LAUNCH = "launch"
    TEASER = "teaser"
    PROMOTION = "promotion"


class InferenceRole(StrEnum):
    """The roles every model call in the system resolves through."""

    TIER_A = "tier_a"
    TIER_B = "tier_b"
    EMBED = "embed"
    SAFETY = "safety"


class Channel(StrEnum):
    """The environment a persona is reached through; each has an exposure budget."""

    SURVEY_ROOM = "survey_room"
    SOCIAL_FEED = "social_feed"
    FORUM = "forum"
    WOM = "wom"


class StimulusKind(StrEnum):
    """What a stimulus is; brand-authored and persona-authored stimuli share the type."""

    CONCEPT = "concept"
    CLAIM_POST = "claim_post"
    PEER_POST = "peer_post"
    PEER_REPLY = "peer_reply"
    WOM_MESSAGE = "wom_message"


class ActionKind(StrEnum):
    """What a persona did in a turn."""

    ANSWER = "answer"
    POST = "post"
    COMMENT = "comment"
    LIKE = "like"
    REPOST = "repost"
    QUOTE = "quote"
    FOLLOW = "follow"
    BUY = "buy"
    ASK_PEER = "ask_peer"
    REJECT = "reject"
    COMPLAIN = "complain"
    REPLY = "reply"
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"
    IGNORE = "ignore"


class InferenceRoute(StrEnum):
    """What served a model call: the pinned primary model, the role's pinned fallback, or the cache."""

    PRIMARY = "primary"
    FALLBACK = "fallback"
    CACHE = "cache"


class ExposureReason(StrEnum):
    """Why a stimulus got through to a persona; the random arm separates filter-driven from organic reach."""

    INTEREST = "interest"
    SOCIAL_PROOF = "social_proof"
    RANDOM = "random"
    WOM = "wom"
    FORUM = "forum"


class DropReason(StrEnum):
    """Why a stimulus that could have reached a persona did not."""

    BUDGET_EXHAUSTED = "budget_exhausted"


class BeliefDim(StrEnum):
    """The closed set of belief dimensions; per-claim credence travels alongside them."""

    VALUE = "value"
    FIT = "fit"
    TRUST = "trust"


class ReflectionTrigger(StrEnum):
    """Why a reflection fired."""

    TICK_CADENCE = "tick_cadence"
    BELIEF_SHIFT = "belief_shift"


class LifecyclePhase(StrEnum):
    """A world's position in its execution."""

    STARTED = "started"
    COMPLETED = "completed"
    PAUSED = "paused"


class RunStatus(StrEnum):
    """A run's registry status; paused runs keep their completed worlds, labeled partial."""

    RUNNING = "running"
    COMPLETED = "completed"
    PAUSED = "paused"
    PARTIAL = "partial"


class WorldStatus(StrEnum):
    """What became of one world by the time its run reported: it reached its horizon, it stopped short, or
    the budget ran out before it began."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    NOT_STARTED = "not_started"


class TrustLevel(StrEnum):
    """Whether a study's results have been checked against real human data; stated once per run."""

    UNCALIBRATED = "uncalibrated"
    CATEGORY_BENCHMARKED = "category_benchmarked"
    PROSPECTIVELY_VALIDATED = "prospectively_validated"


class Confidence(StrEnum):
    """How strongly the evidence supports one finding; independent of engine calibration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingKind(StrEnum):
    """What a finding is; a recommendation is one kind of finding."""

    RANKING = "ranking"
    RISK = "risk"
    OBJECTION = "objection"
    BELIEF_SHIFT = "belief_shift"
    WOM_PATH = "wom_path"
    RECOMMENDATION = "recommendation"


class AnomalyKind(StrEnum):
    """The closed set of rule-based anomaly flags."""

    HERDING = "herding"
    BACKLASH = "backlash"
    FLOP = "flop"


class DegradationRung(StrEnum):
    """A step on the budget's degrade ladder, in escalating order; a world only ever climbs it."""

    WARN = "warn"
    FREEZE_OPTIONAL_TIER_B = "freeze_optional_tier_b"
    SUBSAMPLE_ACTIVATION = "subsample_activation"
    PAUSE = "pause"


# Rungs are declared in escalation order, and degradation only ever climbs them.
RUNG_ORDER: Final[tuple["DegradationRung", ...]] = tuple(DegradationRung)


class GuardrailRule(StrEnum):
    """The rule a guardrail violation broke."""

    REFERENCES_UNSHOWN_STIMULUS = "references_unshown_stimulus"


class RelaxationRung(StrEnum):
    """A step on the shortfall ladder, in escalating order; the conditioning set is never one.

    A quota that cannot be filled widens an ordinal predicate by one band, then drops the least
    relevant non-conditioning filter, then accepts the shortfall rather than inventing coverage."""

    WIDEN_ORDINAL = "widen_ordinal"
    DROP_FILTER = "drop_filter"
    ACCEPT_SHORTFALL = "accept_shortfall"


class GateReference(StrEnum):
    """What a gate report judged its sample against.

    `design` is the share-weighted mixture of the audiences the study asked for: it catches a draw
    that did not realise its own design, and says nothing about whether the study matches the real
    world. `category_targets` is that stronger claim, and needs measured targets the engine does not
    yet carry."""

    DESIGN = "design"
    CATEGORY_TARGETS = "category_targets"


class GraphCheck(StrEnum):
    """A structural property of the social graph that a gate result can judge."""

    DEGREE_SHAPE = "degree_shape"
    CLUSTERING = "clustering"
    CONNECTIVITY = "connectivity"

