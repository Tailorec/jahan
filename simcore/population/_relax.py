"""The relaxation ladder: what happens when the people a study asked for are not there in the numbers.

A quota that cannot be filled climbs a fixed ladder — widen an ordinal predicate by one band (nearest
band first), then drop the least relevant non-conditioning filter by the ontology's own relevance
order, then accept the shortfall — and fails only when the audience matched nothing to begin with.
Every rung is a `Relaxation`, so a reader can reconstruct what was asked for, what was applied and
what was obtained. The conditioning set is never a rung: widening a value predicate keeps the
attribute required-present, and a conditioning attribute's filter is never dropped (ADR 0002)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    Audience,
    BandRange,
    CategoryOntology,
    Exactly,
    GateFailure,
    OneOf,
    Relaxation,
    RelaxationRung,
)

# How a pool is obtained: real row ids from a source, or one placeholder per match from a catalog, since
# the ladder only ever measures a pool by its size.
Match = Callable[[dict[AttributeId, AttributeFilter]], Sequence[str]]


@dataclass(frozen=True)
class ResolvedAudience:
    pool: tuple[str, ...]
    relaxations: tuple[Relaxation, ...]
    counts: tuple[tuple[str, int], ...]


def resolve(
    audience: Audience,
    quota: int,
    ontology: CategoryOntology,
    match: Match,
    conditioning: Sequence[AttributeId],
    *,
    raise_on_empty: bool = True,
) -> ResolvedAudience:
    """The audience's final eligible pool after climbing the ladder, and every rung it climbed.

    `raise_on_empty` is False for a forecast: a preview reports an audience that matches nobody rather
    than refusing a request the author has not committed to, so the zero is visible while it is cheap
    to change."""
    filters = dict(audience.attribute_filters)
    initial = tuple(match(filters))
    pool = initial
    relaxations: list[Relaxation] = []
    counts: list[tuple[str, int]] = [("initial", len(pool))]

    while len(pool) < quota:
        widened = _best_widening(filters, ontology, match, len(pool))
        if widened is None:
            break
        attribute, applied, candidate = widened
        _record(relaxations, audience, RelaxationRung.WIDEN_ORDINAL, attribute, filters[attribute], applied, pool, candidate, quota)
        filters[attribute] = applied
        pool = candidate
        counts.append(("widen_ordinal", len(pool)))

    while len(pool) < quota:
        droppable = [attribute for attribute in filters if attribute not in conditioning]
        if not droppable:
            break
        least_relevant = max(droppable, key=lambda attribute: ontology.relevance_order.index(attribute))
        authored = filters.pop(least_relevant)
        candidate = tuple(match(filters))
        _record(relaxations, audience, RelaxationRung.DROP_FILTER, least_relevant, authored, None, pool, candidate, quota)
        pool = candidate
        counts.append(("drop_filter", len(pool)))

    if len(pool) < quota:
        _record(relaxations, audience, RelaxationRung.ACCEPT_SHORTFALL, None, None, None, pool, pool, quota)
        counts.append(("accept_shortfall", len(pool)))

    if not initial and raise_on_empty:
        raise GateFailure(
            f"audience {audience.name!r} matches no rows at all: filters {dict(audience.attribute_filters)}; "
            f"counts at each rung: {counts}"
        )
    return ResolvedAudience(pool, tuple(relaxations), tuple(counts))


def _record(
    relaxations: list[Relaxation],
    audience: Audience,
    rung: RelaxationRung,
    attribute: AttributeId | None,
    authored: AttributeFilter | None,
    applied: AttributeFilter | None,
    before: tuple[str, ...],
    after: tuple[str, ...],
    quota: int,
) -> None:
    relaxations.append(
        Relaxation(
            audience=audience.name,
            rung=rung,
            attribute=attribute,
            authored=authored,
            applied=applied,
            rows_before=len(before),
            rows_after=len(after),
            share_achieved=min(len(after), quota) / quota,
        )
    )


def _best_widening(
    filters: dict[AttributeId, AttributeFilter],
    ontology: CategoryOntology,
    match: Match,
    current: int,
) -> tuple[AttributeId, AttributeFilter, tuple[str, ...]] | None:
    """The single-band widening that adds the most rows, most relevant attribute first on a tie."""
    chosen: tuple[AttributeId, AttributeFilter, tuple[str, ...]] | None = None
    chosen_size = current
    for attribute in ontology.relevance_order:
        if attribute not in filters:
            continue
        order = _band_order(ontology, attribute)
        if order is None:
            continue
        for candidate in _widenings(filters[attribute], order):
            candidate_pool = tuple(match({**filters, attribute: candidate}))
            if len(candidate_pool) > chosen_size:
                chosen, chosen_size = (attribute, candidate, candidate_pool), len(candidate_pool)
    return chosen


def _band_order(ontology: CategoryOntology, attribute: AttributeId) -> tuple[str, ...] | None:
    for scale in ontology.ordinal_scales:
        if scale.attribute == attribute:
            return tuple(band.label for band in scale.bands)
    return None


def _widenings(predicate: AttributeFilter, order: tuple[str, ...]) -> list[BandRange]:
    """Extend the predicate's band span by one band on either side, lower side first.

    A widening that would span every band is not offered: an audience whose filter covers the whole
    scale no longer means what its name says, and calling that a widening rather than a drop would
    hide it. The ladder moves on to its next rung instead."""
    span = _band_span(predicate, order)
    if span is None:
        return []
    low, high = span
    candidates = []
    if low > 0:
        candidates.append(BandRange(first=order[low - 1], last=order[high]))
    if high < len(order) - 1:
        candidates.append(BandRange(first=order[low], last=order[high + 1]))
    return [band for band in candidates if not _spans_every_band(band, order)]


def _spans_every_band(predicate: BandRange, order: tuple[str, ...]) -> bool:
    return order.index(predicate.first) == 0 and order.index(predicate.last) == len(order) - 1


def _band_span(predicate: AttributeFilter, order: tuple[str, ...]) -> tuple[int, int] | None:
    if isinstance(predicate, BandRange):
        return order.index(predicate.first), order.index(predicate.last)
    if isinstance(predicate, Exactly):
        if predicate.value not in order:
            return None
        return order.index(predicate.value), order.index(predicate.value)
    if isinstance(predicate, OneOf):
        positions = sorted(order.index(value) for value in predicate.values if value in order)
        return (positions[0], positions[-1]) if positions else None
    return None
