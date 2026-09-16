"""The audience-preview domain: what a request would draw, answered from an index without decoding a row.

A preview is a forecast, not a verdict: it says how many rows match per source, which attributes are
measured, extracted or absent, how many fields a draw would synthesize, which relaxation rungs it would
climb, and the evidence grade the resulting population would carry. Every count travels with its
denominator, because "nobody was asked" and "nobody is like this" are both zeros otherwise.
"""

from pydantic import Field

from .base import FrozenDict, NonNegativeInt, SimBaseModel, UnitInterval
from .brief import AttributeId
from .enums import FieldOrigin
from .persona import PersonaSource
from .population import Relaxation


class SourcePreview(SimBaseModel):
    """One source's answer to a request: how many rows exist, carry the required attributes, and match
    the filters; and the tier each requested attribute is carried at, or none when it is absent."""

    source: PersonaSource
    total: NonNegativeInt
    carrying: NonNegativeInt
    matched: NonNegativeInt
    # Every requested attribute, keyed to the tier the source carries it at, or nothing when it is absent.
    attributes: FrozenDict[AttributeId, FieldOrigin | None]
    # Attributes some rows recorded in a form the vocabulary cannot express, with how many: those rows are
    # excluded from anything requiring the attribute, and the exclusion follows the value — every `65+`
    # age, never a `25-34` — so it is a skew to see, not a gap to ignore. Only non-zero entries appear.
    unexpressible: FrozenDict[AttributeId, NonNegativeInt] = FrozenDict({})


class AudiencePreview(SimBaseModel):
    """What the corpus holds for one request: per source the matched, carrying and total counts; the
    fields a draw would synthesize; the rungs the relaxation ladder would climb; and the evidence grade
    the resulting population would carry."""

    sources: tuple[SourcePreview, ...] = Field(min_length=1)
    # The fields a draw of the requested size would synthesize, expected from the pool's share — not the
    # count across the whole pool, which scales with the corpus rather than the study.
    synthesized_fields: NonNegativeInt
    synthesized_share: UnitInterval
    relaxations: tuple[Relaxation, ...] = ()
    evidence: FieldOrigin
