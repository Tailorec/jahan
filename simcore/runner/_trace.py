"""In-memory trace and registry adapters for runner boundary tests.

The runner writes through a port with a fake in its tests; the real writer
arrives at merge (Phase 8). The fake honours the same contract the real one
must: one tick in one call, `(world_id, seq)` refusals on duplicates.
"""

from __future__ import annotations

from simcore.schemas import RunRegistryEntry, check_registry_update, TraceEvent


class InMemoryTraceSink:
    """A trace that holds whole ticks in memory, keyed by world."""

    def __init__(self) -> None:
        import threading

        self._events: dict[str, list[TraceEvent]] = {}
        self._seen: set[tuple[str, int]] = set()
        self.writes: list[list[TraceEvent]] = []
        self.finalized: list[str] = []
        self.published: dict[str, str] = {}
        self._lock = threading.Lock()

    def write(self, events: object) -> None:
        batch = tuple(events)  # type: ignore[arg-type]
        with self._lock:
            for event in batch:
                key = (event.world_id, event.seq)
                if key in self._seen:
                    raise ValueError(f"duplicate (world_id, seq): {key}")
            for event in batch:
                self._seen.add((event.world_id, event.seq))
                self._events.setdefault(event.world_id, []).append(event)
            self.writes.append(list(batch))

    def finalize(self, world_id: str) -> None:
        """Remembered rather than performed: in memory there is nothing to convert, and a test
        can see that a finished world was handed over."""
        self.finalized.append(world_id)

    def note_published(self, stimuli) -> None:
        """What the tick published, before its turns are taken — the runner's hook so an agent
        reading `published` sees the current tick's words, not only earlier ticks'."""
        with self._lock:
            for stimulus in stimuli:
                self.published[stimulus.stimulus_id] = stimulus.text

    def events_for(self, world_id: str) -> tuple[TraceEvent, ...]:
        return tuple(sorted(self._events.get(world_id, []), key=lambda e: e.seq))

    def all_events(self) -> tuple[TraceEvent, ...]:
        out: list[TraceEvent] = []
        for events in self._events.values():
            out.extend(events)
        return tuple(sorted(out, key=lambda e: (e.world_id, e.seq)))


class InMemoryRegistry:
    """One entry per run, plus runner bookkeeping the schema does not carry."""

    def __init__(self) -> None:
        self._entries: dict[str, RunRegistryEntry] = {}
        # Counted so a test can see the difference between pinning a run and moving it.
        self.records = 0
        self.updates = 0
        self.forced: set[str] = set()

    def record(self, entry: RunRegistryEntry) -> None:
        """Pin a new run. A second entry is refused, as the real registry refuses it."""
        if entry.config.run_id in self._entries:
            raise ValueError(f"an entry for run {entry.config.run_id} already exists")
        self._entries[entry.config.run_id] = entry
        self.records += 1

    def update(self, entry: RunRegistryEntry) -> None:
        """Move status, recorded cost and discarded ticks; never what a replay pins."""
        held = self._entries.get(entry.config.run_id)
        if held is None:
            raise KeyError(f"no entry for run {entry.config.run_id}")
        check_registry_update(held, entry)
        self._entries[entry.config.run_id] = entry
        self.updates += 1

    def entry(self, run_id: str) -> RunRegistryEntry | None:
        return self._entries.get(run_id)

    def mark_forced(self, run_id: str) -> None:
        self.forced.add(run_id)

    def is_forced(self, run_id: str) -> bool:
        return run_id in self.forced
