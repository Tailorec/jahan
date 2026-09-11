"""The population domain: distribution gates, the sample manifest, the discovered social structure,
and the population that joins them with the brief and ontology they were built for."""

from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import Field, computed_field, model_validator

from .base import (
    FrozenDict,
    GraphHash,
    Identifier,
    NonNegativeInt,
    PersonaId,
    PopulationHash,
    SimBaseModel,
    UnitInterval,
    proportions_sum_to_one,
)
from .brief import AttributeId, BriefPack
from .enums import FieldOrigin, PersonaFieldDomain
from .persona import Persona, PersonaSource

OpenUnitInterval = Annotated[float, Field(gt=0.0, lt=1.0)]


class CategoricalGateResult(SimBaseModel):
    """A chi-squared test on a categorical marginal; it passes when the p-value exceeds its significance level."""

    kind: Literal["categorical"]
    attribute: AttributeId
    chi_square: Annotated[float, Field(ge=0.0)]
    degrees_of_freedom: Annotated[int, Field(gt=0)]
    p_value: UnitInterval
    significance_level: OpenUnitInterval = 0.05

    @computed_field
    @property
    def passed(self) -> bool:
        return self.p_value > self.significance_level


class OrdinalGateResult(SimBaseModel):
    """A KS test on an ordinal attribute; it passes when the similarity reaches its threshold."""

    kind: Literal["ordinal"]
    attribute: AttributeId
    ks_statistic: UnitInterval
    ks_similarity: UnitInterval
    similarity_threshold: Annotated[float, Field(gt=0.0, le=1.0)] = 0.80

    @model_validator(mode="after")
    def _similarity_is_one_minus_statistic(self) -> Self:
        if abs(self.ks_similarity - (1.0 - self.ks_statistic)) > 1e-9:
            raise ValueError("ks_similarity must equal one minus the ks_statistic")
        return self

    @computed_field
    @property
    def passed(self) -> bool:
        return self.ks_similarity >= self.similarity_threshold


GateResult = Annotated[CategoricalGateResult | OrdinalGateResult, Field(discriminator="kind")]


class GateReport(SimBaseModel):
    results: tuple[GateResult, ...] = Field(min_length=1)
    source_mix: FrozenDict[PersonaSource, UnitInterval]

    @model_validator(mode="after")
    def _source_mix_is_complete(self) -> Self:
        proportions_sum_to_one(self.source_mix)
        return self

    @model_validator(mode="after")
    def _one_result_per_attribute(self) -> Self:
        repeated = sorted(name for name, count in Counter(r.attribute for r in self.results).items() if count > 1)
        if repeated:
            raise ValueError(f"more than one gate result for: {repeated}")
        return self

    @computed_field
    @property
    def overall(self) -> bool:
        return all(result.passed for result in self.results)


class PopulationManifest(SimBaseModel):
    population_hash: PopulationHash
    population_seed: NonNegativeInt
    persona_ids: tuple[PersonaId, ...] = Field(min_length=1)
    achieved_mix: FrozenDict[Identifier, UnitInterval]

    @model_validator(mode="after")
    def _persona_ids_unique(self) -> Self:
        repeated = sorted(name for name, count in Counter(self.persona_ids).items() if count > 1)
        if repeated:
            raise ValueError(f"persona ids sampled more than once: {repeated}")
        return self

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

    @model_validator(mode="after")
    def _each_tie_appears_once(self) -> Self:
        ties = Counter(frozenset((edge.u, edge.v)) for edge in self.edges)
        repeated = sorted(tuple(sorted(tie)) for tie, count in ties.items() if count > 1)
        if repeated:
            raise ValueError(f"social ties declared more than once, in either direction: {repeated}")
        return self


class Community(SimBaseModel):
    community_id: Identifier
    member_ids: tuple[PersonaId, ...] = Field(min_length=1)


_NEVER_SYNTHESIZED = frozenset({PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC})


class Population(SimBaseModel):
    """Who is in a study, checked against the brief and ontology it was built for.

    Every invariant that spans personas — conditioning, field domains, gate grounding, source mix,
    graph membership, community partition — is enforced here rather than trusted from its parts.
    """

    pack: BriefPack
    manifest: PopulationManifest
    personas: tuple[Persona, ...] = Field(min_length=1)
    gate_report: GateReport
    graph: SocialGraph | None = None
    communities: tuple[Community, ...] = ()

    @model_validator(mode="after")
    def _personas_are_the_manifest(self) -> Self:
        if tuple(persona.persona_id for persona in self.personas) != self.manifest.persona_ids:
            raise ValueError("personas must be exactly the manifest's persona ids, in manifest order")
        return self

    @model_validator(mode="after")
    def _personas_conform_to_the_ontology(self) -> Self:
        ontology = self.pack.ontology
        for persona in self.personas:
            if set(persona.conditioning) != set(ontology.conditioning_set):
                raise ValueError(
                    f"{persona.persona_id} must be conditioned on exactly {sorted(ontology.conditioning_set)}, "
                    f"got {sorted(persona.conditioning)}"
                )
            undeclared = sorted(persona.projected_attributes - set(ontology.attribute_domains))
            if undeclared:
                raise ValueError(f"{persona.persona_id} projects attributes the ontology does not declare: {undeclared}")
            invented = sorted(
                attribute
                for attribute, origin in persona.origins.items()
                if origin is FieldOrigin.SYNTHESIZED and ontology.attribute_domains[attribute] in _NEVER_SYNTHESIZED
            )
            if invented:
                raise ValueError(f"{persona.persona_id} has synthesized demographic or psychographic fields: {invented}")
        return self

    @model_validator(mode="after")
    def _embeddings_are_distinct_positions_in_one_space(self) -> Self:
        spaces = {(persona.embedding.model_id, persona.embedding.dim) for persona in self.personas}
        if len(spaces) > 1:
            raise ValueError(f"persona embeddings come from more than one model or dimension: {sorted(spaces)}")
        positions = Counter(persona.embedding.index for persona in self.personas)
        shared = sorted(index for index, count in positions.items() if count > 1)
        if shared:
            raise ValueError(f"personas share embedding positions: {shared}")
        return self

    @model_validator(mode="after")
    def _achieved_mix_reports_every_declared_audience(self) -> Self:
        declared = {audience.name for audience in self.pack.brief.audiences}
        if declared and set(self.manifest.achieved_mix) != declared:
            raise ValueError(
                f"achieved mix must report every declared audience, including any not reached: "
                f"declared {sorted(declared)}, reported {sorted(self.manifest.achieved_mix)}"
            )
        return self

    @model_validator(mode="after")
    def _source_mix_matches_the_personas(self) -> Self:
        counts = Counter(persona.source for persona in self.personas)
        actual = {source: count / len(self.personas) for source, count in counts.items()}
        reported = dict(self.gate_report.source_mix)
        if set(reported) != set(actual) or any(abs(reported[s] - actual[s]) > 1e-6 for s in actual):
            raise ValueError(f"gate report source mix {reported} does not match the personas {actual}")
        return self

    @model_validator(mode="after")
    def _gates_run_on_declared_grounded_attributes(self) -> Self:
        ontology = self.pack.ontology
        scaled = {scale.attribute for scale in ontology.ordinal_scales}
        for result in self.gate_report.results:
            attribute = result.attribute
            if attribute not in ontology.attribute_domains:
                raise ValueError(f"gate on {attribute!r}, which the ontology does not declare")
            if (result.kind == "ordinal") != (attribute in scaled):
                expected = "ordinal" if attribute in scaled else "categorical"
                raise ValueError(f"gate on {attribute!r} must be {expected}, per the ontology's ordinal scales")
            carriers = [persona for persona in self.personas if attribute in persona.origins]
            if not carriers:
                raise ValueError(f"gate on {attribute!r}, which no persona carries")
            ungrounded = sorted(p.persona_id for p in carriers if p.origins[attribute] is not FieldOrigin.GROUNDED)
            if ungrounded:
                raise ValueError(f"gates run on grounded attributes only; {attribute!r} is not grounded for {ungrounded}")
        return self

    @model_validator(mode="after")
    def _graph_and_communities_cover_the_population(self) -> Self:
        members = set(self.manifest.persona_ids)
        if self.graph is not None:
            strangers = sorted({end for edge in self.graph.edges for end in (edge.u, edge.v)} - members)
            if strangers:
                raise ValueError(f"social graph ties personas outside the population: {strangers}")
        if not self.communities:
            return self
        if self.graph is None:
            raise ValueError("communities are discovered in the social graph, so they require one")
        ids = Counter(community.community_id for community in self.communities)
        repeated_ids = sorted(name for name, count in ids.items() if count > 1)
        if repeated_ids:
            raise ValueError(f"community ids repeated: {repeated_ids}")
        placements = Counter(member for community in self.communities for member in community.member_ids)
        overlapping = sorted(member for member, count in placements.items() if count > 1)
        unplaced = sorted(members - set(placements))
        outsiders = sorted(set(placements) - members)
        if overlapping or unplaced or outsiders:
            raise ValueError(
                "communities must partition the population: "
                f"in several {overlapping}, in none {unplaced}, not in the population {outsiders}"
            )
        return self
