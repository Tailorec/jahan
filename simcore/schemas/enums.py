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
