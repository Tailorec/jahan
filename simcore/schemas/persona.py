"""The persona domain: one simulated individual projected from a dataset row."""

import warnings
from typing import Annotated, Self

from pydantic import AfterValidator, StringConstraints, model_validator

from .base import FrozenDict, Identifier, NonNegativeInt, PersonaId, PositiveInt, SimBaseModel
from .brief import AttributeId
from .enums import FieldOrigin
from .sim import Beliefs

AttributeValue = str | int | float

# The corpora the dataset documents for its rows. Unverified against the dataset card, so an
# unrecognised source warns rather than refuses; promote to an enumeration once the card is read.
KNOWN_PERSONA_SOURCES = frozenset({"wiki", "amazon", "stackoverflow", "gss", "prism", "real_human_survey", "synthetic"})


def _warn_on_unrecognised_source(value: str) -> str:
    if value not in KNOWN_PERSONA_SOURCES:
        warnings.warn(f"unrecognised persona source {value!r}; known sources: {sorted(KNOWN_PERSONA_SOURCES)}", stacklevel=2)
    return value


PersonaSource = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*$"),
    AfterValidator(_warn_on_unrecognised_source),
]


class EmbeddingRef(SimBaseModel):
    """A position in the population's contiguous embedding array, never an inline vector."""

    model_id: Identifier
    dim: PositiveInt
    index: NonNegativeInt


class Persona(SimBaseModel):
    """One projected persona; every field states where its value came from.

    What its category requires — the conditioning set and each attribute's domain — belongs to the
    ontology, and is checked where personas are joined with it, never taken from the persona itself.
    """

    persona_id: PersonaId
    source: PersonaSource
    conditioning: FrozenDict[AttributeId, AttributeValue]
    attributes: FrozenDict[AttributeId, AttributeValue]
    origins: FrozenDict[AttributeId, FieldOrigin]
    # Attribute homophily explains a tie on its own, so embeddings are an optional secondary signal.
    embedding: EmbeddingRef | None = None
    baseline_beliefs: Beliefs

    @model_validator(mode="after")
    def _conditioning_is_present(self) -> Self:
        if not self.conditioning:
            raise ValueError("a persona cannot be conditioned without conditioning attributes")
        return self

    @model_validator(mode="after")
    def _conditioning_and_attributes_are_disjoint(self) -> Self:
        overlap = sorted(set(self.conditioning) & set(self.attributes))
        if overlap:
            raise ValueError(f"an attribute cannot be both conditioning and remaining: {overlap}")
        return self

    @model_validator(mode="after")
    def _origins_cover_every_projected_field(self) -> Self:
        projected = set(self.conditioning) | set(self.attributes)
        stated = set(self.origins)
        if stated != projected:
            raise ValueError(
                f"every projected field states an origin: unstated {sorted(projected - stated)}, "
                f"stated for unknown attributes {sorted(stated - projected)}"
            )
        return self

    @property
    def projected_attributes(self) -> frozenset[str]:
        return frozenset(self.conditioning) | frozenset(self.attributes)
