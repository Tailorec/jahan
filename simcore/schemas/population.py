"""The population domain: distribution gates, the sample manifest, the discovered social structure,
and the population that joins them with the brief and ontology they were built for."""

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, computed_field, model_validator

from .base import (
    FrozenDict,
    GraphHash,
    HashDigest,
    Identifier,
    NonNegativeInt,
    PersonaId,
    PopulationHash,
    SimBaseModel,
    UnitInterval,
    canonical_hash,
    canonical_payload,
    hash_payload,
    proportions_sum_to_one,
)
from .brief import AttributeFilter, AttributeId, BriefPack
from .enums import FieldOrigin, GateReference, GraphCheck, PersonaFieldDomain, RelaxationRung
from .persona import Persona, PersonaSource
from .run import PinnedModelId

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


class GraphGateResult(SimBaseModel):
    """A structural property of the social graph, judged against a target; it passes when it reaches it.

    Keyed by the check it performed rather than by an attribute, so a graph gate shares a report with
    distribution gates without pretending to be one."""

    kind: Literal["graph"]
    check: GraphCheck
    measured: float
    threshold: float

    @computed_field
    @property
    def passed(self) -> bool:
        return self.measured >= self.threshold


class Relaxation(SimBaseModel):
    """One rung climbed when an audience's quota could not be filled, recorded so the sample is legible.

    It travels on the gate report — that is already where "is this sample acceptable" is answered — and
    it caveats a population without rejecting it. The conditioning set is never a rung."""

    audience: Identifier
    rung: RelaxationRung
    attribute: AttributeId | None = None
    authored: AttributeFilter | None = None
    applied: AttributeFilter | None = None
    rows_before: NonNegativeInt
    rows_after: NonNegativeInt
    share_achieved: UnitInterval

    @model_validator(mode="after")
    def _rung_shapes_the_record(self) -> Self:
        if self.rung is RelaxationRung.WIDEN_ORDINAL:
            if self.attribute is None or self.authored is None or self.applied is None:
                raise ValueError("widening a predicate records the attribute and the filter as authored and as applied")
        elif self.rung is RelaxationRung.DROP_FILTER:
            if self.attribute is None or self.authored is None or self.applied is not None:
                raise ValueError("dropping a filter records the attribute and what was dropped, applying nothing")
        elif self.attribute is not None or self.authored is not None or self.applied is not None:
            raise ValueError("accepting a shortfall changes no filter")
        if self.rows_after < self.rows_before:
            raise ValueError("a relaxation never shrinks the pool it relaxes")
        return self


GateResult = Annotated[
    CategoricalGateResult | OrdinalGateResult | GraphGateResult, Field(discriminator="kind")
]


class GateReport(SimBaseModel):
    results: tuple[GateResult, ...] = Field(min_length=1)
    source_mix: FrozenDict[PersonaSource, UnitInterval]
    # What the sample actually drew, keyed by audience, beside the mix the study asked for. Empty when
    # the brief declares no audiences. `build` carries the same mix on the manifest it persists.
    achieved_mix: FrozenDict[Identifier, UnitInterval] = FrozenDict({})
    # A shortfall caveats the sample; it is not a verdict, so it never moves `overall`.
    relaxations: tuple[Relaxation, ...] = ()
    # What the results were judged against, so a pass is never read as a claim it does not make.
    reference: GateReference = GateReference.DESIGN

    @model_validator(mode="after")
    def _source_mix_is_complete(self) -> Self:
        proportions_sum_to_one(self.source_mix)
        return self

    @model_validator(mode="after")
    def _achieved_mix_is_complete(self) -> Self:
        if self.achieved_mix:
            proportions_sum_to_one(self.achieved_mix)
        return self

    @model_validator(mode="after")
    def _one_result_per_subject(self) -> Self:
        repeated = sorted(subject for subject, count in Counter(_subject(r) for r in self.results).items() if count > 1)
        if repeated:
            raise ValueError(f"more than one gate result for: {repeated}")
        return self

    @computed_field
    @property
    def overall(self) -> bool:
        return all(result.passed for result in self.results)


def _subject(result: GateResult) -> tuple[str, str]:
    if result.kind == "graph":
        return ("graph", result.check.value)
    return (result.kind, result.attribute)


class CompletionProvenance(SimBaseModel):
    """What produced the synthesized fields in a population, so invented data stays accountable even
    after the personas stop travelling with the manifest (ADR 0015)."""

    model_id: PinnedModelId
    template_id: Identifier
    template_hash: HashDigest


class PopulationManifest(SimBaseModel):
    """The light-weight record of a population: what travels with runs and traces in place of the personas.
    Its hashes are stated here and verified wherever the population itself is present."""

    population_hash: PopulationHash
    graph_hash: GraphHash | None = None
    population_seed: NonNegativeInt
    persona_ids: tuple[PersonaId, ...] = Field(min_length=1)
    # The mix the study asked for, beside the mix it got; the difference is a shortfall, told plainly.
    requested_mix: FrozenDict[Identifier, UnitInterval] = FrozenDict({})
    achieved_mix: FrozenDict[Identifier, UnitInterval]
    # The homophily strength the graph was generated with, so structure is explained rather than assumed.
    homophily_strength: UnitInterval = 0.0
    synthesized_share: UnitInterval = 0.0
    completion: CompletionProvenance | None = None

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

    @model_validator(mode="after")
    def _requested_mix_is_complete(self) -> Self:
        if self.requested_mix:
            proportions_sum_to_one(self.requested_mix)
        return self

    @model_validator(mode="after")
    def _synthesized_fields_name_their_producer(self) -> Self:
        if self.synthesized_share > 0 and self.completion is None:
            raise ValueError("a manifest reporting synthesized fields must name the model and template that produced them")
        if self.synthesized_share == 0 and self.completion is not None:
            raise ValueError("a manifest reporting no synthesized fields must not name a completion source")
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
    """The generated ties between personas. Its hash is derived from the ties themselves — each tie counted
    once, in either direction — so two different graphs can never share an identity."""

    edges: tuple[SocialEdge, ...]

    @model_validator(mode="after")
    def _each_tie_appears_once(self) -> Self:
        ties = Counter(frozenset((edge.u, edge.v)) for edge in self.edges)
        repeated = sorted(tuple(sorted(tie)) for tie, count in ties.items() if count > 1)
        if repeated:
            raise ValueError(f"social ties declared more than once, in either direction: {repeated}")
        return self

    @computed_field
    @property
    def graph_hash(self) -> str:
        ties = sorted((*sorted((edge.u, edge.v)), edge.weight + 0.0) for edge in self.edges)
        return hash_payload([list(tie) for tie in ties])


class Community(SimBaseModel):
    community_id: Identifier
    member_ids: tuple[PersonaId, ...] = Field(min_length=1)


_NEVER_SYNTHESIZED = frozenset({PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC})


def derive_population_hash(
    pack: BriefPack,
    population_seed: int,
    personas: Sequence[Persona],
    graph: SocialGraph | None,
    communities: Sequence[Community],
) -> str:
    """A population's identity: the brief and ontology it was built for, its seed, every persona, and the
    social structure among them. Gate results and the achieved mix are diagnostics of that, not part of it."""
    return hash_payload(
        {
            "brief": canonical_hash(pack.brief),
            "ontology": canonical_hash(pack.ontology),
            "population_seed": population_seed,
            "personas": [canonical_payload(persona) for persona in personas],
            "graph": graph.graph_hash if graph is not None else None,
            "communities": sorted(
                ([community.community_id, sorted(community.member_ids)] for community in communities),
                key=lambda entry: entry[0],
            ),
        }
    )


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

    @computed_field
    @property
    def population_hash(self) -> str:
        return derive_population_hash(self.pack, self.manifest.population_seed, self.personas, self.graph, self.communities)

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
    def _baseline_beliefs_credit_every_claim_of_the_brief(self) -> Self:
        claims = {claim.id for claim in self.pack.brief.claims}
        for persona in self.personas:
            held = set(persona.baseline_beliefs.claim_credence)
            if held != claims:
                raise ValueError(
                    f"{persona.persona_id} must hold baseline credence for exactly the brief's claims "
                    f"{sorted(claims)}, got {sorted(held)}"
                )
        return self

    @model_validator(mode="after")
    def _embeddings_are_distinct_positions_in_one_space(self) -> Self:
        present = [persona.embedding for persona in self.personas if persona.embedding is not None]
        spaces = {(embedding.model_id, embedding.dim) for embedding in present}
        if len(spaces) > 1:
            raise ValueError(f"persona embeddings come from more than one model or dimension: {sorted(spaces)}")
        positions = Counter(embedding.index for embedding in present)
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
            if result.kind == "graph":
                continue
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
            tied = {end for edge in self.graph.edges for end in (edge.u, edge.v)}
            isolated = sorted(members - tied)
            if isolated:
                raise ValueError(f"every persona has at least one social tie; isolated: {isolated}")
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

    # Runs last: every semantic check above names its own problem before the identity check catches the change.
    @model_validator(mode="after")
    def _manifest_hashes_are_this_populations(self) -> Self:
        if self.manifest.population_hash != self.population_hash:
            raise ValueError(f"manifest states population hash {self.manifest.population_hash}, but this population is {self.population_hash}")
        graph_hash = self.graph.graph_hash if self.graph is not None else None
        if self.manifest.graph_hash != graph_hash:
            raise ValueError(f"manifest states graph hash {self.manifest.graph_hash}, but this population's graph is {graph_hash}")
        return self
