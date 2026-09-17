"""The append-only record and the questions that can be asked of it.

The runner hands over a tick's events with its ``tick_closed`` in one call; ``write`` lands
them in one SQLite transaction and refuses a ``(world_id, seq)`` it already holds.
"""

from .derive import apply_change, derive_beliefs, derive_edges, derive_verbatims, filter_events, resolve_events
from .errors import (
    DuplicateEntryError,
    DuplicateSequenceError,
    FinalizedError,
    TraceError,
    UnknownRunError,
    UnknownWorldError,
)
from .fake import InMemoryRunRegistry, InMemoryTraceSink
from .registry import SqliteRunRegistry, replay_config
from .store import TraceStore, create_world, finalize, view, write
from .views import ParquetTraceView, SqliteTraceView

__all__ = [
    "DuplicateEntryError",
    "DuplicateSequenceError",
    "FinalizedError",
    "InMemoryRunRegistry",
    "InMemoryTraceSink",
    "ParquetTraceView",
    "SqliteRunRegistry",
    "SqliteTraceView",
    "TraceError",
    "TraceStore",
    "UnknownRunError",
    "UnknownWorldError",
    "apply_change",
    "create_world",
    "derive_beliefs",
    "derive_edges",
    "derive_verbatims",
    "filter_events",
    "finalize",
    "replay_config",
    "resolve_events",
    "view",
    "write",
]
