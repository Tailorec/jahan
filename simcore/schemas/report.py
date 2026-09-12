"""The report domain: what the engine says — findings, trust, anomalies and outcome digests,
joined with the run configuration they describe."""

import math
from collections import Counter
from collections.abc import Iterable
from typing import Self

from pydantic import AwareDatetime, Field, computed_field, model_validator

from .base import (
    FrozenDict,
    HashDigest,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PositiveInt,
    SimBaseModel,
    UnitInterval,
    canonical_hash,
    proportions_sum_to_one,
)
from .enums import AnomalyKind, Confidence, FindingKind, TickUnit, TrustLevel
from .run import RunConfig
from .sim import PMF5
from .trace import EventId

# A benchmark must reach both floors before any calibrated trust level can be claimed — the same 0.80
# the engine's own ordinal distribution gate and reference-set rank-stability checks hold themselves to.
MIN_DISTRIBUTION_SIMILARITY = 0.80
MIN_RANK_ATTAINMENT = 0.80


def _repeated(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


class CalibrationRef(SimBaseModel):
    """Evidence that a calibrated trust level was earned: the benchmark report and the human study it was
    scored against, both pinned by content hash, and the measurements themselves. A prospective validation
    also records that its prediction was registered before the outcome was observed.

    Nothing in this repository produces one; a claim of calibration must bring its evidence from outside."""

    benchmark_report_hash: HashDigest
    human_study_hash: HashDigest
    category: Identifier
    distribution_similarity: UnitInterval
    rank_attainment: UnitInterval
    checked_at: AwareDatetime
    prediction_registered_at: AwareDatetime | None = None
    outcome_observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _prediction_precedes_outcome(self) -> Self:
        registered, observed = self.prediction_registered_at, self.outcome_observed_at
        if (registered is None) != (observed is None):
            raise ValueError("a prospective check records both when the prediction was registered and when the outcome was observed")
        if registered is not None and not registered < observed <= self.checked_at:
            raise ValueError("a prospective prediction must be registered before its outcome, and checked after it")
        return self

    @computed_field
    @property
    def meets_floors(self) -> bool:
        return self.distribution_similarity >= MIN_DISTRIBUTION_SIMILARITY and self.rank_attainment >= MIN_RANK_ATTAINMENT

    @property
    def prospective(self) -> bool:
        return self.prediction_registered_at is not None


class TrustStatement(SimBaseModel):
    """Calibration status, stated once per run — never per finding. An uncalibrated statement may still cite a
    benchmark that fell short; every level above it must cite one that met the floors."""

    level: TrustLevel
    calibration_ref: CalibrationRef | None = None
    caveats: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _levels_above_uncalibrated_require_evidence(self) -> Self:
        if self.level is TrustLevel.UNCALIBRATED:
            return self
        if self.calibration_ref is None:
            raise ValueError(f"{self.level.value} requires a calibration reference")
        if not self.calibration_ref.meets_floors:
            raise ValueError(
                f"{self.level.value} requires distribution similarity >= {MIN_DISTRIBUTION_SIMILARITY} and rank attainment "
                f">= {MIN_RANK_ATTAINMENT}; the cited benchmark measured {self.calibration_ref.distribution_similarity} "
                f"and {self.calibration_ref.rank_attainment}"
            )
        if self.level is TrustLevel.PROSPECTIVELY_VALIDATED and not self.calibration_ref.prospective:
            raise ValueError("prospectively_validated requires a prediction registered before its outcome was observed")
        return self


class Finding(SimBaseModel):
    """One statement the engine makes about what happened. It cannot exist without the trace records
    supporting it and the real-world test that would falsify it. A ranking names the scenarios it orders."""

    finding_id: Identifier
    kind: FindingKind
    statement: NonEmptyStr
    evidence_trace_ids: tuple[EventId, ...] = Field(min_length=1)
    disconfirming_test: NonEmptyStr
    confidence: Confidence
    ranked_scenarios: tuple[HashDigest, ...] = ()

    @model_validator(mode="after")
    def _evidence_cited_once(self) -> Self:
        if _repeated(self.evidence_trace_ids):
            raise ValueError(f"evidence cited more than once: {_repeated(self.evidence_trace_ids)}")
        return self

    @model_validator(mode="after")
    def _only_rankings_order_scenarios(self) -> Self:
        if self.kind is FindingKind.RANKING:
            if len(self.ranked_scenarios) < 2 or _repeated(self.ranked_scenarios):
                raise ValueError("a ranking orders at least two distinct scenarios, best first")
        elif self.ranked_scenarios:
            raise ValueError(f"a {self.kind.value} finding orders no scenarios")
        return self


class Anomaly(SimBaseModel):
    """A rule-based flag over one scenario's trace; it carries the evidence that produced it."""

    kind: AnomalyKind
    scenario_hash: HashDigest
    tick: NonNegativeInt
    evidence_trace_ids: tuple[EventId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_cited_once(self) -> Self:
        if _repeated(self.evidence_trace_ids):
            raise ValueError(f"evidence cited more than once: {_repeated(self.evidence_trace_ids)}")
        return self


class ObjectionCluster(SimBaseModel):
    """Verbatims clustered by embedding similarity around one recurring objection; the cited verbatims are
    a sample of the cluster, so the cluster is at least as large as what it cites."""

    label: NonEmptyStr
    verbatim_trace_ids: tuple[EventId, ...] = Field(min_length=1)
    size: PositiveInt

    @model_validator(mode="after")
    def _cites_a_distinct_sample(self) -> Self:
        if _repeated(self.verbatim_trace_ids):
            raise ValueError(f"verbatims cited more than once: {_repeated(self.verbatim_trace_ids)}")
        if self.size < len(self.verbatim_trace_ids):
            raise ValueError(f"a cluster of {self.size} cannot cite {len(self.verbatim_trace_ids)} verbatims")
        return self


def _entropy(mass: Iterable[float]) -> float:
    return -sum(p * math.log2(p) for p in mass if p > 0.0)


def _normalized_divergence(masses: list[tuple[float, ...]], weights: list[float]) -> float:
    """Weighted generalized Jensen-Shannon divergence, divided by its ceiling log2(n) so it lies in [0, 1]."""
    if len(masses) < 2:
        return 0.0
    total = sum(weights)
    shares = [weight / total for weight in weights]
    mixture = [sum(share * mass[point] for share, mass in zip(shares, masses)) for point in range(5)]
    divergence = _entropy(mixture) - sum(share * _entropy(mass) for share, mass in zip(shares, masses))
    return min(1.0, max(0.0, divergence / math.log2(len(masses))))


class OutcomeDigest(SimBaseModel):
    """What happened in one scenario's worlds. It carries response masses per audience with each audience's
    share, and per community with each community's size; adoption, polarization and audience divergence are
    computed from those, so none can be stated at odds with the masses. The tick unit travels so an axis
    can be labeled truthfully."""

    scenario_hash: HashDigest
    tick_unit: TickUnit
    audience_pmfs: FrozenDict[Identifier, PMF5]
    audience_shares: FrozenDict[Identifier, UnitInterval]
    community_pmfs: FrozenDict[Identifier, PMF5]
    community_sizes: FrozenDict[Identifier, PositiveInt]

    @model_validator(mode="after")
    def _weights_cover_exactly_the_masses(self) -> Self:
        if not self.audience_pmfs:
            raise ValueError("a digest reports response masses for at least one audience")
        if set(self.audience_shares) != set(self.audience_pmfs):
            raise ValueError("every audience with a response mass needs a share, and only those")
        if set(self.community_sizes) != set(self.community_pmfs):
            raise ValueError("every community with a response mass needs a size, and only those")
        proportions_sum_to_one(self.audience_shares)
        return self

    @computed_field
    @property
    def adoption(self) -> float:
        """Share-weighted top-two-box purchase intent: the probability of answering 4 or 5 on the five-point scale."""
        names = sorted(self.audience_pmfs)
        total = sum(self.audience_shares[name] for name in names)
        weighted = sum(self.audience_shares[name] * (self.audience_pmfs[name][3] + self.audience_pmfs[name][4]) for name in names)
        return min(1.0, max(0.0, weighted / total))

    @computed_field
    @property
    def polarization(self) -> float | None:
        """Size-weighted divergence between communities' response masses: whether social dynamics created
        camps. A population that formed fewer than two communities has no polarization to measure, so it is
        reported as not measurable rather than as a measured zero."""
        if len(self.community_pmfs) < 2:
            return None
        names = sorted(self.community_pmfs)
        return _normalized_divergence([self.community_pmfs[n] for n in names], [float(self.community_sizes[n]) for n in names])

    @computed_field
    @property
    def audience_divergence(self) -> float:
        """Share-weighted divergence between audiences' response masses: whether the concept splits the target market."""
        names = sorted(self.audience_pmfs)
        return _normalized_divergence([self.audience_pmfs[n] for n in names], [self.audience_shares[n] for n in names])


def ensure_same_tick_unit(*digests: OutcomeDigest) -> None:
    """Comparing digests whose tick units differ is refused; two studies compare only
    when their ticks carry the same real-world duration."""
    units = {digest.tick_unit for digest in digests}
    if len(units) > 1:
        raise ValueError(f"digests with differing tick units are not comparable: {sorted(u.value for u in units)}")


class Report(SimBaseModel):
    """The run's document: the configuration it describes, trust stated once, findings each falsifiable,
    and one digest per scenario of that run. The configuration discloses the method — model pins, seeds,
    templates and anchor sets — and every digest, anomaly and ranking must belong to one of its scenarios."""

    config: RunConfig
    trust: TrustStatement
    findings: tuple[Finding, ...]
    anomalies: tuple[Anomaly, ...] = ()
    objection_clusters: tuple[ObjectionCluster, ...] = ()
    digests: tuple[OutcomeDigest, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _digests_describe_this_runs_scenarios(self) -> Self:
        scenarios = {canonical_hash(scenario): scenario for scenario in self.config.scenarios}
        if _repeated(digest.scenario_hash for digest in self.digests):
            raise ValueError("a scenario is digested more than once")
        for digest in self.digests:
            scenario = scenarios.get(digest.scenario_hash)
            if scenario is None:
                raise ValueError(f"digest for scenario {digest.scenario_hash}, which this run does not configure")
            if digest.tick_unit is not scenario.tick_unit:
                raise ValueError(f"digest in {digest.tick_unit.value} ticks for a scenario run in {scenario.tick_unit.value}")
            if scenario.audience_weights is not None and set(digest.audience_pmfs) != set(scenario.audience_weights):
                raise ValueError(f"digest audiences {sorted(digest.audience_pmfs)} differ from the scenario's {sorted(scenario.audience_weights)}")
        ensure_same_tick_unit(*self.digests)
        return self

    @model_validator(mode="after")
    def _findings_and_anomalies_belong_to_this_run(self) -> Self:
        if _repeated(finding.finding_id for finding in self.findings):
            raise ValueError(f"finding ids repeated: {_repeated(f.finding_id for f in self.findings)}")
        digested = {digest.scenario_hash for digest in self.digests}
        for finding in self.findings:
            undigested = sorted(set(finding.ranked_scenarios) - digested)
            if undigested:
                raise ValueError(f"finding {finding.finding_id} ranks scenarios this report does not digest: {undigested}")
        horizons = {canonical_hash(scenario): scenario.horizon_ticks for scenario in self.config.scenarios}
        for anomaly in self.anomalies:
            if anomaly.scenario_hash not in horizons:
                raise ValueError(f"{anomaly.kind.value} anomaly for scenario {anomaly.scenario_hash}, which this run does not configure")
            if anomaly.tick >= horizons[anomaly.scenario_hash]:
                raise ValueError(f"{anomaly.kind.value} anomaly at tick {anomaly.tick}, beyond its scenario's horizon")
        return self
