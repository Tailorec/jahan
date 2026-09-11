"""The report domain: what the engine says — findings, trust, anomalies, and outcome digests."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .base import FrozenDict, Identifier, NonEmptyStr, NonNegativeInt, RunId, SimBaseModel, UnitInterval
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
