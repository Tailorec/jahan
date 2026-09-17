"""The five questions a run's record answers, over either backend.

`SqliteTraceView` answers from the live record while a run is going or paused; only ticks
that closed are shown, so a view is always consistent though it may be behind.
`ParquetTraceView` answers from the finalized record. Both derive beliefs and edges through
`derive` — one implementation — and every shape returns frozen models, never storage.
"""

from collections.abc import Iterable
from pathlib import Path

from simcore.schemas import BeliefHistory, EventFilter, TraceEdge, TraceEvent, VerbatimGroup, VerbatimGrouping

from . import derive as _derive


class _ViewBase:
    def _all_events(self) -> tuple[TraceEvent, ...]:
        raise NotImplementedError

    def events(self, asked: EventFilter) -> tuple[TraceEvent, ...]:
        """The events the filter asks for, ordered by `(persona_id, tick, seq)`."""
        if not isinstance(asked, EventFilter):
            raise TypeError(f"events takes a typed filter, not {type(asked).__name__}; build the filter first")
        return _derive.filter_events(self._all_events(), asked)

    def beliefs(self, persona_id: str) -> BeliefHistory:
        """One persona's beliefs over the run, derived from its snapshots and turns."""
        return _derive.derive_beliefs(self._all_events(), persona_id)

    def edges(self) -> tuple[TraceEdge, ...]:
        """What travelled between personas, per pair and channel."""
        return _derive.derive_edges(self._all_events())

    def verbatims(self, grouping: VerbatimGrouping) -> tuple[VerbatimGroup, ...]:
        """What personas said, gathered under the keys of the grouping asked for."""
        if not isinstance(grouping, VerbatimGrouping):
            raise TypeError(f"verbatims takes a grouping, not {type(grouping).__name__}")
        return _derive.derive_verbatims(self._all_events(), grouping)

    def resolve(self, trace_ids: Iterable[str]) -> tuple[TraceEvent, ...]:
        """Exactly the events named, so a finding can cite its evidence; absent ids raise."""
        if isinstance(trace_ids, (str, bytes)):
            raise TypeError("resolve takes event ids, not a single string")
        return _derive.resolve_events(self._all_events(), trace_ids)


class SqliteTraceView(_ViewBase):
    """A live or paused run, answered from SQLite. Sees every closed tick and nothing more."""

    def __init__(self, store, run_id: str, worlds: tuple[str, ...]) -> None:
        self._store = store
        self._run_id = run_id
        self._worlds = worlds

    def _all_events(self) -> tuple[TraceEvent, ...]:
        events: list[TraceEvent] = []
        for world_id in self._worlds:
            events.extend(_derive.visible_events(self._store.read_live(self._run_id, world_id)))
        return tuple(sorted(events, key=lambda e: (e.world_id, e.seq)))


class ParquetTraceView(_ViewBase):
    """A finished run, answered from Parquet. Answers identically to the live view."""

    def __init__(self, root: str | Path, run_id: str, worlds: tuple[str, ...]) -> None:
        self._root = Path(root)
        self._run_id = run_id
        self._worlds = worlds

    def _all_events(self) -> tuple[TraceEvent, ...]:
        from .finalize import read_finalized_events

        events: list[TraceEvent] = []
        for world_id in self._worlds:
            # The same visibility rule as the live view, so the two cannot disagree.
            events.extend(_derive.visible_events(read_finalized_events(self._root, self._run_id, world_id)))
        return tuple(sorted(events, key=lambda e: (e.world_id, e.seq)))
