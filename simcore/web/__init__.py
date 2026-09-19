"""M13 `web`: the engine over HTTP.

The web layer derives nothing (ADR 0045): it serialises, filters, pages and
streams. Every number it returns is a field of something `analysis`, `trace` or
a contract produced — the five shapes, `TraceSummary`, the digest, findings,
clusters, anomalies and the report. A panel wanting an underived number is
blocked until `analysis` derives it.

The registry decides which backend a view opens: `TraceStore.view` answers from
the live record while a run is going and from the finalized one when it ends,
so a live run and a finished run answer identically through the same endpoints.
Nothing reaches storage another way, and no endpoint returns a row, a frame, a
filesystem path or a cursor.
"""

from . import _lifecycle as lifecycle
from .app import create_app

__all__ = ["create_app", "lifecycle"]
