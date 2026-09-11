"""Closed vocabularies shared across domains."""

from enum import StrEnum


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


class BeliefDim(StrEnum):
    """The closed set of belief dimensions; per-claim credence travels alongside them."""

    VALUE = "value"
    FIT = "fit"
    TRUST = "trust"
