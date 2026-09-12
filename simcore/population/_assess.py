"""`assess`: eligibility, a seeded sample, and the gates that judge it — no model and no cost.

Eligibility applies the category's conditioning filter before sampling, so a row missing any
conditioning attribute never enters the candidate pool (ADR 0002). Quotas follow the brief's
declared shares, and the gates compare what was drawn against the source population so a skew is
a verdict rather than a hidden property. `build` will continue from the same sample; `assess` is
the free check a user runs before spending anything on a model.
"""

import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from simcore.ports import CoresetSource
from simcore.schemas import (
    AttributeId,
    BriefPack,
    CategoricalGateResult,
    FrozenDict,
    GateFailure,
    GateReport,
    Identifier,
    OrdinalGateResult,
)

from ._gates import chi_squared, ordinal_similarity


def assess(pack: BriefPack, n: int, population_seed: int, *, coreset: CoresetSource) -> GateReport:
    """Who is eligible, who was drawn, and whether the draw is sound, for `pack` sampling `n` personas."""
    if n < 1:
        raise ValueError(f"a study samples at least one persona, got n={n}")
    brief, ontology = pack.brief, pack.ontology
    conditioning = tuple(sorted(ontology.conditioning_set))

    population_ids = coreset.matching({}, present=())
    eligible = coreset.matching({}, present=conditioning)
    if not eligible:
        raise GateFailure("no row in the source carries every attribute the category's conditioning set requires")

    audiences = tuple(audience.name for audience in brief.audiences)
    shares = brief.audience_shares
    if audiences and shares is None:
        raise GateFailure("the brief declares audiences but no shares to sample them by")

    if audiences:
        pools = {audience.name: coreset.matching(audience.attribute_filters, present=conditioning) for audience in brief.audiences}
        quotas = _quotas(shares, n, audiences)
    else:
        pools = {None: eligible}
        quotas = {None: n}

    drawn = _draw(pools, quotas, population_seed)
    if not drawn:
        raise GateFailure("no eligible row was drawn: every audience's eligible pool is empty")

    rows = {row.row_id: row for row in coreset.rows([row_id for _, row_id in drawn])}
    sample_rows = [rows[row_id] for _, row_id in drawn]
    population_rows = list(coreset.rows(population_ids))

    return GateReport(
        results=_gate_results(ontology, coreset, population_rows, sample_rows),
        source_mix=_mix(Counter(row.source for row in sample_rows)),
        achieved_mix=_achieved_mix(drawn, audiences),
        relaxations=(),
    )


def _quotas(shares: Mapping[Identifier, float], n: int, order: Sequence[Identifier]) -> dict[Identifier, int]:
    """Whole quotas summing to `n`, by largest remainder, tie-broken by the brief's audience order."""
    raw = {name: shares[name] * n for name in order}
    quotas = {name: math.floor(raw[name]) for name in order}
    remainder = n - sum(quotas.values())
    for name in sorted(order, key=lambda name: (-(raw[name] - quotas[name]), order.index(name)))[:remainder]:
        quotas[name] += 1
    return quotas


def _draw(pools: Mapping[Identifier | None, Sequence[str]], quotas: Mapping[Identifier | None, int], seed: int):
    """One seeded draw per audience from its own eligible pool, in audience order."""
    drawn: list[tuple[Identifier | None, str]] = []
    for name in pools:
        pool = list(pools[name])
        generator = random.Random(f"population-sample:{seed}:{name}")
        for row_id in generator.sample(pool, k=min(quotas[name], len(pool))):
            drawn.append((name, row_id))
    return drawn


def _mix(counts: Counter) -> FrozenDict:
    total = sum(counts.values())
    return FrozenDict({name: count / total for name, count in counts.items()})


def _achieved_mix(drawn: Sequence[tuple[Identifier | None, str]], audiences: Sequence[Identifier]) -> FrozenDict:
    if not audiences:
        return FrozenDict({})
    counts = Counter(name for name, _ in drawn)
    total = sum(counts.values())
    return FrozenDict({name: counts.get(name, 0) / total for name in audiences})


def _by_attribute(rows: Sequence) -> Mapping[AttributeId, list]:
    values: dict[AttributeId, list] = defaultdict(list)
    for row in rows:
        for attribute, value in row.values.items():
            values[attribute].append(value)
    return values


def _gate_results(ontology, coreset: CoresetSource, population_rows: Sequence, sample_rows: Sequence) -> tuple:
    scaled = {scale.attribute for scale in ontology.ordinal_scales}
    population_values = _by_attribute(population_rows)
    sample_values = _by_attribute(sample_rows)
    results = []
    for attribute in ontology.relevance_order:
        if attribute not in sample_values:
            continue
        vocabulary = coreset.values(attribute)
        if attribute in scaled:
            outcome = ordinal_similarity(sample_values[attribute], population_values.get(attribute, []), vocabulary)
            if outcome is not None:
                statistic, similarity = outcome
                results.append(
                    OrdinalGateResult(kind="ordinal", attribute=attribute, ks_statistic=statistic, ks_similarity=similarity)
                )
        else:
            outcome = chi_squared(sample_values[attribute], population_values.get(attribute, []), vocabulary)
            if outcome is not None:
                statistic, degrees, p_value = outcome
                results.append(
                    CategoricalGateResult(
                        kind="categorical", attribute=attribute, chi_square=statistic, degrees_of_freedom=degrees, p_value=p_value
                    )
                )
    if not results:
        raise GateFailure("no declared attribute could be gated from the sample")
    return tuple(results)
