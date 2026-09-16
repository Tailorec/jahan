"""`holdout`: the measurement projection's credibility rests on (ADR 0019).

On rows carrying measured attitudes, a declared attitude set is hidden, projected from the conditioning
set through the production path, and scored — marginal distance, calibration of the sampled
distributions, and how much of the attitudes' dependence on demographics is recovered — beside a
baseline that samples each attitude from its demographic-conditional marginal estimated on the rows
that were *not* held out. It runs on the fake in CI and against a real endpoint when a user points it
at one: ``python -m simcore.holdout``."""

from ._evaluate import AttributeScore, HoldoutReport, evaluate, select_measured_rows

__all__ = ["AttributeScore", "HoldoutReport", "evaluate", "select_measured_rows"]
