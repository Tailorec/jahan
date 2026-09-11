"""The persona domain: one simulated individual projected from a dataset row."""

from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenDict, Identifier, NonNegativeInt, PersonaId, PositiveInt, SimBaseModel
from .brief import AttributeId
from .enums import FieldOrigin, PersonaFieldDomain

AttributeValue = str | int | float

PersonaSource = Annotated[str, StringConstraints(pattern=r"^(matraix|gss|synthetic)$")]


class EmbeddingRef(SimBaseModel):
    """A position in the population's contiguous embedding array, never an inline vector."""

    model_id: Identifier
    dim: PositiveInt
    index: NonNegativeInt


class Persona(SimBaseModel):
    """One projected persona; every field states where its value came from."""

    persona_id: PersonaId
    source: PersonaSource
    category: Identifier
    conditioning_set: frozenset[AttributeId] = Field(min_length=1)
    conditioning: FrozenDict[AttributeId, AttributeValue]
    attributes: FrozenDict[AttributeId, AttributeValue]
    attribute_domains: FrozenDict[AttributeId, PersonaFieldDomain]
    origins: FrozenDict[AttributeId, FieldOrigin]
    embedding: EmbeddingRef

    @model_validator(mode="after")
    def _conditioning_is_exactly_the_declared_set(self) -> Self:
        declared = set(self.conditioning_set)
        present = set(self.conditioning)
        if present != declared:
            missing = sorted(declared - present)
            unexpected = sorted(present - declared)
            raise ValueError(
                f"conditioning must hold exactly the declared set for {self.category!r}: "
                f"missing {missing}, unexpected {unexpected}"
            )
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

    @model_validator(mode="after")
    def _domains_cover_every_projected_field(self) -> Self:
        projected = set(self.conditioning) | set(self.attributes)
        missing = sorted(projected - set(self.attribute_domains))
        if missing:
            raise ValueError(f"projected fields have no declared domain: {missing}")
        return self

    @model_validator(mode="after")
    def _demographics_and_psychographics_are_never_synthesized(self) -> Self:
        never = {PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC}
        invented = sorted(
            attribute
            for attribute, origin in self.origins.items()
            if origin is FieldOrigin.SYNTHESIZED and self.attribute_domains[attribute] in never
        )
        if invented:
            raise ValueError(f"demographic or psychographic fields may not be synthesized: {invented}")
        return self
