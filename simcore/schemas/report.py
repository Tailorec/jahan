"""The report domain: what the engine says — findings, trust, anomalies, and outcome digests."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .base import (
    FrozenDict,
    HashDigest,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PositiveInt,
    RunId,
    SimBaseModel,
    UnitInterval,
)
from .enums import AnomalyKind, Confidence, FindingKind, TickUnit, TrustLevel
from .run import ModelPins
from .sim import PMF5
from .trace import EventId


class CalibrationRef(SimBaseModel):
    """Evidence that a trust level above uncalibrated was earned; nothing in this
    repository produces one — every field must be supplied from outside."""

    benchmark: Identifier
    study_id: Identifier
    checked_at: AwareDatetime


class TrustStatement(SimBaseModel):
    """Calibration status, stated once per run — never per finding."""

    level: TrustLevel
    calibration_ref: CalibrationRef | None = None
    caveats: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _levels_above_uncalibrated_require_a_reference(self) -> Self:
        if self.level is not TrustLevel.UNCALIBRATED and self.calibration_ref is None:
            raise ValueError(f"{self.level.value} requires a calibration reference")
        return self


class Finding(SimBaseModel):
    """One statement the engine makes about what happened. It cannot exist without the
    trace records supporting it and the real-world test that would falsify it."""

    finding_id: Identifier
    kind: FindingKind
    statement: NonEmptyStr
    evidence_trace_ids: tuple[EventId, ...] = Field(min_length=1)
    disconfirming_test: NonEmptyStr
    confidence: Confidence


class Anomaly(SimBaseModel):
    """A rule-based flag over the trace; it carries the evidence that produced it."""

    kind: AnomalyKind
    tick: NonNegativeInt
    evidence_trace_ids: tuple[EventId, ...] = Field(min_length=1)


class ObjectionCluster(SimBaseModel):
    """Verbatims clustered by embedding similarity, addressing one recurring objection."""

    label: NonEmptyStr
    verbatim_trace_ids: tuple[EventId, ...] = Field(min_length=1)
    size: PositiveInt = Field(gt=0)


class OutcomeDigest(SimBaseModel):
    """What happened in one scenario's worlds: response masses per audience and per
    community, with polarization defined over communities and audience-level divergence
    reported separately. The tick unit travels so an axis can be labeled truthfully."""

    scenario_hash: HashDigest
    tick_unit: TickUnit
    adoption: UnitInterval
    audience_pmfs: FrozenDict[Identifier, PMF5] = Field(min_length=1)
    community_pmfs: FrozenDict[Identifier, PMF5] = Field(min_length=1)
    polarization: UnitInterval
    audience_divergence: UnitInterval


def ensure_same_tick_unit(*digests: OutcomeDigest) -> None:
    """Comparing digests whose tick units differ is refused; two studies compare only
    when their ticks carry the same real-world duration."""
    units = {digest.tick_unit for digest in digests}
    if len(units) > 1:
        raise ValueError(f"digests with differing tick units are not comparable: {sorted(u.value for u in units)}")


class Report(SimBaseModel):
    """The run's document: trust stated once, findings each falsifiable, digests attached."""

    run_id: RunId
    trust: TrustStatement
    pins: ModelPins
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    findings: tuple[Finding, ...]
    anomalies: tuple[Anomaly, ...] = ()
    objection_clusters: tuple[ObjectionCluster, ...] = ()
    digests: tuple[OutcomeDigest, ...] = Field(min_length=1)
