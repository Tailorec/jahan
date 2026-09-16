"""`preview`: what the corpus holds, answered from an index and no rows at all.

The first stage of the pre-flight (ADR 0020). It turns a request into an `AudiencePreview` without
drawing a sample or reading a shard, so an author can learn what an audience would cost while it is
still cheap to change. The statistical verdict is `assess`; this answers the earlier question.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from simcore.ports import CoresetCatalog
from simcore.ports.catalog import AttributeCoverage
from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    Audience,
    AudiencePreview,
    BriefPack,
    FieldOrigin,
    FrozenDict,
    PersonaFieldDomain,
    PersonaSource,
    PopulationParameters,
    SourcePreview,
    weakest_origin,
)

from ._relax import resolve

_NEVER_SYNTHESIZED = frozenset({PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC})


@dataclass(frozen=True)
class PreviewRequest:
    """One thing an author wants to know before spending anything: for this brief, sampling `n`,
    matching these filters (one audience's), from these sources. Sources default to all the catalog
    holds; filters default to none, which previews the eligible population the conditioning set defines."""

    pack: BriefPack
    n: int
    filters: Mapping[AttributeId, AttributeFilter] = field(default_factory=dict)
    sources: tuple[PersonaSource, ...] | None = None
    parameters: PopulationParameters = PopulationParameters()

    def __post_init__(self) -> None:
        from pydantic import TypeAdapter

        adapter: TypeAdapter = TypeAdapter(AttributeFilter)
        object.__setattr__(
            self, "filters", FrozenDict({attribute: adapter.validate_python(predicate) for attribute, predicate in self.filters.items()})
        )


def preview(request: PreviewRequest, *, catalog: CoresetCatalog) -> AudiencePreview:
    """What the corpus holds for `request`, from the catalog alone."""
    if request.n < 1:
        raise ValueError(f"a preview samples at least one persona, got n={request.n}")
    pack, ontology = request.pack, request.pack.ontology
    sources = tuple(request.sources) if request.sources is not None else (tuple(request.parameters.admissible_sources) if request.parameters.admissible_sources is not None else catalog.sources())
    if not sources:
        raise ValueError("a preview needs at least one admissible source")

    conditioning = tuple(sorted(ontology.conditioning_set))
    declared = tuple(ontology.relevance_order)
    filters = dict(request.filters)
    undeclared = sorted(set(filters) - set(declared))
    if undeclared:
        raise ValueError(f"the preview filters on attributes the ontology does not declare: {undeclared}")

    required = tuple(sorted(set(conditioning) | set(filters)))
    coverage = catalog.coverage(declared, sources)
    carrying = _counts(catalog, {}, required)
    matched = _counts(catalog, filters, required)

    source_previews = tuple(
        SourcePreview(
            source=source,
            total=coverage[declared[0]][source].total,
            carrying=carrying.get(source, 0),
            matched=matched.get(source, 0),
            attributes=FrozenDict({attribute: coverage[attribute][source].tier for attribute in declared}),
            unexpressible=FrozenDict(
                {attribute: coverage[attribute][source].unexpressible for attribute in declared if coverage[attribute][source].unexpressible}
            ),
        )
        for source in sources
    )

    completable = tuple(
        attribute
        for attribute, domain in ontology.attribute_domains.items()
        if domain in ontology.completion_policy.completable_domains
        and domain not in _NEVER_SYNTHESIZED
        and attribute not in conditioning
    )
    synthesized = 0
    for source in sources:
        reached = matched.get(source, 0)
        if not reached:
            continue
        for attribute in completable:
            carried = _counts(catalog, filters, (*required, attribute)).get(source, 0)
            synthesized += max(0, reached - carried)

    matched_total = sum(matched.get(source, 0) for source in sources)
    projected = matched_total * len(declared)
    share = min(1.0, synthesized / projected) if projected else 0.0
    # The share is measured over the whole matched pool, but the count a study author reads is for the
    # draw they asked for: 38,000 fields across a pool says nothing about a study of 300.
    drawn = min(request.n, matched_total)
    synthesized = round(share * drawn * len(declared))

    relaxations = ()
    if filters:
        def match(candidate: dict[AttributeId, AttributeFilter]) -> tuple[str, ...]:
            return tuple("" for _ in range(int(catalog.count(candidate, conditioning, by_source=False))))

        forecast = resolve(
            Audience(name="preview", share=None, attribute_filters=filters),
            request.n,
            ontology,
            match,
            conditioning,
            raise_on_empty=False,
        )
        relaxations = forecast.relaxations

    return AudiencePreview(
        sources=source_previews,
        synthesized_fields=synthesized,
        synthesized_share=share,
        relaxations=relaxations,
        evidence=_grade(coverage, sources, declared),
    )


def _counts(
    catalog: CoresetCatalog, predicates: Mapping[AttributeId, AttributeFilter], present
) -> Mapping[PersonaSource, int]:
    counted = catalog.count(predicates, present, by_source=True)
    assert not isinstance(counted, int)
    return counted


def _grade(
    coverage: Mapping[AttributeId, Mapping[PersonaSource, AttributeCoverage]],
    sources: tuple[PersonaSource, ...],
    declared: tuple[AttributeId, ...],
) -> FieldOrigin:
    """The weakest tier among the attributes that are carried and therefore could be gated. A field that
    would be synthesized is not gated, so it does not enter the grade — the report is a claim about
    evidence behind the comparisons it makes, and synthesis is reported separately as a count."""
    tiers: list[FieldOrigin] = []
    for attribute in declared:
        present = [coverage[attribute][source].tier for source in sources if coverage[attribute][source].tier is not None]
        if present:
            tiers.append(weakest_origin(present))
    return weakest_origin(tiers) or FieldOrigin.MEASURED
