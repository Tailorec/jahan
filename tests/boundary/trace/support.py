"""Shared scaffolding for the trace boundary suite: one store per test, seeded from the
representative partition. Every test runs against a temporary directory and reaches no network."""

from pathlib import Path

from simcore.schemas import PartitionHeader, RunRegistryEntry, TraceEvent
from simcore.trace import TraceStore
from tests.study_builders import partition_header_payload, partition_payload


def seed_header_and_entry(store: TraceStore, **header_overrides):
    """Record the representative run and pin its world's header; returns `(header, entry)`."""
    header = PartitionHeader.model_validate(partition_header_payload(**header_overrides))
    entry = RunRegistryEntry.model_validate(
        {
            "config": header.config.model_dump(mode="json"),
            "contract_version": header.contract_version,
            "status": "running",
            "engine_version": "0a35555",
        }
    )
    store.registry.record(entry)
    store.create_world(entry.config.run_id, header)
    return header, entry


def partition_events(**header_overrides) -> tuple[list[TraceEvent], PartitionHeader]:
    """The representative partition's events as validated models, with their header."""
    payload = partition_payload(**header_overrides)
    header = PartitionHeader.model_validate(payload["header"])
    return [TraceEvent.model_validate(record) for record in payload["events"]], header


def write_by_tick(store: TraceStore, events: list[TraceEvent]) -> None:
    """Hand over one tick per call, the way the runner does — events plus their `tick_closed`."""
    ticks: dict[int, list[TraceEvent]] = {}
    for event in events:
        ticks.setdefault(event.tick, []).append(event)
    for tick in sorted(ticks):
        store.write(ticks[tick])


def seed_store(store: TraceStore, **header_overrides):
    """A store holding the whole representative world; returns `(header, entry, events)`."""
    header, entry = seed_header_and_entry(store, **header_overrides)
    events, _ = partition_events(**header_overrides)
    write_by_tick(store, events)
    return header, entry, events


def hot(events: list[TraceEvent]) -> list[TraceEvent]:
    """The same records through the hot path: `model_construct` from payload models, unvalidated."""
    rebuilt = []
    for event in events:
        rebuilt.append(
            TraceEvent.model_construct(
                event_id=event.event_id,
                world_id=event.world_id,
                tick=event.tick,
                seq=event.seq,
                persona_id=event.persona_id,
                payload=event.payload,
            )
        )
    return rebuilt
