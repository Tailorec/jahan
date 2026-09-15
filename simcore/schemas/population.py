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
    PositiveInt,
    SignedUnitInterval,
    SimBaseModel,
    UnitInterval,
    canonical_hash,
    canonical_payload,
    hash_payload,
    proportions_sum_to_one,
)
from .brief import AttributeFilter, AttributeId, BriefPack
from .enums import FieldOrigin, GateReference, GraphCheck, PersonaFieldDomain, RelaxationRung, weakest_origin
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
    # What this gate compared the sample against: the study's own design, or measured category targets.
    reference: GateReference = GateReference.DESIGN

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
    # What this gate compared the sample against: the study's own design, or measured category targets.
    reference: GateReference = GateReference.DESIGN

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
    # The tier each gated attribute was judged at. A gate is a claim about a distribution, and the claim
    # is only as strong as the evidence behind the values it compared; the attribute's tier travels
    # beside the result rather than on it, since a result is a statistic and a tier is a property of
    # what it was computed from.
    attribute_origins: FrozenDict[AttributeId, FieldOrigin] = FrozenDict({})
    # What the sample actually drew, keyed by audience, beside the mix the study asked for. Empty when
    # the brief declares no audiences. `build` carries the same mix on the manifest it persists.
    achieved_mix: FrozenDict[Identifier, UnitInterval] = FrozenDict({})
    # A shortfall caveats the sample; it is not a verdict, so it never moves `overall`.
    relaxations: tuple[Relaxation, ...] = ()
    # How strongly ties joined personas sharing each declared attribute, measured on the graph beside its
    # gates: -1 through 0 (no preference) to 1 (only like joins like). A measurement, not a verdict.
    assortativity: FrozenDict[AttributeId, SignedUnitInterval] = FrozenDict({})
    # How strongly ties stayed within the declared audiences — the value the assortativity ceiling judged —
    # or nothing when a study declares fewer than two audiences.
    audience_assortativity: SignedUnitInterval | None = None

    @model_validator(mode="after")
    def _source_mix_is_complete(self) -> Self:
        proportions_sum_to_one(self.source_mix)
        return self

    @model_validator(mode="after")
    def _attribute_origins_cover_exactly_the_gated_attributes(self) -> Self:
        gated = {result.attribute for result in self.results if result.kind != "graph"}
        if set(self.attribute_origins) != gated:
            missing = sorted(gated - set(self.attribute_origins))
            extra = sorted(set(self.attribute_origins) - gated)
            raise ValueError(
                f"attribute origins must cover exactly the gated attributes: missing {missing}, extra {extra}"
            )
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

    @computed_field
    @property
    def evidence(self) -> FieldOrigin:
        """The weakest tier among the gated attributes: a pass is never read as stronger evidence than its
        weakest gate rests on. A report with no distribution gate makes no distributional claim, so nothing
        weakens it."""
        return weakest_origin(self.attribute_origins.values()) or FieldOrigin.MEASURED

    @computed_field
    @property
    def reference(self) -> GateReference:
        """The claim the whole report supports, which is the weakest any distribution gate makes: category
        targets only when every distribution gate was judged against them, so a pass is never read as a
        claim that one of its gates did not make."""
        distribution = [result for result in self.results if result.kind != "graph"]
        if distribution and all(result.reference is GateReference.CATEGORY_TARGETS for result in distribution):
            return GateReference.CATEGORY_TARGETS
        return GateReference.DESIGN


def _subject(result: GateResult) -> tuple[str, str]:
    if result.kind == "graph":
        return ("graph", result.check.value)
    return (result.kind, result.attribute)


class GraphParameters(SimBaseModel):
    """What shapes the social structure. These are study parameters: they change what a study measures,
    so they are tunable, recorded on the manifest, and never read from the environment."""

    # The fraction of ties rewired toward attribute-similar partners — how much attributes shape the graph.
    homophily_strength: UnitInterval = 0.3
    # Ties per persona in the ring lattice that supplies clustering; even, since a ring ties both sides.
    ring_degree: PositiveInt = 4
    # Ties each newcomer makes under preferential attachment, which supplies the hub tail.
    hub_attachment: PositiveInt = 2

    @model_validator(mode="after")
    def _ring_ties_both_sides(self) -> Self:
        if self.ring_degree % 2:
            raise ValueError(f"a ring lattice ties each persona to both sides, so its degree is even, got {self.ring_degree}")
        return self


class GraphThresholds(SimBaseModel):
    """What a generated graph must reach to be accepted. Quality thresholds decide whether a population is
    used at all, so tuning one is recorded rather than silent."""

    clustering_floor: UnitInterval = 0.05
    connectivity_floor: UnitInterval = 0.98
    # Highest degree over mean degree; at least one by definition, so a floor at or below it judges nothing.
    hub_tail_floor: Annotated[float, Field(gt=1.0)] = 1.8
    # How far ties may follow the declared audiences before the graph merely restates them: attribute
    # assortativity runs from -1 through 0 (no preference) to 1 (every tie joins like to like).
    assortativity_ceiling: Annotated[float, Field(gt=0.0, le=1.0)] = 0.9


class CommunityThresholds(SimBaseModel):
    """When a discovered partition is substantial enough to call communities."""

    modularity_floor: UnitInterval = 0.4
    min_communities: Annotated[int, Field(ge=2)] = 4
    max_communities: Annotated[int, Field(ge=2)] = 8
    # A community's size floor is a share of the population, so it scales with the study.
    share_floor: OpenUnitInterval = 0.05
    resolutions: tuple[Annotated[float, Field(gt=0.0)], ...] = Field(default=(0.5, 0.75, 1.0, 1.25, 1.5), min_length=1)

    @model_validator(mode="after")
    def _a_qualifying_partition_is_possible(self) -> Self:
        if self.min_communities > self.max_communities:
            raise ValueError(f"at least {self.min_communities} and at most {self.max_communities} communities cannot both hold")
        if self.min_communities * self.share_floor > 1.0:
            raise ValueError(
                f"{self.min_communities} communities each holding {self.share_floor:.0%} of the population exceed it; "
                "no partition could ever qualify"
            )
        if list(self.resolutions) != sorted(set(self.resolutions)):
            raise ValueError("resolutions are searched in ascending order, each once")
        return self


class DistributionThresholds(SimBaseModel):
    """The significance a categorical gate tests at and the similarity an ordinal gate must reach."""

    significance_level: OpenUnitInterval = 0.05
    similarity_threshold: Annotated[float, Field(gt=0.0, le=1.0)] = 0.80


class PopulationParameters(SimBaseModel):
    """Every value that shapes a population or decides whether it is accepted, with the engine's defaults.

    A user may tune any of them; none is hard-coded where it cannot be seen. They travel on the manifest,
    so a study built with a tuned graph or a loosened gate says so wherever the population goes."""

    graph: GraphParameters = GraphParameters()
    graph_gates: GraphThresholds = GraphThresholds()
    communities: CommunityThresholds = CommunityThresholds()
    distribution_gates: DistributionThresholds = DistributionThresholds()
    # Which sources a study may draw from. None means every source the corpus holds; naming a subset is a
    # study parameter, recorded on the manifest, never read from the environment. A union is permitted and
    # never silent: the preview shows the mix and the weakest-tier rule grades it (ADR 0017, ADR 0020).
    admissible_sources: frozenset[PersonaSource] | None = None

    @model_validator(mode="after")
    def _admissible_is_never_empty(self) -> Self:
        if self.admissible_sources is not None and not self.admissible_sources:
            raise ValueError("admissible_sources is either a non-empty set of sources or nothing at all")
        return self


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
    # Everything that shaped this population or decided its acceptance, defaults included, so tuning is visible.
    parameters: PopulationParameters = PopulationParameters()
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
# The tiers a distribution gate may judge: a value an instrument recorded or a model read from corpus
# text. A synthesized or calibrated value is not gateable, because the gate would judge an invention.
_GATEABLE_TIERS = frozenset({FieldOrigin.MEASURED, FieldOrigin.EXTRACTED})


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
    def _gates_run_on_declared_gateable_attributes(self) -> Self:
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
            ungateable = sorted(
                p.persona_id for p in carriers if p.origins[attribute] not in _GATEABLE_TIERS
            )
            if ungateable:
                raise ValueError(
                    f"gates run on measured or extracted attributes only; {attribute!r} is neither for {ungateable}"
                )
        for attribute, tier in self.gate_report.attribute_origins.items():
            carried = [p.origins[attribute] for p in self.personas if attribute in p.origins]
            actual = weakest_origin(carried)
            if actual is not tier:
                held = actual.value if actual is not None else "absent"
                raise ValueError(
                    f"the gate report states {attribute!r} as {tier.value}, but the population carries it as {held}"
                )
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

    @model_validator(mode="after")
    def _assortativity_is_measured_on_the_graph_over_declared_attributes(self) -> Self:
        report = self.gate_report
        if (report.assortativity or report.audience_assortativity is not None) and self.graph is None:
            raise ValueError("assortativity is measured on the social graph, so a population without one reports none")
        undeclared = sorted(set(report.assortativity) - set(self.pack.ontology.attribute_domains))
        if undeclared:
            raise ValueError(f"assortativity reported for attributes the ontology does not declare: {undeclared}")
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
