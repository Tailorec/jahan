"""The seams around the record: what writes it, what reads it, and what pins the run.

A tick is handed over whole and written in one transaction, or not at all (ADR 0033). A read asks
one of five questions and gets frozen models back, whether the run is still going or long finished
(ADR 0034) — the caller never learns which storage answered. The registry pins what a resume must
check and what a report must say about spend nobody recorded.
"""

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from simcore.schemas import (
        BeliefHistory,
        EventFilter,
        RunRegistryEntry,
        TraceEdge,
        TraceEvent,
        VerbatimGroup,
        VerbatimGrouping,
    )


@runtime_checkable
class TraceSink(Protocol):
    """Where a run's events go. The runner is the only caller; nothing else writes."""

    def write(self, events: "Sequence[TraceEvent]") -> None:
        """One tick's events, in one transaction. A `(world_id, seq)` already held is refused."""
        ...

    def finalize(self, world_id: str) -> None:
        """Turn a finished world's live record into its lasting one. Idempotent."""
        ...


@runtime_checkable
class TraceView(Protocol):
    """The five questions a run's record answers, and the only ones.

    A reader cannot reach past this set: no shape returns a path, a cursor or a frame, and none
    takes open keyword arguments. That is the whole point — the design this replaces passed views
    as an undefined wide interface, and the same derivation ended up in two consumers.
    """

    def events(self, asked: "EventFilter") -> "tuple[TraceEvent, ...]":
        """The events the filter asks for, in sequence order."""
        ...

    def beliefs(self, persona_id: str) -> "BeliefHistory":
        """One persona's beliefs over the run, derived from its snapshots and turns."""
        ...

    def edges(self) -> "tuple[TraceEdge, ...]":
        """What travelled between personas, per pair and channel."""
        ...

    def verbatims(self, grouping: "VerbatimGrouping") -> "tuple[VerbatimGroup, ...]":
        """What personas said, gathered under the keys of the grouping asked for."""
        ...

    def resolve(self, trace_ids: "Iterable[str]") -> "tuple[TraceEvent, ...]":
        """Exactly the events named, so a finding can cite its evidence; absent ids raise."""
        ...


@runtime_checkable
class RunRegistry(Protocol):
    """One entry per run: everything a replay needs, and what the run knows about its own spend."""

    def record(self, entry: "RunRegistryEntry") -> None:
        """Write or update this run's entry. A second entry for the same run is refused."""
        ...

    def entry(self, run_id: str) -> "RunRegistryEntry | None":
        """This run's entry, or nothing when the run is unknown."""
        ...
