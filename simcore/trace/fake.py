"""In-memory adapters: the fake the boundary tests that need no filesystem run against.

Both satisfy their ports (`TraceSink`, `RunRegistry`) and follow the same rules as the
SQLite implementations — whole ticks, refused duplicates, refused second entries — so a
test that passes here constrains the production path too.
"""

from collections.abc import Iterable, Sequence

from simcore.schemas import check_registry_update, RunRegistryEntry, TraceEvent

from . import derive as _derive
from .errors import DuplicateEntryError, UnknownRunError, DuplicateSequenceError


class InMemoryTraceSink:
    """Where a test's events go when no directory is wanted."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, int], TraceEvent] = {}
        self._finalized: set[str] = set()

    def write(self, events: Sequence[TraceEvent]) -> None:
        from collections.abc import Mapping as _Mapping

        events = tuple(events)
        if not events:
            return
        for event in events:
            if not isinstance(event, TraceEvent):
                raise TypeError(f"the write path takes payload models, not mappings ({type(event).__name__})")
        worlds = {event.world_id for event in events}
        if len(worlds) != 1:
            raise ValueError(f"one call writes one world's tick, got {sorted(worlds)}")
        from .errors import FinalizedError

        if next(iter(worlds)) in self._finalized:
            raise FinalizedError(f"world {next(iter(worlds))} is finalized and read-only")
        held = {seq for (world, seq) in self._events if world == events[0].world_id}
        incoming = [event.seq for event in events]
        if any(seq in held for seq in incoming):
            identical = (
                len(set(incoming)) == len(incoming)
                and all(seq in held for seq in incoming)
                and all(self._events[(events[0].world_id, event.seq)] == event for event in events)
            )
            if identical and set(incoming) <= held:
                return
            raise DuplicateSequenceError(f"world {events[0].world_id} already holds some of {sorted(incoming)}")
        for event in events:
            self._events[(event.world_id, event.seq)] = event

    def finalize(self, world_id: str) -> None:
        self._finalized.add(world_id)

    def events_of(self, world_id: str) -> tuple[TraceEvent, ...]:
        return tuple(
            sorted((e for (w, _) in self._events for e in [self._events[(w, _)]] if w == world_id),
                   key=lambda e: e.seq)
        )

    def visible_of(self, world_id: str) -> tuple[TraceEvent, ...]:
        return _derive.visible_events(self.events_of(world_id))


class InMemoryRunRegistry:
    """One entry per run, in memory. A second entry for the same run is refused."""

    def __init__(self) -> None:
        self._entries: dict[str, RunRegistryEntry] = {}

    def record(self, entry: RunRegistryEntry) -> None:
        if not isinstance(entry, RunRegistryEntry):
            raise TypeError(f"the registry records entries, not mappings ({type(entry).__name__})")
        if entry.config.run_id in self._entries:
            raise DuplicateEntryError(f"an entry for run {entry.config.run_id} already exists")
        self._entries[entry.config.run_id] = entry

    def entry(self, run_id: str) -> RunRegistryEntry | None:
        return self._entries.get(run_id)

    def update(self, entry: RunRegistryEntry) -> None:
        """Move status, recorded cost and discarded ticks; never what a replay pins."""
        held = self._entries.get(entry.config.run_id)
        if held is None:
            raise UnknownRunError(f"no entry for run {entry.config.run_id}")
        check_registry_update(held, entry)
        self._entries[entry.config.run_id] = entry
