"""The brief domain: the study's inputs — product, claims, price, competitors, target market,
audiences, assumptions — and the category ontology a brief is read against."""

import re
from typing import Annotated, Any, ClassVar, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from .base import FrozenDict, HashDigest, Identifier, NonEmptyStr, SimBaseModel, UnitInterval
from .enums import ClaimSource, PersonaFieldDomain

ClaimId = Annotated[str, StringConstraints(pattern=r"^C[1-9][0-9]*$")]
ConstructId = Identifier
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
AttributeId = Identifier

# An ontology a study ran against must resolve forever, so `latest`, a wildcard segment or a range
# is refused for the same reason model pins refuse them.
_FLOATING_VERSION = re.compile(r"(^|[/:@._-])latest$", re.IGNORECASE)
_VERSION_WILDCARD = re.compile(r"(?:^|[._-])[xX](?:[._-]|$)")


def _exact_version(value: str) -> str:
    if _FLOATING_VERSION.search(value) or _VERSION_WILDCARD.search(value):
        raise ValueError(f"an ontology version must name an exact version, got floating {value!r}")
    return value


OntologyVersion = Annotated[Identifier, AfterValidator(_exact_version)]


class Evidence(SimBaseModel):
    # The content hash is the evidence's identity; when it was fetched is provenance and must not move a hash.
    _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"fetched_at"})

    url: HttpUrl
    fetched_at: AwareDatetime
    content_hash: HashDigest


class Claim(SimBaseModel):
    id: ClaimId
    text: NonEmptyStr
    source: ClaimSource
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def _evidence_matches_its_source(self) -> Self:
        if self.source is ClaimSource.PUBLIC_SOURCE and self.evidence is None:
            raise ValueError("a claim drawn from a public source must carry the evidence it was drawn from")
        if self.source is ClaimSource.ASSUMED and self.evidence is not None:
            raise ValueError("an assumed claim is taken as true without evidence, so it cannot carry evidence")
        return self


class Price(SimBaseModel):
    amount: Annotated[float, Field(gt=0.0)]
    currency: CurrencyCode


class Competitor(SimBaseModel):
    name: NonEmptyStr
    price: Price | None = None
    claims: tuple[NonEmptyStr, ...] = ()


FilterValue = str | int | float


class Exactly(SimBaseModel):
    """A filter matches one attribute value."""

    value: FilterValue


class OneOf(SimBaseModel):
    """A filter matches any of several attribute values."""

    values: tuple[FilterValue, ...] = Field(min_length=1)


class BandRange(SimBaseModel):
    """A filter matches the ordinal bands from `first` to `last`, inclusive, in declared band order."""

    first: NonEmptyStr
    last: NonEmptyStr


def _as_predicate(value: Any) -> Any:
    """Read an authored filter: an exact scalar, a list of alternatives, or `range: [first, last]`."""
    if isinstance(value, (list, tuple)):
        return {"values": list(value)}
    if isinstance(value, dict) and set(value) == {"range"}:
        bounds = value["range"]
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            return {"first": bounds[0], "last": bounds[1]}
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return {"value": value}
    return value


AttributeFilter = Annotated[Exactly | OneOf | BandRange, BeforeValidator(_as_predicate)]


class Audience(SimBaseModel):
    name: Identifier
    # All audiences of a brief declare a share or none do; the brief checks that and the total.
    share: UnitInterval | None = None
    attribute_filters: FrozenDict[AttributeId, AttributeFilter]


class Assumption(SimBaseModel):
    text: NonEmptyStr
    source: ClaimSource


class OrdinalBand(SimBaseModel):
    label: NonEmptyStr
    midpoint: float


class OrdinalScale(SimBaseModel):
    attribute: AttributeId
    bands: tuple[OrdinalBand, ...]

    @model_validator(mode="after")
    def _bands_distinct_and_ascending(self) -> Self:
        if len(self.bands) < 2:
            raise ValueError("an ordinal scale needs at least two bands")
        labels = [band.label for band in self.bands]
        if len(set(labels)) != len(labels):
            duplicated = sorted({label for label in labels if labels.count(label) > 1})
            raise ValueError(f"ordinal band labels duplicated: {duplicated}")
        midpoints = [band.midpoint for band in self.bands]
        if any(lower >= upper for lower, upper in zip(midpoints, midpoints[1:])):
            raise ValueError("ordinal bands must be strictly ascending by midpoint")
        return self


class CompletionPolicy(SimBaseModel):
    completable_domains: frozenset[PersonaFieldDomain]

    @model_validator(mode="after")
    def _never_demographic_or_psychographic(self) -> Self:
        never = {PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC}
        listed = self.completable_domains & never
        if listed:
            raise ValueError(
                f"completion policy may never list {sorted(member.value for member in listed)}: "
                "demographics and psychographics are never synthesized"
            )
        return self


class OntologyDrafting(SimBaseModel):
    """Which model drafted an ontology, from which corpus codebook, and when.

    This is provenance, not identity: it is hash-excluded so redrafting or correcting the record never
    moves what studies pinned against the ontology (ADR 0014)."""

    model_id: Identifier
    codebook: Identifier
    drafted_at: AwareDatetime


class CategoryTargets(SimBaseModel):
    """How a category's real population is distributed on some of its attributes, and where that was measured.

    A gate judged against these makes the strongest claim a sample can support — that it matches the
    category, not merely the study's own design — so targets name their source, as any claim of realism
    must bring its evidence. Changing them is a new ontology version, so studies stay comparable."""

    source: NonEmptyStr
    marginals: FrozenDict[AttributeId, FrozenDict[NonEmptyStr, UnitInterval]] = Field(min_length=1)

    @model_validator(mode="after")
    def _each_marginal_is_a_distribution(self) -> Self:
        for attribute, shares in self.marginals.items():
            if len(shares) < 2:
                raise ValueError(f"a target marginal for {attribute!r} spans at least two values, got {sorted(shares)}")
            total = sum(shares.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"the target marginal for {attribute!r} must sum to one, got {total}")
        return self


class CategoryOntology(SimBaseModel):
    """The shared, versioned description of a category; a brief refers to it, never embeds it."""

    _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"drafting"})

    category: Identifier
    version: OntologyVersion
    attribute_domains: FrozenDict[AttributeId, PersonaFieldDomain]
    conditioning_set: frozenset[AttributeId] = Field(min_length=1)
    completion_policy: CompletionPolicy
    ordinal_scales: tuple[OrdinalScale, ...] = ()
    # Most relevant first. A prompt cut to a token budget drops from the end, so the conditioning set leads it.
    relevance_order: tuple[AttributeId, ...] = Field(min_length=1)
    # The anchor set each construct is scored against, so a study cannot be scored against another category's.
    anchor_sets: FrozenDict[ConstructId, Identifier] = Field(min_length=1)
    # Measured marginals of the category's real population, where anyone has measured them. A study that
    # declares no audiences is gated against these rather than against its own design.
    targets: CategoryTargets | None = None
    # Hash-excluded provenance: which model drafted this ontology, and when (ADR 0014).
    drafting: OntologyDrafting | None = None

    @model_validator(mode="after")
    def _referenced_attributes_declare_a_domain(self) -> Self:
        referenced = set(self.conditioning_set) | {scale.attribute for scale in self.ordinal_scales}
        undeclared = referenced - set(self.attribute_domains)
        if undeclared:
            raise ValueError(f"attributes used by the ontology have no declared domain: {sorted(undeclared)}")
        return self

    @model_validator(mode="after")
    def _one_scale_per_attribute(self) -> Self:
        attributes = [scale.attribute for scale in self.ordinal_scales]
        if len(set(attributes)) != len(attributes):
            duplicated = sorted({name for name in attributes if attributes.count(name) > 1})
            raise ValueError(f"more than one ordinal scale declared for: {duplicated}")
        return self


    @model_validator(mode="after")
    def _targets_describe_declared_attributes_in_their_own_values(self) -> Self:
        if self.targets is None:
            return self
        undeclared = sorted(set(self.targets.marginals) - set(self.attribute_domains))
        if undeclared:
            raise ValueError(f"targets describe attributes the ontology does not declare: {undeclared}")
        bands = {scale.attribute: {band.label for band in scale.bands} for scale in self.ordinal_scales}
        for attribute, shares in self.targets.marginals.items():
            unknown = sorted(set(shares) - bands.get(attribute, set(shares)))
            if unknown:
                raise ValueError(
                    f"targets for {attribute!r} name values that are not its bands: {unknown}; bands {sorted(bands[attribute])}"
                )
        return self

    @model_validator(mode="after")
    def _relevance_ranks_every_attribute_once(self) -> Self:
        ranked, declared = list(self.relevance_order), set(self.attribute_domains)
        repeated = sorted({name for name in ranked if ranked.count(name) > 1})
        missing, unknown = sorted(declared - set(ranked)), sorted(set(ranked) - declared)
        if repeated or missing or unknown:
            raise ValueError(
                f"the relevance order ranks every declared attribute exactly once: unranked {missing}, "
                f"undeclared {unknown}, ranked more than once {repeated}"
            )
        return self

    @model_validator(mode="after")
    def _conditioning_attributes_lead_the_order(self) -> Self:
        for rank, attribute in enumerate(self.relevance_order):
            if attribute in self.conditioning_set and rank >= len(self.conditioning_set):
                outranking = [name for name in self.relevance_order[:rank] if name not in self.conditioning_set]
                raise ValueError(
                    f"conditioning attribute {attribute!r} is outranked by {outranking}; a prompt cut to its "
                    "budget drops only non-conditioning attributes, so the conditioning set leads the order"
                )
        return self


class Product(SimBaseModel):
    name: NonEmptyStr
    category: Identifier
    description: NonEmptyStr


class ProductBrief(SimBaseModel):
    product: Product
    price: Price
    claims: tuple[Claim, ...] = Field(min_length=1)
    competitors: tuple[Competitor, ...] = ()
    target_market: NonEmptyStr
    audiences: tuple[Audience, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    ontology_version: OntologyVersion

    @field_validator("claims", mode="before")
    @classmethod
    def _assign_claim_ids(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and all(isinstance(item, dict) and "id" not in item for item in value):
            return [{**item, "id": f"C{index + 1}"} for index, item in enumerate(value)]
        return value

    @model_validator(mode="after")
    def _claim_ids_contiguous(self) -> Self:
        expected = [f"C{index + 1}" for index in range(len(self.claims))]
        actual = [claim.id for claim in self.claims]
        if actual != expected:
            duplicated = sorted({claim_id for claim_id in actual if actual.count(claim_id) > 1})
            if duplicated:
                raise ValueError(f"claim identifiers duplicated: {duplicated}")
            raise ValueError(f"claim identifiers must be contiguous and ordered, expected {expected}, got {actual}")
        return self

    @model_validator(mode="after")
    def _audience_names_unique(self) -> Self:
        names = [audience.name for audience in self.audiences]
        if len(set(names)) != len(names):
            duplicated = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(f"audience names duplicated: {duplicated}")
        return self

    @model_validator(mode="after")
    def _audience_shares_are_all_or_nothing(self) -> Self:
        declared = [audience.share is not None for audience in self.audiences]
        if not any(declared):
            return self
        if not all(declared):
            raise ValueError("either every audience declares a share or none does")
        total = sum(audience.share for audience in self.audiences)
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"audience shares must sum to one, got {total}")
        return self

    @property
    def audiences_declared(self) -> bool:
        return bool(self.audiences)

    @property
    def audience_shares(self) -> FrozenDict[Identifier, UnitInterval] | None:
        """The shares the study asked for, or nothing when the brief declares no shares."""
        if any(audience.share is None for audience in self.audiences):
            return None
        return FrozenDict({audience.name: audience.share for audience in self.audiences})


class BriefPack(SimBaseModel):
    """A brief joined with the ontology it names: what the population module consumes."""

    brief: ProductBrief
    ontology: CategoryOntology

    @model_validator(mode="after")
    def _ontology_is_the_one_the_brief_names(self) -> Self:
        named = (self.brief.product.category, self.brief.ontology_version)
        packed = (self.ontology.category, self.ontology.version)
        if packed != named:
            raise ValueError(f"brief is read against ontology {named} but was packed with {packed}")
        return self

    @model_validator(mode="after")
    def _audience_filters_use_declared_attributes(self) -> Self:
        bands = {scale.attribute: [band.label for band in scale.bands] for scale in self.ontology.ordinal_scales}
        for audience in self.brief.audiences:
            for attribute, predicate in audience.attribute_filters.items():
                if attribute not in self.ontology.attribute_domains:
                    raise ValueError(
                        f"audience {audience.name!r} filters on {attribute!r}, "
                        f"which ontology {self.ontology.category}@{self.ontology.version} does not declare"
                    )
                labels = bands.get(attribute)
                if isinstance(predicate, BandRange):
                    if labels is None:
                        raise ValueError(
                            f"audience {audience.name!r} filters {attribute!r} by band range, "
                            f"but the ontology does not scale it"
                        )
                    for label in (predicate.first, predicate.last):
                        if label not in labels:
                            raise ValueError(
                                f"audience {audience.name!r} names band {label!r} of {attribute!r}, "
                                f"which is not one of its bands {sorted(labels)}"
                            )
                    if labels.index(predicate.first) > labels.index(predicate.last):
                        raise ValueError(
                            f"audience {audience.name!r} ranges {attribute!r} from {predicate.first!r} to "
                            f"{predicate.last!r}, which runs backwards in band order"
                        )
                elif isinstance(predicate, OneOf):
                    if labels is not None:
                        unknown = [value for value in predicate.values if value not in labels]
                        if unknown:
                            raise ValueError(
                                f"audience {audience.name!r} filters {attribute!r} on {unknown}, "
                                f"which are not among its bands {sorted(labels)}"
                            )
                elif labels is not None and predicate.value not in labels:
                    raise ValueError(
                        f"audience {audience.name!r} filters {attribute!r} on {predicate.value!r}, "
                        f"which is not one of its bands {sorted(labels)}"
                    )
        return self
