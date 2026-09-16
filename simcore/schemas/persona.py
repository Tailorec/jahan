"""The persona domain: one simulated individual projected from a dataset row."""

import warnings
from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .base import FrozenDict, Identifier, NonEmptyStr, NonNegativeInt, PersonaId, PositiveInt, SimBaseModel
from .brief import AttributeId
from .enums import FieldOrigin
from .run import PinnedModelId
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


class CompletedDistribution(SimBaseModel):
    """The probability distribution a completed field was sampled from, in the vocabulary's own order.
    Recorded so projection's calibration can be measured after the fact: a sampled value without its
    distribution is a number nobody can check (ADR 0019, ADR 0024)."""

    values: tuple[NonEmptyStr, ...] = Field(min_length=1)
    probabilities: tuple[Annotated[float, Field(ge=0.0)], ...]

    @model_validator(mode="after")
    def _covers_the_vocabulary_once(self) -> Self:
        if len(self.values) != len(self.probabilities):
            raise ValueError(
                f"a distribution names {len(self.probabilities)} probabilities for {len(self.values)} vocabulary values"
            )
        if len(set(self.values)) != len(self.values):
            raise ValueError("a distribution\'s vocabulary repeats a value")
        total = sum(self.probabilities)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"a distribution must sum to one, got {total}")
        return self


class EmbeddingRef(SimBaseModel):
    """A position in the population's contiguous embedding array, never an inline vector."""

    model_id: PinnedModelId
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
    # The distribution each synthesized field was sampled from, so completion's calibration is measurable.
    completed_distributions: FrozenDict[AttributeId, CompletedDistribution] = FrozenDict({})
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
