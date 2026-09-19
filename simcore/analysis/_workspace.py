"""The workspace summary: a derived shape over registry entries alone.

Studies run, spend against budget, personas simulated, reports written — read from
entries rather than by walking partitions.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from simcore.schemas import (
    NonNegativeInt,
    RunRegistryEntry,
    RunStatus,
    SimBaseModel,
)


class WorkspaceSummary(SimBaseModel):
    """The workspace-level summary derived from registry entries alone.

    Computes nothing from a trace: counts and costs come straight from entries.
    """

    total_studies: NonNegativeInt = 0
    completed_studies: NonNegativeInt = 0
    running_studies: NonNegativeInt = 0
    partial_studies: NonNegativeInt = 0
    total_spend: float = 0.0
    total_personas: NonNegativeInt = 0
    total_budget: float = 0.0
    reports_written: NonNegativeInt = 0


def workspace_summary(
    entries: Sequence[RunRegistryEntry],
    *,
    report_run_ids: Collection[str] | None = None,
) -> WorkspaceSummary:
    """Derive a workspace summary from a sequence of RunRegistryEntry objects.

    Every number comes from the entries themselves; no partition or trace file is walked.
    A run that reached `completed` has not necessarily written its report — analysis
    can fail after the worlds finish — so the caller that knows which runs have a report
    names them, and only those count as reports written. Without that knowledge a
    completed run is the best the entries can say.
    """
    total = len(entries)
    completed = sum(1 for e in entries if e.status is RunStatus.COMPLETED or e.status.value == "completed")
    running = sum(1 for e in entries if e.status is RunStatus.RUNNING or e.status.value == "running")
    partial = sum(1 for e in entries if e.status is RunStatus.PARTIAL or e.status.value == "partial")
    total_spend = sum(float(e.recorded_cost) for e in entries)
    total_personas = sum(int(getattr(e, "population_size", 0)) for e in entries)
    total_budget = sum(
        float(e.config.budget.max_cost) for e in entries if getattr(e.config, "budget", None) is not None
    )
    reports = (
        completed
        if report_run_ids is None
        else sum(1 for e in entries if e.config.run_id in report_run_ids)
    )

    return WorkspaceSummary(
        total_studies=total,
        completed_studies=completed,
        running_studies=running,
        partial_studies=partial,
        total_spend=round(total_spend, 4),
        total_personas=total_personas,
        total_budget=round(total_budget, 4),
        reports_written=reports,
    )
