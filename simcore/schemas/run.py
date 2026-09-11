"""The run domain: what is executed — concept variants, scenarios, budgets, model pins,
the run configuration, and the derivation of world identity."""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
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
    canonical_hash,
    proportions_sum_to_one,
)
from .brief import BriefPack, ClaimId, CurrencyCode, Price
from .enums import InterventionKind, TickUnit

VariantId = Identifier
WorldId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]

_FLOATING_VERSION = re.compile(r"(^|[/:@._-])latest$", re.IGNORECASE)


def _versioned_model_id(value: str) -> str:
    if value == "*" or _FLOATING_VERSION.search(value):
        raise ValueError(f"model pins must name a fixed model version, got floating {value!r}")
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


def _check_study_cells(scenarios: Iterable[Scenario], seeds: Iterable[int]) -> None:
    """Every (scenario, replicate) cell of a run or grid must be a distinct, comparable world."""
    scenarios, seeds = tuple(scenarios), tuple(seeds)
    repeated_seeds = sorted(seed for seed, count in Counter(seeds).items() if count > 1)
    if repeated_seeds:
        raise ValueError(f"replicate seeds repeated, which would run identical worlds: {repeated_seeds}")
    if len(set(map(canonical_hash, scenarios))) != len(scenarios):
        raise ValueError("scenarios repeated, which would run identical worlds")
    cards: dict[str, str] = {}
    for scenario in scenarios:
        card = canonical_hash(scenario.variant)
        if cards.setdefault(scenario.variant.variant_id, card) != card:
            raise ValueError(f"variant {scenario.variant.variant_id!r} names two different concept cards")
    units = {scenario.tick_unit for scenario in scenarios}
    if len(units) > 1:
        raise ValueError(f"scenarios in one run must share a tick unit to be comparable, got {sorted(units)}")


class RunConfig(SimBaseModel):
    # The run id names one execution; it is not an input, so identical configurations hash identically.
    _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"run_id"})
    _hash_version_: ClassVar[bool] = True

    run_id: RunId
    pins: ModelPins
    budget: Budget
    brief_hash: BriefHash
    ontology_hash: OntologyHash
    population_hash: PopulationHash
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _cells_are_distinct_and_comparable(self) -> Self:
        _check_study_cells(self.scenarios, self.seeds)
        return self


class SweepGrid(SimBaseModel):
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    budget: Budget
    pins: ModelPins

    @model_validator(mode="after")
    def _cells_are_distinct_and_comparable(self) -> Self:
        _check_study_cells(self.scenarios, self.seeds)
        return self


class SweepPlan(SimBaseModel):
    """A sweep grid joined with the brief it tests: every name a scenario uses must exist in that brief."""

    pack: BriefPack
    grid: SweepGrid

    @model_validator(mode="after")
    def _scenarios_reference_the_brief(self) -> Self:
        brief = self.pack.brief
        audiences = {audience.name for audience in brief.audiences}
        claims = {claim.id for claim in brief.claims}
        for scenario in self.grid.scenarios:
            variant = scenario.variant.variant_id
            if audiences:
                unknown = sorted(set(scenario.audience_weights) - audiences)
                if unknown:
                    raise ValueError(f"scenario {variant!r} weights audiences the brief does not declare: {unknown}")
            unknown_claims = sorted(set(scenario.variant.emphasized_claims) - claims)
            if unknown_claims:
                raise ValueError(f"scenario {variant!r} emphasizes claims the brief does not make: {unknown_claims}")
            if scenario.price.currency != brief.price.currency:
                raise ValueError(
                    f"scenario {variant!r} is priced in {scenario.price.currency}, the brief in {brief.price.currency}"
                )
        return self


def derive_world_seed(replicate_seed: int, variant_id: str) -> int:
    """Worlds of one variant share their random draws across prices and conditions, isolating those effects."""
    digest = hashlib.sha256(f"{int(replicate_seed)}:{variant_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def derive_world_id(scenario: Scenario, replicate_seed: int, population_hash: str) -> WorldId:
    """A world is identified by everything that makes it a distinct cell: its full scenario, replicate and population."""
    material = f"{canonical_hash(scenario)}:{int(replicate_seed)}:{population_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
