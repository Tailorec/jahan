"""The trust guard: one statement per run, and no path to a chat model.

The run's calibration is stated once as its `TrustStatement` and is `UNCALIBRATED`;
anything higher needs a `CalibrationRef` pinning a benchmark and human study by hash,
which nothing in this repository can produce. Findings carry only their own confidence.
The only model call in this package is embedding, through the run's pinned embedding
model — a digest or finding built from a trace in a different embedding space is refused.
"""

from simcore.schemas import CalibrationRef, TrustStatement


def trust_statement(
    level: str = "uncalibrated",
    calibration_ref: CalibrationRef | dict | None = None,
    caveats: tuple[str, ...] = ("the engine has never been benchmarked against human purchase intent",),
) -> TrustStatement:
    """State a run's calibration once. Above `UNCALIBRATED` without a reference raises."""
    return TrustStatement.model_validate({
        "level": level,
        "calibration_ref": calibration_ref,
        "caveats": list(caveats),
    })
