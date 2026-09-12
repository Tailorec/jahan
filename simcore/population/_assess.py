"""`assess`: eligibility, a seeded sample, and the gates that judge it — no model and no cost.

Eligibility applies the category's conditioning filter before sampling, so a row missing any
conditioning attribute never enters the candidate pool (ADR 0002). Quotas follow the brief's
declared shares, and the gates compare what was drawn against the source population so a skew is
a verdict rather than a hidden property. `build` will continue from the same sample; `assess` is
the free check a user runs before spending anything on a model.
"""

import math
import random

import numpy as np
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from simcore.ports import CoresetSource
from simcore.ports.coreset import DecodedRow
from simcore.schemas import (
    AttributeId,
    BriefPack,
    CategoricalGateResult,
    CategoryTargets,
    GateReference,
    DistributionThresholds,
    FrozenDict,
    GateFailure,
    GateReport,
    Identifier,
    OrdinalGateResult,
    PopulationParameters,
    Relaxation,
)

from ._gates import chi_squared, counts_of, ordinal_similarity
from ._relax import resolve
from ._streams import spawn


@dataclass(frozen=True)
class Sampled:
    """One draw: the rows it took, what each audience held, and what the draw achieved.

    `build` continues from exactly this draw, so the free check `assess` makes and the population a run
    is built from can never disagree about which rows the study used."""

    rows: tuple[DecodedRow, ...]
    drawn: tuple[tuple[Identifier | None, str], ...]
    relaxations: tuple[Relaxation, ...]
    references: tuple[tuple[float, tuple[DecodedRow, ...]], ...]
    audiences: tuple[Identifier, ...]
    source_mix: FrozenDict
    achieved_mix: FrozenDict


def sample(pack: BriefPack, n: int, population_seed: int, *, coreset: CoresetSource) -> Sampled:
    """Eligibility, quotas, the relaxation ladder and one seeded draw per audience — the shared draw.

    A row missing any conditioning attribute never reaches a pool (ADR 0002), and the sampling stream is
    one of the three spawned from the population seed, so no graph draw can shift it."""
    if n < 1:
        raise ValueError(f"a study samples at least one persona, got n={n}")
    sampling_seed, _, _ = spawn(population_seed)
    brief, ontology = pack.brief, pack.ontology
    conditioning = tuple(sorted(ontology.conditioning_set))

    eligible = coreset.matching({}, present=conditioning)
    if not eligible:
        raise GateFailure("no row in the source carries every attribute the category's conditioning set requires")

    audiences = tuple(audience.name for audience in brief.audiences)
    shares = brief.audience_shares
    if audiences and shares is None:
        raise GateFailure("the brief declares audiences but no shares to sample them by")

    relaxations: tuple[Relaxation, ...] = ()
    if audiences:
        quotas = _quotas(shares, n, audiences)
        resolved = [
            (audience.name, quotas[audience.name], resolve(audience, quotas[audience.name], ontology, coreset, conditioning))
            for audience in brief.audiences
        ]
        drawn = _draw(resolved, sampling_seed)
        relaxations = tuple(relaxation for _, _, outcome in resolved for relaxation in outcome.relaxations)
    else:
        generator = random.Random(f"population-sample:{sampling_seed}:none")
        drawn = [(None, row_id) for row_id in generator.sample(list(eligible), k=min(n, len(eligible)))]

    if not drawn:
        raise GateFailure("no eligible row was drawn: every audience's eligible pool is empty")

    rows = {row.row_id: row for row in coreset.rows([row_id for _, row_id in drawn])}
    sample_rows = tuple(rows[row_id] for _, row_id in drawn)
    if audiences:
        references = tuple(
            (shares[name], tuple(_reference(outcome.pool, sampling_seed, name, coreset))) for name, _, outcome in resolved
        )
    else:
        references = ((1.0, tuple(_reference(eligible, sampling_seed, "population", coreset))),)

    return Sampled(
        rows=sample_rows,
        drawn=tuple(drawn),
        relaxations=relaxations,
        references=references,
        audiences=audiences,
        source_mix=_mix(Counter(row.source for row in sample_rows)),
        achieved_mix=_achieved_mix(drawn, audiences),
    )


def assess(
    pack: BriefPack,
    n: int,
    population_seed: int,
    *,
    coreset: CoresetSource,
    parameters: PopulationParameters = PopulationParameters(),
) -> GateReport:
    """Who is eligible, who was drawn, and whether the draw is sound, for `pack` sampling `n` personas.

    The gates test at the significance and similarity `parameters` set, and every result carries the
    threshold it was judged against, so a loosened gate is visible in the report it produced."""
    sampled = sample(pack, n, population_seed, coreset=coreset)
    return GateReport(
        results=_gate_results(
            pack.ontology, coreset, sampled.references, sampled.rows, parameters.distribution_gates, targets_for(pack, sampled)
        ),
        source_mix=sampled.source_mix,
        achieved_mix=sampled.achieved_mix,
        relaxations=sampled.relaxations,
    )


def _quotas(shares: Mapping[Identifier, float], n: int, order: Sequence[Identifier]) -> dict[Identifier, int]:
    """Whole quotas summing to `n`, by largest remainder, tie-broken by the brief's audience order."""
    raw = {name: shares[name] * n for name in order}
    quotas = {name: math.floor(raw[name]) for name in order}
    remainder = n - sum(quotas.values())
    for name in sorted(order, key=lambda name: (-(raw[name] - quotas[name]), order.index(name)))[:remainder]:
        quotas[name] += 1
    return quotas


def _draw(resolved, seed: int):
    """One seeded draw per audience, without replacement across the whole study: a persona is one row, so
    a row that satisfies two audiences is still drawn once."""
    drawn: list[tuple[Identifier | None, str]] = []
    used: set[str] = set()
    for name, quota, outcome in resolved:
        candidates = [row_id for row_id in outcome.pool if row_id not in used]
        generator = random.Random(f"population-sample:{seed}:{name}")
        chosen = generator.sample(candidates, k=min(quota, len(candidates)))
        used.update(chosen)
        drawn.extend((name, row_id) for row_id in chosen)
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


# The expectation is a distribution, so it is read from a bounded draw of each pool rather than from
# every row the pool holds: a study of two thousand must not scan a corpus of a million to be judged.
REFERENCE_CAP = 5_000


def _reference(pool: Sequence[str], seed: int, name: str, coreset: CoresetSource) -> list:
    """A bounded, seeded read of one pool, standing for its distribution."""
    if len(pool) > REFERENCE_CAP:
        generator = random.Random(f"population-reference:{seed}:{name}")
        pool = tuple(generator.sample(list(pool), k=REFERENCE_CAP))
    return list(coreset.rows(pool))


def _expected(references: Sequence[tuple[float, Sequence]], attribute: AttributeId, vocabulary: Sequence):
    """What the study's design implies for one attribute: each pool's distribution, weighted by the
    share the brief asked that audience to hold."""
    expected = np.zeros(len(vocabulary), dtype=float)
    for share, rows in references:
        counts = counts_of([row.values[attribute] for row in rows if attribute in row.values], vocabulary)
        if counts.sum() > 0:
            expected += share * counts / counts.sum()
    return expected


def targets_for(pack: BriefPack, sampled: Sampled) -> CategoryTargets | None:
    """The category targets a draw is judged against, or none.

    Only a study that declares no audiences means to resemble the whole category, so only it is held to the
    category's measured marginals. A targeted study is supposed to differ from the category — gym regulars
    are younger than everybody — and holding it to category targets would reject every study for doing what
    it was asked, the very defect gating against the corpus once had. It stays judged against its design."""
    return None if sampled.audiences else pack.ontology.targets


def _reference_for(attribute: AttributeId, vocabulary: Sequence, references, targets: CategoryTargets | None):
    """The expectation for one attribute and the reference it stands for: the category's measured marginal
    where one exists, otherwise what the study's design implies."""
    marginal = targets.marginals.get(attribute) if targets is not None else None
    if marginal is None:
        return _expected(references, attribute, vocabulary), GateReference.DESIGN
    return np.array([marginal.get(str(value), 0.0) for value in vocabulary], dtype=float), GateReference.CATEGORY_TARGETS


def _gate_results(
    ontology,
    coreset: CoresetSource,
    references: Sequence[tuple[float, Sequence]],
    sample_rows: Sequence,
    thresholds: DistributionThresholds,
    targets: CategoryTargets | None = None,
) -> tuple:
    scaled = {scale.attribute for scale in ontology.ordinal_scales}
    sample_values = _by_attribute(sample_rows)
    results = []
    for attribute in ontology.relevance_order:
        if attribute not in sample_values:
            continue
        vocabulary = coreset.values(attribute)
        if attribute in scaled:
            expected, reference = _reference_for(attribute, vocabulary, references, targets)
            outcome = ordinal_similarity(sample_values[attribute], expected, vocabulary)
            if outcome is not None:
                statistic, similarity = outcome
                results.append(
                    OrdinalGateResult(
                        kind="ordinal",
                        attribute=attribute,
                        ks_statistic=statistic,
                        ks_similarity=similarity,
                        similarity_threshold=thresholds.similarity_threshold,
                        reference=reference,
                    )
                )
        else:
            expected, reference = _reference_for(attribute, vocabulary, references, targets)
            outcome = chi_squared(sample_values[attribute], expected, vocabulary)
            if outcome is not None:
                statistic, degrees, p_value = outcome
                results.append(
                    CategoricalGateResult(
                        kind="categorical",
                        attribute=attribute,
                        chi_square=statistic,
                        degrees_of_freedom=degrees,
                        p_value=p_value,
                        significance_level=thresholds.significance_level,
                        reference=reference,
                    )
                )
    if not results:
        raise GateFailure("no declared attribute could be gated from the sample")
    return tuple(results)
