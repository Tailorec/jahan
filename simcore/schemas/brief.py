"""The brief domain: the study's inputs — product, claims, price, competitors,
target market, audiences, assumptions, and the category ontology that travels with them."""

from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import Field, HttpUrl, StringConstraints, field_validator, model_validator

from .base import FrozenDict, HashDigest, Identifier, NonEmptyStr, SimBaseModel, UnitInterval
from .enums import ClaimSource, PersonaFieldDomain

ClaimId = Annotated[str, StringConstraints(pattern=r"^C[1-9][0-9]*$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Evidence(SimBaseModel):
    url: HttpUrl
    fetched_at: datetime
    content_hash: HashDigest


class Claim(SimBaseModel):
    id: ClaimId
    text: NonEmptyStr
    source: ClaimSource
    evidence: Evidence | None = None


class Price(SimBaseModel):
    amount: Annotated[float, Field(gt=0.0)]
    currency: CurrencyCode


class Competitor(SimBaseModel):
    name: NonEmptyStr
    price: Price | None = None


class Audience(SimBaseModel):
    name: Identifier
    attribute_filters: FrozenDict[str, str]


class Assumption(SimBaseModel):
    text: NonEmptyStr
    source: ClaimSource


class OrdinalBand(SimBaseModel):
    label: NonEmptyStr
    midpoint: UnitInterval


class OrdinalScale(SimBaseModel):
    attribute: Identifier
    bands: tuple[OrdinalBand, ...]

    @model_validator(mode="after")
    def _bands_ascending(self) -> Self:
        if len(self.bands) < 2:
            raise ValueError("an ordinal scale needs at least two bands")
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


class CategoryOntology(SimBaseModel):
    category: Identifier
    version: Identifier
    conditioning_set: frozenset[Identifier] = Field(min_length=1)
    completion_policy: CompletionPolicy
    ordinal_scales: tuple[OrdinalScale, ...] = ()


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
    ontology: CategoryOntology

    @field_validator("claims", mode="before")
    @classmethod
    def _assign_claim_ids(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and value and all(
            isinstance(item, dict) and not item.get("id") for item in value
        ):
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
    def _ontology_matches_product_category(self) -> Self:
        if self.ontology.category != self.product.category:
            raise ValueError(
                f"ontology declares category {self.ontology.category!r} "
                f"but the product is {self.product.category!r}"
            )
        return self

    @property
    def audiences_declared(self) -> bool:
        return bool(self.audiences)
