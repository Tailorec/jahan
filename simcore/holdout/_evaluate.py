"""The holdout evaluation itself: hide measured attitudes, project them through the production path,
and score the result against the truth and against a demographic-conditional baseline.

Held-out rows never touch the baseline: the baseline is what a statistician would build from the data
they had, and a baseline that peeked at the answers would measure nothing. The report records the pins,
served models, seeds, completion temperature and row counts that produced every number in it."""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from simcore.population._project import project
from simcore.ports import ChatPort, CoresetSource
from simcore.ports.coreset import DecodedRow, RowId
from simcore.schemas import BriefPack, FieldOrigin


@dataclass(frozen=True)
class AttributeScore:
    """How projection did on one hidden attitude, beside how the baseline did on the same rows."""

    vocabulary: tuple[str, ...]
    projected_rows: int
    # The headline scores: proper scoring rules of the stated distribution against the recorded answer.
    # They reward a distribution for being both right and sharp, so an uninformative one cannot win.
    log_loss: float | None  # mean negative log probability given to the recorded answer (floored at 1e-6)
    brier: float | None  # mean squared distance between the stated distribution and the recorded answer
    marginal_distance: float  # total variation between projected and true marginals — blind to demographics
    calibration_error: float  # expected-minus-observed accuracy — perfect for uniform guessing, never a score alone
    recovered_dependence: float | None  # share of the attitude's demographic dependence regained, bias-corrected
    baseline_log_loss: float | None
    baseline_brier: float | None
    baseline_marginal_distance: float
    baseline_calibration_error: float | None
    baseline_recovered_dependence: float | None


@dataclass
class HoldoutReport:
    hidden: tuple[str, ...]
    information: str  # which arm: what projection and its baseline were both allowed to see
    projected_from: tuple[str, ...]
    holdout_seed: int
    population_seed: int
    completion_temperature: float
    pool_rows: int
    held_out_rows: int
    inference: str
    pins: Mapping[str, Any]
    served_models: Mapping[str, tuple[str, ...]]
    attributes: Mapping[str, AttributeScore] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True, default=str)


def select_measured_rows(rows: Sequence[DecodedRow], attributes: Sequence[str]) -> list[DecodedRow]:
    """Only rows on which every hidden attribute was recorded by an instrument can be hidden and scored:
    an extracted attitude is a claim about corpus text, not a measurement to hold out against."""
    wanted = set(attributes)
    return [
        row
        for row in rows
        if wanted <= set(row.values)
        and all(row.tiers.get(attribute, FieldOrigin.MEASURED) is FieldOrigin.MEASURED for attribute in wanted)
    ]


def evaluate(
    pack: BriefPack,
    coreset: CoresetSource,
    rows: Sequence[DecodedRow],
    *,
    hidden: Sequence[str],
    inference: ChatPort,
    holdout_seed: int,
    population_seed: int | None = None,
    completion_temperature: float = 1.0,
    holdout_share: float = 0.25,
    inference_label: str = "fake",
    pins: Mapping[str, Any] | None = None,
    served_models: Mapping[str, Sequence[str]] | None = None,
    information: str = "demographics",
) -> HoldoutReport:
    """The whole evaluation: split, hide, project, score, and state every choice the numbers rest on.

    `information` decides what projection may see, and the baseline always sees exactly the same. Under
    `demographics` — the question ADR 0019 asks — projection is given only the conditioning set. Under `all` it
    is given every other declared attribute, and the baseline conditions on those too. A first real run gave
    projection every known attribute and the baseline only demographics: `coding_ai_sentiment` rode along for
    100 of 115 personas and nearly is `att_ai`, so a model "beat" the baseline by reading a near-copy of the
    answer while the comparison claimed to measure demographics."""
    if information not in INFORMATION_ARMS:
        raise ValueError(f"information must be one of {sorted(INFORMATION_ARMS)}, got {information!r}")
    hidden = tuple(hidden)
    candidates = select_measured_rows(rows, hidden)
    if len(candidates) < 8:
        raise ValueError(f"the holdout needs rows carrying every hidden attitude as measured; found {len(candidates)}")
    holdout_ids = _draw_holdout(candidates, holdout_seed, holdout_share)
    held_out = [row for row in candidates if row.row_id in holdout_ids]
    pool = [row for row in candidates if row.row_id not in holdout_ids]
    ontology = pack.ontology
    conditioning = tuple(sorted(ontology.conditioning_set))
    seen = conditioning if information == "demographics" else tuple(sorted(set(ontology.attribute_domains) - set(hidden)))

    # The answers are hidden before the projection path ever sees the rows, and projection sees exactly the
    # attributes the arm allows; the baseline is built from the pool alone on the same attributes, so no
    # held-out value informs the comparison and neither side knows what the other does not.
    visible = [_restrict(row, seen) for row in held_out]
    projection = project(
        pack,
        visible,
        coreset,
        inference=inference,
        population_seed=population_seed if population_seed is not None else holdout_seed,
        completion_temperature=completion_temperature,
        evaluatable=frozenset(hidden),
    )
    projected_by_id = {persona.persona_id: persona for persona in projection.personas}

    scores: dict[str, AttributeScore] = {}
    for attribute in hidden:
        vocabulary = tuple(str(value) for value in coreset.values(attribute))
        truth = [row.values[attribute] for row in held_out if attribute in row.values]
        predicted: list[Any] = []
        assigned: list[float] = []
        correct: list[bool] = []
        known: list[dict[str, Any]] = []
        stated: list[tuple[Sequence[float], int]] = []
        for row in held_out:
            persona = projected_by_id.get(f"p-{row.row_id}")
            value = persona.attributes.get(attribute) if persona is not None else None
            if value is None:
                continue
            predicted.append(value)
            distribution = persona.completed_distributions.get(attribute)
            if distribution is not None:
                name = str(value)
                assigned.append(distribution.probabilities[distribution.values.index(name)] if name in distribution.values else 0.0)
                correct.append(value == row.values[attribute])
                recorded = str(row.values[attribute])
                if tuple(distribution.values) == vocabulary and recorded in vocabulary:
                    stated.append((distribution.probabilities, vocabulary.index(recorded)))
            known.append({key: str(row.values[key]) for key in conditioning if key in row.values})
        truth_known = [
            {key: str(row.values[key]) for key in conditioning if key in row.values}
            for row in held_out
        ]
        cells = _BaselineCells(pool, attribute, seen, conditioning)
        baseline_predicted, baseline_assigned, baseline_correct = _baseline_draws(held_out, attribute, vocabulary, holdout_seed, cells)
        baseline_stated = _baseline_distributions(held_out, attribute, vocabulary, cells)
        dependence_seed = f"{holdout_seed}|{attribute}"
        scores[attribute] = AttributeScore(
            vocabulary=vocabulary,
            projected_rows=len(predicted),
            log_loss=_log_loss(stated),
            brier=_brier(stated, len(vocabulary)),
            baseline_log_loss=_log_loss(baseline_stated),
            baseline_brier=_brier(baseline_stated, len(vocabulary)),
            marginal_distance=_marginal_distance(predicted, truth, vocabulary) if predicted else 1.0,
            calibration_error=_calibration(assigned, correct) if assigned else 1.0,
            recovered_dependence=_recovered_dependence(known, predicted, truth_known, truth, vocabulary, seed=dependence_seed),
            baseline_marginal_distance=_marginal_distance(baseline_predicted, truth, vocabulary),
            baseline_calibration_error=_calibration(baseline_assigned, baseline_correct) if baseline_assigned else None,
            baseline_recovered_dependence=_recovered_dependence(
                truth_known, baseline_predicted, truth_known, truth, vocabulary, seed=dependence_seed
            ),
        )
    return HoldoutReport(
        hidden=hidden,
        information=information,
        projected_from=seen,
        holdout_seed=holdout_seed,
        population_seed=population_seed if population_seed is not None else holdout_seed,
        completion_temperature=completion_temperature,
        pool_rows=len(pool),
        held_out_rows=len(held_out),
        inference=inference_label,
        pins=dict(pins or {}),
        served_models={model: tuple(sorted(served)) for model, served in (served_models or {}).items()},
        attributes=scores,
    )


def _draw_holdout(rows: Sequence[DecodedRow], seed: int, share: float) -> set[RowId]:
    """A deterministic draw of which rows are held out, from the holdout seed alone."""
    count = max(4, round(len(rows) * share))
    order = sorted(
        range(len(rows)),
        key=lambda index: hashlib.sha256(f"{seed}|{rows[index].row_id}".encode()).digest(),
    )
    return {rows[index].row_id for index in order[:count]}


def _restrict(row: DecodedRow, seen: Sequence[str]) -> DecodedRow:
    """The row as the arm lets projection see it: only the allowed attributes, the hidden ones never among them."""
    allowed = set(seen)
    values = {key: value for key, value in row.values.items() if key in allowed}
    return DecodedRow(row_id=row.row_id, source=row.source, values=values, tiers=row.tiers)


INFORMATION_ARMS = frozenset({"demographics", "all"})
# A pool cell must hold this many rows to stand for its own marginal; thinner cells back off to the demographic
# cell, then to the whole pool. Conditioning on every known attribute otherwise leaves most cells nearly empty,
# and a baseline fitted to one or two rows would be as misleading as a leak.
MIN_CELL_ROWS = 5


class _BaselineCells:
    """Each pool marginal of the hidden attribute, keyed by the arm's attributes, with backoff to thinner keys."""

    def __init__(self, pool: Sequence[DecodedRow], attribute: str, seen: Sequence[str], conditioning: Sequence[str]) -> None:
        self._levels = [tuple(seen)] if tuple(seen) == tuple(conditioning) else [tuple(seen), tuple(conditioning)]
        self._cells: list[dict[tuple, Counter]] = [defaultdict(Counter) for _ in self._levels]
        self.overall: Counter = Counter()
        for row in pool:
            value = row.values.get(attribute)
            if value is None:
                continue
            self.overall[str(value)] += 1
            for level, keys in enumerate(self._levels):
                self._cells[level][_key(row, keys)][str(value)] += 1

    def marginal(self, row: DecodedRow) -> Counter:
        for level, keys in enumerate(self._levels):
            counts = self._cells[level].get(_key(row, keys))
            if counts is not None and sum(counts.values()) >= MIN_CELL_ROWS:
                return counts
        return self.overall


def _key(row: DecodedRow, keys: Sequence[str]) -> tuple:
    return tuple((name, str(row.values[name]) if name in row.values else None) for name in keys)




def _baseline_draws(
    held_out: Sequence[DecodedRow],
    attribute: str,
    vocabulary: tuple[str, ...],
    seed: int,
    cells: "_BaselineCells",
) -> tuple[list[Any], list[float], list[bool]]:
    """Sample each held-out row's attitude from its cell's marginal in the pool, keyed by exactly the attributes the
    arm let projection see. The pool alone decides every marginal, and a value that never appears in the pool draws
    nothing rather than a guess."""
    predicted: list[Any] = []
    assigned: list[float] = []
    correct: list[bool] = []
    for row in held_out:
        distribution = cells.marginal(row)
        total = sum(distribution.values())
        if not total:
            continue
        probabilities = [distribution.get(name, 0) / total for name in vocabulary]
        material = f"baseline|{seed}|{row.row_id}|{attribute}".encode("utf-8")
        child = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        index = int(np.random.default_rng(child).choice(len(vocabulary), p=np.asarray(probabilities, dtype=np.float64)))
        drawn = vocabulary[index]
        predicted.append(drawn)
        assigned.append(probabilities[index])
        correct.append(drawn == str(row.values.get(attribute)))
    return predicted, assigned, correct


def _marginal_distance(predicted: Sequence[Any], truth: Sequence[Any], vocabulary: tuple[str, ...]) -> float:
    """Total variation between the projected and true marginals over the hidden attribute's vocabulary."""
    left = _marginal(predicted, vocabulary)
    right = _marginal(truth, vocabulary)
    return 0.5 * sum(abs(a - b) for a, b in zip(left, right, strict=True))


def _marginal(values: Sequence[Any], vocabulary: tuple[str, ...]) -> list[float]:
    counts = Counter(str(value) for value in values)
    total = sum(counts.get(name, 0) for name in vocabulary) or 1
    return [counts.get(name, 0) / total for name in vocabulary]


def _calibration(assigned: Sequence[float], correct: Sequence[bool]) -> float:
    """Expected-minus-observed accuracy over ten probability bins: a well-calibrated projection is
    right as often as it says it will be."""
    bins: list[tuple[list[float], list[bool]]] = [([], []) for _ in range(10)]
    for probability, hit in zip(assigned, correct, strict=True):
        bins[min(9, int(probability * 10))][0].append(probability)
        bins[min(9, int(probability * 10))][1].append(hit)
    total = len(assigned)
    return sum(
        (len(probabilities) / total) * abs(sum(probabilities) / len(probabilities) - sum(hits) / len(hits))
        for probabilities, hits in bins
        if probabilities
    )


def _recovered_dependence(
    known: Sequence[Mapping[str, str]],
    predicted: Sequence[Any],
    truth_known: Sequence[Mapping[str, str]],
    truth: Sequence[Any],
    vocabulary: tuple[str, ...],
    *,
    seed: str,
) -> float | None:
    """The share of the attitude's mutual information with its demographic cells that the projection
    regains, both measured above what chance alone produces. When the truth carries no dependence beyond
    chance, nothing is recovered and nothing claims to.

    Mutual information counted over many sparse cells is biased upward: on Stack Overflow-sized samples
    with weak dependence, uniform guessing once scored 64% recovered. Subtracting the information the same
    values carry once shuffled across cells removes that bias."""
    true_mi = _dependence_above_chance(truth_known, [str(value) for value in truth], f"{seed}|truth")
    if true_mi <= 1e-9:
        return None
    predicted_mi = _dependence_above_chance(list(known), [str(value) for value in predicted], f"{seed}|predicted")
    return min(1.0, predicted_mi / true_mi)


# How many shuffles estimate the information chance alone puts between values and cells.
NULL_PERMUTATIONS = 20


def _dependence_above_chance(keys: Sequence[Mapping[str, str]], values: Sequence[str], seed: str) -> float:
    if not keys:
        return 0.0
    plugin = _mutual_information(keys, values)
    generator = np.random.default_rng(int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big"))
    null = float(np.mean([_mutual_information(keys, list(generator.permutation(list(values)))) for _ in range(NULL_PERMUTATIONS)]))
    return max(0.0, plugin - null)


# The least probability a stated distribution is charged for, so one zero cannot make a mean infinite.
LOG_LOSS_FLOOR = 1e-6


def _log_loss(stated: Sequence[tuple[Sequence[float], int]]) -> float | None:
    """Mean negative log probability given to the recorded answer: a proper scoring rule, so a sharp and
    right distribution beats a vague one and neither uniform guessing nor ignoring demographics can win."""
    if not stated:
        return None
    return float(np.mean([-np.log(max(float(probabilities[index]), LOG_LOSS_FLOOR)) for probabilities, index in stated]))


def _brier(stated: Sequence[tuple[Sequence[float], int]], width: int) -> float | None:
    """Mean squared distance between the stated distribution and the recorded answer, bounded where log
    loss is not."""
    if not stated:
        return None
    return float(np.mean([sum((float(p) - (1.0 if i == index else 0.0)) ** 2 for i, p in enumerate(probabilities)) for probabilities, index in stated]))


def _baseline_distributions(
    held_out: Sequence[DecodedRow],
    attribute: str,
    vocabulary: tuple[str, ...],
    cells: "_BaselineCells",
) -> list[tuple[list[float], int]]:
    """The baseline's stated distribution for each held-out row — its cell's marginal in the pool, keyed by the arm's
    attributes, with add-one smoothing so a value the cell never showed is improbable rather than impossible —
    beside the index of the recorded answer."""
    stated = []
    for row in held_out:
        recorded = row.values.get(attribute)
        if recorded is None or str(recorded) not in vocabulary:
            continue
        counts = cells.marginal(row)
        total = sum(counts.get(name, 0) for name in vocabulary) + len(vocabulary)
        stated.append(([(counts.get(name, 0) + 1) / total for name in vocabulary], vocabulary.index(str(recorded))))
    return stated


def _mutual_information(keys: Sequence[Mapping[str, str]], values: Sequence[str]) -> float:
    if not keys:
        return 0.0
    joint: Counter = Counter((tuple(sorted(row.items())), value) for row, value in zip(keys, values, strict=True))
    row_counts: Counter = Counter(tuple(sorted(row.items())) for row in keys)
    value_counts: Counter = Counter(values)
    total = len(keys)
    mi = 0.0
    for (row, value), count in joint.items():
        mi += (count / total) * np.log((count * total) / (row_counts[row] * value_counts[value]))
    return float(mi)
