"""The run domain: what is executed — concept variants, scenarios, budgets, model pins,
the run configuration, and the derivation of world identity."""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, ClassVar, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .base import (
    BriefHash,
    FrozenDict,
    GraphHash,
    HashDigest,
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
from .brief import BriefPack, ClaimId, CurrencyCode, Price, ProductBrief
from .enums import TurnTask, InferenceRole, InterventionKind, TickUnit

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

NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class PinPrice(SimBaseModel):
    """What a pinned model charges per million tokens, as the study declared it. A price the study states
    is what makes a `price_table` cost a computation rather than an invention."""

    input_per_million: NonNegativeFloat
    output_per_million: NonNegativeFloat
    currency: CurrencyCode = "USD"


class ModelPin(SimBaseModel):
    """A pin as a specification, not a bare identifier: the name sent to the endpoint, the served
    identifiers that answer counts as this model, whether it follows a strict output schema, whether a
    `seed` it is sent is honoured, and what it costs. A call served by anything outside `serves` is a
    pin failure: an answer from an unnamed model would silently change what the study measured."""

    model_id: PinnedModelId
    serves: frozenset[PinnedModelId]
    structured_output: bool = False
    honours_seed: bool = False
    price: PinPrice | None = None

    @model_validator(mode="before")
    @classmethod
    def _reads_as_a_bare_identifier(cls, data: Any) -> Any:
        # A bare model identifier is a pin that accepts only itself and promises no capability.
        if isinstance(data, str):
            return {"model_id": data, "serves": {data}}
        if isinstance(data, Mapping) and isinstance(data.get("model_id"), str) and "serves" not in data:
            return {**data, "serves": {data["model_id"]}}
        return data

    @model_validator(mode="after")
    def _the_name_sent_answers_as_itself(self) -> Self:
        if self.model_id not in self.serves:
            raise ValueError(f"pin {self.model_id!r} must accept its own name among the identifiers it serves")
        return self


class ModelPins(SimBaseModel):
    """The model every role resolves to, and at most one pinned fallback per role. Embedding never falls back:
    anchors and responses scored with different embedding models are not comparable (ADR 0012)."""

    tier_a: ModelPin
    tier_b: ModelPin
    embed: ModelPin
    safety: ModelPin | None = None
    fallbacks: FrozenDict[InferenceRole, ModelPin] = FrozenDict({})

    @model_validator(mode="after")
    def _fallbacks_are_real_alternatives(self) -> Self:
        if InferenceRole.EMBED in self.fallbacks:
            raise ValueError("the embedding role never falls back: responses must be scored in the anchors' embedding space")
        for role, fallback in self.fallbacks.items():
            primary = getattr(self, role.value)
            if primary is None:
                raise ValueError(f"{role.value} has a fallback but no primary model")
            if fallback.model_id == primary.model_id:
                raise ValueError(f"{role.value}'s fallback {fallback.model_id} is its primary model")
        return self


class Budget(SimBaseModel):
    max_cost: Annotated[float, Field(gt=0.0)]
    currency: CurrencyCode


class ElicitationParams(SimBaseModel):
    """The SSR study parameters for one construct: temperature applied once after the mean across
    sets, and ε added to the least similar anchor and the denominator. Defaults are the paper's."""

    temperature: Annotated[float, Field(ge=0.0)] = 1.0
    epsilon: Annotated[float, Field(ge=0.0)] = 0.0


class Variant(SimBaseModel):
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

    variant: Variant
    price: Price
    # Omitted weights inherit the brief's declared audience shares; stated ones must sum to one.
    audience_weights: FrozenDict[Identifier, UnitInterval] | None = None
    tick_unit: TickUnit
    horizon_ticks: PositiveInt
    interventions: tuple[Intervention, ...] = ()
    # Stimuli one persona can be shown per channel per tick; the survey room always shows exactly one.
    exposure_budget: PositiveInt = 3
    # What an activated persona is asked. A study exists to ask purchase intent, and until this
    # was a scenario's to say, the runner named the task itself and adoption was unreachable from
    # any configuration — 400 real turns produced verbatims and no intent at all.
    elicits: TurnTask = TurnTask.REACTION

    @model_validator(mode="after")
    def _audience_weights_sum_to_one(self) -> Self:
        if self.audience_weights is not None:
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
            raise ValueError(f"variant {scenario.variant.variant_id!r} names two different variants")
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
    graph_hash: GraphHash | None = None
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    # Replay needs the exact prompt templates and SSR anchor sets, not just the model pins.
    template_hashes: FrozenDict[Identifier, HashDigest]
    anchor_set_hashes: FrozenDict[Identifier, HashDigest] = FrozenDict({})
    # Per-construct SSR parameters, hashed with the run; absent constructs run at the paper's defaults.
    elicitation_params: FrozenDict[Identifier, ElicitationParams] = FrozenDict({})

    @model_validator(mode="after")
    def _cells_are_distinct_and_comparable(self) -> Self:
        _check_study_cells(self.scenarios, self.seeds)
        return self

    @model_validator(mode="after")
    def _every_scenario_states_the_weights_it_runs_with(self) -> Self:
        """A brief may leave weights to be inherited; a run configuration may not.

        It is a recorded input, read downstream by modules that hold no brief to inherit from, so the
        weights are resolved when the configuration is assembled and stated here."""
        unresolved = sorted(s.variant.variant_id for s in self.scenarios if s.audience_weights is None)
        if unresolved:
            raise ValueError(
                f"scenarios carry no audience weights and a run configuration cannot inherit them: {unresolved}; "
                "resolve them against the brief before configuring the run"
            )
        return self

    @model_validator(mode="after")
    def _templates_are_pinned(self) -> Self:
        if not self.template_hashes:
            raise ValueError("a run renders prompts, so it must pin the hash of every template it uses")
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
        for scenario in self.grid.scenarios:
            check_scenario_against_brief(scenario, self.pack.brief)
        return self


def resolve_audience_weights(
    scenario: Scenario, brief: ProductBrief
) -> FrozenDict[Identifier, UnitInterval] | None:
    """The weights a scenario runs with: its own if it states any, else the brief's declared shares."""
    if scenario.audience_weights is not None:
        return scenario.audience_weights
    return brief.audience_shares


def check_scenario_against_brief(scenario: Scenario, brief: ProductBrief) -> None:
    """Every name a scenario uses must exist in the brief it tests; omitted weights inherit its shares."""
    variant = scenario.variant.variant_id
    audiences = {audience.name for audience in brief.audiences}
    weights = resolve_audience_weights(scenario, brief)
    if audiences:
        if weights is None:
            raise ValueError(
                f"scenario {variant!r} states no audience weights and the brief declares no shares to inherit"
            )
        unknown = sorted(set(weights) - audiences)
        if unknown:
            raise ValueError(f"scenario {variant!r} weights audiences the brief does not declare: {unknown}")
    unknown_claims = sorted(set(scenario.variant.emphasized_claims) - {claim.id for claim in brief.claims})
    if unknown_claims:
        raise ValueError(f"scenario {variant!r} emphasizes claims the brief does not make: {unknown_claims}")
    if scenario.price.currency != brief.price.currency:
        raise ValueError(f"scenario {variant!r} is priced in {scenario.price.currency}, the brief in {brief.price.currency}")


def derive_world_seed(replicate_seed: int, variant_id: str) -> int:
    """Worlds of one variant share their random draws across prices and conditions, isolating those effects."""
    digest = hashlib.sha256(f"{int(replicate_seed)}:{variant_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def derive_world_id(scenario: Scenario, replicate_seed: int, population_hash: str) -> WorldId:
    """A world is identified by everything that makes it a distinct cell: its full scenario, replicate and population."""
    material = f"{canonical_hash(scenario)}:{int(replicate_seed)}:{population_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
