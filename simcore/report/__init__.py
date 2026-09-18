"""Turning findings into documents: one pass, two formats, no computation.

Findings arrive already validated by `analysis`; this module formats them into markdown
for a person and JSON-ready data for the pages, from one intermediate over the same
finding set. It imports nothing from `analysis` and computes no statistic of its own.
"""

from ._pack import RenderedReport, ReportPack
from ._render import REPORT_CONTRACT_VERSION, render

__all__ = ["REPORT_CONTRACT_VERSION", "RenderedReport", "ReportPack", "render"]
