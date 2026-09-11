"""The population domain: distribution gates, the sample manifest, and the discovered social structure."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import (
    FrozenDict,
    GraphHash,
    Identifier,
    NonNegativeInt,
    PersonaId,
    PopulationHash,
    PositiveInt,
    SimBaseModel,
    UnitInterval,
    proportions_sum_to_one,
)
from .brief import AttributeId
from .enums import FieldOrigin
from .persona import PersonaSource


class CategoricalGateResult(SimBaseModel):
    kind: Literal["categorical"]
    attribute: AttributeId
    attribute_origin: FieldOrigin
    chi_square: Annotated[float, Field(ge=0.0)]
    degrees_of_freedom: PositiveInt
    p_value: UnitInterval
    passed: bool

    @model_validator(mode="after")
    def _gates_run_on_grounded_attributes_only(self) -> Self:
        if self.attribute_origin is not FieldOrigin.GROUNDED:
            raise ValueError(
                f"gates run on grounded attributes only; {self.attribute!r} is {self.attribute_origin.value}"
            )
        return self


class OrdinalGateResult(SimBaseModel):
    kind: Literal["ordinal"]
    attribute: AttributeId
    attribute_origin: FieldOrigin
    ks_statistic: Annotated[float, Field(ge=0.0, le=1.0)]
    ks_similarity: Annotated[float, Field(ge=0.0, le=1.0)]
    passed: bool

    @model_validator(mode="after")
    def _gates_run_on_grounded_attributes_only(self) -> Self:
        if self.attribute_origin is not FieldOrigin.GROUNDED:
            raise ValueError(
                f"gates run on grounded attributes only; {self.attribute!r} is {self.attribute_origin.value}"
            )
        return self

    @model_validator(mode="after")
    def _similarity_is_one_minus_statistic(self) -> Self:
        if abs(self.ks_similarity - (1.0 - self.ks_statistic)) > 1e-9:
            raise ValueError("ks_similarity must equal one minus the ks_statistic")
        return self


GateResult = CategoricalGateResult | OrdinalGateResult


class GateReport(SimBaseModel):
    results: tuple[Annotated[GateResult, Field(discriminator="kind")], ...]
    source_mix: FrozenDict[PersonaSource, UnitInterval]

    @model_validator(mode="after")
    def _source_mix_is_complete(self) -> Self:
        proportions_sum_to_one(self.source_mix)
        return self

    @property
    def overall(self) -> bool:
        return all(result.passed for result in self.results)


class PopulationManifest(SimBaseModel):
    population_hash: PopulationHash
    population_seed: NonNegativeInt
    persona_ids: tuple[PersonaId, ...] = Field(min_length=1)
    achieved_mix: FrozenDict[Identifier, UnitInterval]

    @model_validator(mode="after")
    def _achieved_mix_is_complete(self) -> Self:
        proportions_sum_to_one(self.achieved_mix)
        return self


class SocialEdge(SimBaseModel):
    u: PersonaId
    v: PersonaId
    weight: UnitInterval

    @model_validator(mode="after")
    def _no_self_loops(self) -> Self:
        if self.u == self.v:
            raise ValueError(f"a social edge cannot join a persona to itself: {self.u!r}")
        return self


class SocialGraph(SimBaseModel):
    graph_hash: GraphHash
    edges: tuple[SocialEdge, ...]


class Community(SimBaseModel):
    community_id: Identifier
    member_ids: tuple[PersonaId, ...] = Field(min_length=1)
