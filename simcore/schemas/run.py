"""The run domain: what is executed — concept variants, scenarios, budgets, model pins,
the run configuration, and the derivation of world identity."""

import hashlib
from typing import Annotated, ClassVar, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .base import (
    BriefHash,
    FrozenDict,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    OntologyHash,
    PopulationHash,
    PositiveInt,
    RunId,
    SimBaseModel,
    UnitInterval,
    proportions_sum_to_one,
)
from .brief import ClaimId, CurrencyCode, Price
from .enums import InferenceRole, InterventionKind, TickUnit

VariantId = Identifier
WorldId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]


def _versioned_model_id(value: str) -> str:
    if value in {"latest", "*"}:
        raise ValueError(f"model pins must name a versioned model, got {value!r}")
    return value


PinnedModelId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]*$"),
    AfterValidator(_versioned_model_id),
]


class ModelPins(SimBaseModel):
    tier_a: PinnedModelId
    tier_b: PinnedModelId
    embed: PinnedModelId
    safety: PinnedModelId | None = None


class Budget(SimBaseModel):
    max_cost: Annotated[float, Field(gt=0.0)]
    currency: CurrencyCode


class ConceptCard(SimBaseModel):
    """One version of the proposition under test; the price it faces lives on the scenario."""

    variant_id: VariantId
    name: NonEmptyStr
    description: NonEmptyStr
    emphasized_claims: tuple[ClaimId, ...] = ()


class Intervention(SimBaseModel):
    tick: NonNegativeInt
    kind: InterventionKind


class Scenario(SimBaseModel):
    """One variant together with the conditions it faces; it describes no random draw."""

    variant: ConceptCard
    price: Price
    audience_weights: FrozenDict[Identifier, UnitInterval]
    tick_unit: TickUnit
    horizon_ticks: PositiveInt
    interventions: tuple[Intervention, ...] = ()

    @model_validator(mode="after")
    def _audience_weights_sum_to_one(self) -> Self:
        proportions_sum_to_one(self.audience_weights)
        return self

    @model_validator(mode="after")
    def _interventions_land_within_the_horizon(self) -> Self:
        beyond = sorted(
            intervention.tick for intervention in self.interventions if intervention.tick >= self.horizon_ticks
        )
        if beyond:
            raise ValueError(
                f"interventions scheduled at or beyond the horizon of {self.horizon_ticks} ticks: {beyond}"
            )
        return self


class RunConfig(SimBaseModel):
    _hash_version_: ClassVar[bool] = True

    run_id: RunId
    pins: ModelPins
    budget: Budget
    brief_hash: BriefHash
    ontology_hash: OntologyHash
    population_hash: PopulationHash
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)


class SweepGrid(SimBaseModel):
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    budget: Budget
    pins: ModelPins


def derive_world_seed(replicate_seed: int, variant_id: str) -> int:
    digest = hashlib.sha256(f"{int(replicate_seed)}:{variant_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def derive_world_id(variant_id: str, replicate_seed: int, population_hash: str) -> WorldId:
    digest = hashlib.sha256(f"{variant_id}:{int(replicate_seed)}:{population_hash}".encode("utf-8")).hexdigest()
    return digest[:12]
